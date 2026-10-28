"""A MEASUREMENT of when SofaScore stops revising a finished match. Not a pipeline step.

The question. ``data_ready`` is stamped at +1h on the premise that by then the
provider has said its last word. The first late look (+12h, 28/10/2026) showed it
had not: on Roma-Cagliari 19 shots of 39 had a different xG/xGOT than at +1h, on
Torino-Como 11 of 29, and the late check reported "invariata" on both because it
compares only the facts (score, goals, assists, own goals). So the "final" numbers
are not final, and the votes users read at night move by morning.

What we do NOT know is WHEN the revision happens. Reading a match at every offset in
``PROBE_OFFSETS`` and keeping what each reading said answers it: for each match the
last reading is the reference, and the distance of every earlier one from it says
how much was still to come. The offset where that distance reaches ~0 for the
typical match is where the single confirmation belongs; the intermediate readings
exist for this measurement only and are NOT meant to stay (see
``analyze_revision_probe``).

Three choices that keep it a measurement:

* It never imports. Nothing here writes to the database, so no vote can move
  because of it.
* It fetches into its OWN cache directory (``settings.VFOOT_REVISION_PROBE_DIR``).
  The application's cache is a handoff buffer read by the importer; a probe that
  overwrote it would be a second, silent way of changing what gets imported.
* It is OFF unless ``VFOOT_REVISION_PROBE=1``, and it runs only on a tick with
  nothing else due, one reading per tick — the same lowest priority as the late
  check, for the same reason: the egress namespace is one.

Each reading is four requests (event, lineups, incidents, shot map; the ``live``
kind, no heatmaps) and a match gets ``len(PROBE_OFFSETS)`` of them.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings

from realdata.models import Match
from realdata.services import egress_client
from realdata.services.sofascore_client import (
    SofaScoreBlocked, SofaScoreClient, SofaScoreError,
)

# Offsets from the final whistle. +1h is the current confirmation (the baseline the
# users saw); +12h is the late check; the ones between are the point of the test.
PROBE_OFFSETS: tuple[tuple[str, timedelta], ...] = (
    ("1h", timedelta(hours=1)),
    ("2h", timedelta(hours=2)),
    ("4h", timedelta(hours=4)),
    ("6h", timedelta(hours=6)),
    ("9h", timedelta(hours=9)),
    ("12h", timedelta(hours=12)),
    ("24h", timedelta(hours=24)),
    ("48h", timedelta(hours=48)),
)

# How late a reading may still be taken and count as that offset. The real elapsed
# time is recorded in each reading, so a late one is still honest data; the cap only
# stops a tick that was down for a day from filling the file with "6h" readings
# taken at 30h.
GRACE = timedelta(hours=2)

# What a keeper's vote reads out of the squad sheet besides the shots.
PLAYER_KEYS = ("goalsPrevented", "keeperSaveValue", "expectedAssists", "rating")


def enabled() -> bool:
    return bool(getattr(settings, "VFOOT_REVISION_PROBE", False))


def _dir() -> Path:
    return Path(settings.VFOOT_REVISION_PROBE_DIR)


def readings_file() -> Path:
    return _dir() / "readings.jsonl"


def done_readings(path: Path | None = None) -> set[tuple[str, str]]:
    """``{(event_id, offset_label)}`` already taken. The file is the only state."""
    path = path or readings_file()
    out: set[tuple[str, str]] = set()
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        out.add((str(r["match"]), r["offset"]))
    return out


def candidates(now: datetime):
    """Finished matches that may still be due a reading: the last 48h + grace."""
    horizon = PROBE_OFFSETS[-1][1] + GRACE
    return (Match.objects
            .filter(status=Match.STATUS_FINISHED, finished_at__isnull=False,
                    finished_at__gt=now - horizon)
            .exclude(external_id="")
            .exclude(competition_season__external_id="")
            .select_related("competition_season__season")
            .order_by("finished_at"))


def plan(now: datetime, matches, done: set[tuple[str, str]]) -> list[tuple[Match, str]]:
    """``(match, offset_label)`` pairs due at ``now``, most overdue first."""
    due: list[tuple[datetime, Match, str]] = []
    for m in matches:
        if m.finished_at is None or not m.external_id:
            continue
        for label, off in PROBE_OFFSETS:
            at = m.finished_at + off
            if at <= now < at + GRACE and (str(m.external_id), label) not in done:
                due.append((at, m, label))
    due.sort(key=lambda t: t[0])
    return [(m, label) for _at, m, label in due]


def digest(client: SofaScoreClient, event_id: int) -> dict:
    """What a reading keeps: each shot's xG/xGOT and the squad-sheet numbers a
    keeper's (and a creator's) vote reads. Plain JSON, keyed by the provider's ids."""
    shots = {}
    for s in client.shots_records(event_id):
        sid = s.get("id")
        if sid is None:
            continue
        shots[str(sid)] = [s.get("xg"), s.get("xgot")]
    players = {}
    for rec in client.player_stats_records(event_id):
        pid = rec.get("id")
        if pid is None:
            continue
        players[str(pid)] = {k: rec.get(k) for k in PLAYER_KEYS if rec.get(k) is not None}
    return {"shots": shots, "players": players}


def take(match: Match, label: str, now: datetime) -> bool:
    """One reading. True iff it went through (and was appended); False when the
    egress was blocked — nothing is written and the next tick retries."""
    cache = _dir() / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    # ``live`` = the four light endpoints. The worker drops what it is about to
    # rewrite in this directory itself (fetch_worker.purge), so a second reading of
    # the same match cannot answer with the first one's bytes.
    if not egress_client.run_egress(["fetch", "--match-ids", str(match.external_id),
                                     "--kind", "live", "--cache-dir", str(cache)]):
        return False
    client = SofaScoreClient(cache_dir=cache, max_retries=1, logger=lambda _m: None)
    try:
        d = digest(client, int(match.external_id))
    except (SofaScoreBlocked, SofaScoreError):
        return False
    row = {
        "match": str(match.external_id), "label": str(match),
        "offset": label,
        "finished_at": match.finished_at.isoformat(),
        "taken_at": now.isoformat(),
        "elapsed_min": round((now - match.finished_at).total_seconds() / 60),
        **d,
    }
    with readings_file().open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    return True
