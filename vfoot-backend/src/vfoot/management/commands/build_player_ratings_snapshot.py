"""Write the versioned snapshot of season player ratings (the listone "valore").

Why a file in the repository and not a table in the database: the slim copy from
``export_dev_db`` has no zone features, so the votes cannot be recomputed there —
and a table would have to be filled BEFORE the export, which does nothing for the
copies people have already downloaded. Shipping the numbers with the SOURCE reaches
those too, with a plain ``git pull``, and without asking anyone to replace their
database and lose the leagues and test data inside it. It is 9 KB of JSON against
54 MB of SQLite.

It is a FALLBACK, never an override: ``season_player_ratings`` uses it only when
computing from the zone features yields nothing. A full database always wins.

This command PUBLISHES: what it writes ends up on other people's machines and on
the server, so it decides what is fit to leave this database. Two things are not,
and both are refused here rather than in the reader:

  * a season that has not really been played. The development database contains a
    SIMULATED 2026-27 (``simulate_sofascore_season``), which is complete, coherent
    and scoreable — and inventing it was the point. Publishing it would put invented
    football in front of users, so a season whose "finished" matches kick off in the
    future is skipped;
  * a season without a provider identity, because it could then only be addressed by
    primary key, which is exactly the thing that broke — see ``_portable_key``.

Run it whenever the scoring model changes — same discipline as
``calibrate_vote_reference``, and in the same order: calibrate first, snapshot
after, because the snapshot records the fingerprint of the model that produced it,
``tests_player_ratings_snapshot`` fails when the two no longer agree, and the reader
warns if one ever ships anyway.

    manage.py build_player_ratings_snapshot
    manage.py build_player_ratings_snapshot --check   # CI: is it up to date?
"""

from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand

from realdata.models import CompetitionSeason, Match
from vfoot.services.classic_pagella import data_version
from vfoot.services.player_ratings import (
    SNAPSHOT_FORMAT, SNAPSHOT_PATH, _compute_season_player_ratings,
    _portable_key, clear_snapshot_cache,
)
from vfoot.services.vote_reference import scoring_fingerprint


def unplayed_finished_matches(cs) -> int:
    """Matches this season calls finished whose kick-off is still in the future.

    A contradiction on real data, and the signature of football that was invented:
    the simulator plays a whole 2026-27 at its own dates, so from the real calendar
    its 220 finished matches all lie ahead. Read from the SYSTEM clock on purpose —
    ``timezone.now`` is the one thing ``VFOOT_FAKE_NOW`` moves (see
    ``vfoot/simclock.py``), and under the simulated clock a simulated season looks
    perfectly played, which is precisely when this check must not be fooled.
    """
    return Match.objects.filter(
        competition_season=cs, status=Match.STATUS_FINISHED,
        kickoff__gt=datetime.now(dt_timezone.utc)).count()


def build_snapshot(report=None) -> dict:
    """Recompute every PUBLISHABLE season from the zone features."""
    say = report or (lambda _msg: None)
    seasons = {}
    for cs in CompetitionSeason.objects.all().order_by("season__code"):
        # Deliberately the raw computation, not season_player_ratings: going
        # through the cache could write the previous snapshot back into the new
        # one, and going through the fallback would let a stale file perpetuate
        # itself for a season that can no longer be computed.
        ratings = _compute_season_player_ratings(cs.id)
        if not ratings:
            continue
        invented = unplayed_finished_matches(cs)
        if invented:
            say(f"  {cs}: SALTATA — {invented} partite 'finite' con calcio d'inizio "
                f"nel futuro (stagione simulata, non si pubblica).")
            continue
        if not (cs.external_source and cs.external_id):
            say(f"  {cs}: SALTATA — nessuna identita' del provider, non e' "
                f"indirizzabile fuori da questo database.")
            continue
        players = {p.external_source + ":" + p.external_id: d
                   for p, d in _with_players(ratings)}
        seasons[_portable_key(cs)] = {
            "label": str(cs),
            "data_version": data_version(cs.id),
            "ratings": {k: [d["avg"], d["n"]] for k, d in sorted(players.items())},
        }
    return {"format": SNAPSHOT_FORMAT,
            "scoring_fingerprint": scoring_fingerprint(),
            "seasons": seasons}


def _with_players(ratings: dict):
    """(Player, rating) for the rated players that HAVE a provider identity.

    One without it could only be written down by primary key, and a primary key is
    meaningless in the database that will read this file."""
    from realdata.models import Player

    for player in Player.objects.filter(id__in=ratings).only(
            "id", "external_source", "external_id"):
        if player.external_source and player.external_id:
            yield player, ratings[player.id]


class Command(BaseCommand):
    help = "Write vfoot/data/player_ratings_snapshot.json (listone values for slim DBs)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check", action="store_true",
            help="Do not write: exit 1 if the file on disk differs from a fresh build.")

    def handle(self, *args, **opts):
        snapshot = build_snapshot(report=lambda msg: self.stdout.write(
            self.style.WARNING(msg)))
        # Indented and key-sorted so a regeneration produces a reviewable diff
        # rather than one unreadable line.
        text = json.dumps(snapshot, indent=1, sort_keys=True) + "\n"

        if opts["check"]:
            current = SNAPSHOT_PATH.read_text() if SNAPSHOT_PATH.exists() else ""
            if current == text:
                self.stdout.write(self.style.SUCCESS("snapshot aggiornato"))
                return
            self.stderr.write(self.style.ERROR(
                "snapshot NON aggiornato: rilancia "
                "`manage.py build_player_ratings_snapshot`"))
            raise SystemExit(1)

        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(text)
        clear_snapshot_cache()

        self.stdout.write(f"fingerprint: {snapshot['scoring_fingerprint']}")
        for key, season in sorted(snapshot["seasons"].items()):
            self.stdout.write(
                f"  {season['label']} [{key}]: {len(season['ratings'])} giocatori "
                f"(dati {season['data_version']})")
        if not snapshot["seasons"]:
            self.stdout.write(self.style.WARNING(
                "nessuna stagione calcolabile: questo database non ha zone feature, "
                "quindi non puo' PRODURRE lo snapshot (solo consumarlo)."))
        self.stdout.write(self.style.SUCCESS(
            f"scritto {SNAPSHOT_PATH} ({len(text)/1024:.1f} KB)"))
