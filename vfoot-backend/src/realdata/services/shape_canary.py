"""Does the provider still send the data our model reads? A check on the SHAPE.

THE FAILURE THIS EXISTS FOR. SofaScore renames ``duelWon`` to something else on a
Tuesday. Nothing breaks: the request succeeds, the JSON parses, ``.get("duelWon")``
returns None, the import writes a season of players with a hole where their duels
were, and the voto puro — which is a weighted sum — quietly walks toward 6.0 for
everybody. Exit codes see none of it. Neither does a test suite, which runs against
fixtures that still have the old name. The only witness is the byte stream itself.

So this reads the WARM CACHE — the bytes the egress brought back last — and asks a
question the adapter cannot ask of itself: are the columns I depend on still here?

WHY IT IS TRUSTWORTHY: the thresholds are measured, not guessed. Over the 600 Serie
A matches in ``historical-data/serie-a/sofascore/cache``:

* each of the 31 keys in ``CORE_STAT_KEYS`` appears in **at least 99.5%** of
  matches, and in the union of any TWO consecutive matches **all 31 appear, in 599
  windows out of 599** — zero false alarms across a whole season. That is why the
  check needs a batch of two and not a single match: four single matches out of 600
  are missing some key by pure chance (a game with no save from inside the box),
  and a monitor that cries once a season is a monitor nobody reads;
* the fourteen columns deliberately LEFT OUT are the sparse ones — ``penaltySave``
  shows up in 6% of matches, ``crossNotClaimed`` in 5%. Their absence is football,
  not a broken scraper, and putting them in would make the whole thing noise;
* the overall coverage of the 45 mapped columns ranges 0.73–0.93 per match. The
  blunt ``MIN_COVERAGE`` backstop sits well under that floor: it is not the
  sensitive check (the named keys are), it is the one that still fires if the
  payload changes in a way nobody anticipated.

WHY THE SAMPLE STEPS OVER THE PREDICTED SHEETS. Since the probable-lineups round
exists, the freshest ``_lineups.json`` in the cache is normally a match that has NOT
been played: forty-four names and no ``statistics`` at all, because there is nothing
yet to count. Read by mtime alone that is indistinguishable from the catastrophe
this file watches for, and on 29/08/2026 it duly reported "31 columns gone, coverage
0%" about a provider that was perfectly fine — every morning the 84h window is open,
which is five mornings out of seven.

The discriminator is what the ROUND WROTE, not what the payload says: ``confirmed``
covers both a prediction and an empty answer (v. ``probable_lineups``), while
``fetch_probable`` warms the squad sheet ALONE and every round for a played match
warms the shot map and the incidents beside it. Measured over the 610 lineups files
in the cache: 600 played, every one with both siblings; 10 predicted, with neither;
no ambiguous case.

Note it filters on WAS THIS PLAYED, never on "does this file carry statistics". The
difference is the whole point of the module: a played match whose statistics block
has vanished is exactly the failure worth shouting about, and a filter on emptiness
would throw it away together with the noise.

The other half is ``unknown``: columns the provider sends that we do not map. A
rename shows up here as the NEW name on the same day the old one disappears — which
is the difference between "something broke" and "``duelWon`` is now ``duelsWon``,
fix line 104". The steady-state list is recorded in ``KNOWN_EXTRA`` so that only
genuinely new names are surfaced.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from realdata.services.sofascore_adapter import (
    DISTRIBUTED_STAT_MAP, SIGNED_DISTRIBUTED_STAT_MAP,
)

# Every column the model reads, sparse ones included.
MAPPED_STAT_KEYS: set[str] = {"minutesPlayed", "touches", "totalPass"} | {
    k for m in (DISTRIBUTED_STAT_MAP, SIGNED_DISTRIBUTED_STAT_MAP)
    for v in m.values() for k in (v if isinstance(v, tuple) else (v,))
}

# The canaries: measured at >=99.5% presence per match (see the module docstring).
# Anything added here MUST be re-measured against the historical cache first — a key
# that is merely "obviously always there" is how a monitor starts lying.
CORE_STAT_KEYS: frozenset[str] = frozenset({
    "minutesPlayed", "touches", "totalPass", "accuratePass",
    "accurateCross", "accurateLongBalls", "accurateOppositionHalfPasses",
    "aerialLost", "aerialWon", "ballRecovery", "challengeLost", "dispossessed",
    "duelLost", "duelWon", "expectedAssists", "expectedGoalsOnTarget", "fouls",
    "goalsPrevented", "interceptionWon", "keyPass", "onTargetScoringAttempt",
    "outfielderBlock", "possessionLostCtrl", "saves", "totalClearance",
    "totalContest", "totalTackle", "unsuccessfulTouch", "wasFouled", "wonContest",
    "wonTackle",
})

# Columns SofaScore sends that we knowingly ignore. Present so that a name arriving
# for the first time stands out; not a contract, just a baseline.
KNOWN_EXTRA: frozenset[str] = frozenset({
    "accurateOwnHalfPasses", "ballCarriesCount", "bestBallCarryProgression",
    "blockedScoringAttempt", "defensiveValueNormalized", "dribbleValueNormalized",
    "expectedGoals", "goalAssist", "goalkeeperValueNormalized", "goals",
    "hitWoodwork", "keeperSaveValue", "passValueNormalized", "penaltyFaced",
    # penaltyMiss: comparsa per la prima volta il 14/08/2026, e non e' un rinomino
    # (quel giro non aveva perso nessuna colonna). E' rara perche' lo e' il fatto:
    # esiste solo nelle partite in cui qualcuno sbaglia un rigore, quindi il
    # campione da sei partite la incontra di tanto in tanto e senza questa riga
    # tornerebbe a dirsi "mai vista" ogni volta. Non la mappiamo di proposito: i
    # rigori sbagliati li leggiamo dalla mappa dei tiri (MatchShot situation=
    # 'penalty', is_goal=False — v. classic_pagella), che distingue anche il parato
    # dal fuori bersaglio e vale piu' di un contatore.
    "penaltyMiss",
    "progressiveBallCarriesCount", "rating", "ratingVersions", "shotOffTarget",
    "shotValueNormalized", "statisticsType", "totalBallCarriesDistance",
    "totalCross", "totalKeeperSweeper", "totalLongBalls", "totalOffside",
    "totalOppositionHalfPasses", "totalOwnHalfPasses", "totalProgression",
    "totalProgressiveBallCarriesDistance", "totalShots",
})

# Structural fields, outside the statistics block. Losing one of these is not a
# degraded model, it is an import that resolves nobody.
PLAYER_FIELDS = ("id", "name")
SHOT_FIELDS = ("id", "isHome", "player", "playerCoordinates", "shotType",
               "situation", "time", "xg")
INCIDENT_FIELDS = ("incidentType", "time")

# What a match that has BEEN PLAYED leaves in the cache beside its squad sheet. The
# probable round writes the sheet alone (``egress/fetch_worker.fetch_probable``);
# every round for a match being played or finished writes the shot map and the
# incidents next to it. ``.json`` — the light event — comes last because the bulk
# historical scrape never wrote it: of the 600 played matches in the cache 6 have
# it, all 600 have the other two.
PLAYED_SIBLINGS = ("_shotmap.json", "_incidents.json", ".json")

MIN_BATCH = 2          # matches whose union must hold every core key
MIN_COVERAGE = 0.60    # blunt backstop; observed floor is 0.71 per single match
MIN_RATED_PLAYERS = 30 # per match; observed range 40-52
STALE_AFTER = timedelta(days=7)


@dataclass(frozen=True)
class Finding:
    level: str   # "alarm" | "warn" | "info"
    code: str
    message: str

    def __str__(self) -> str:
        mark = {"alarm": "!!", "warn": " !", "info": "  "}[self.level]
        return f"{mark} [{self.code}] {self.message}"


@dataclass
class CanaryReport:
    checked: int = 0
    findings: list[Finding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def alarms(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "alarm"]

    @property
    def ok(self) -> bool:
        return not self.alarms

    def add(self, level: str, code: str, message: str) -> None:
        self.findings.append(Finding(level, code, message))

    def as_dict(self) -> dict:
        return {
            "checked": self.checked,
            "ok": self.ok,
            "findings": [{"level": f.level, "code": f.code, "message": f.message}
                         for f in self.findings],
            "stats": self.stats,
        }


def _cache_dir(override=None) -> Path:
    return Path(override or settings.VFOOT_SOFASCORE_CACHE)


def _read(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _event_id(path: Path) -> str:
    m = re.search(r"api_v1_event_(\d+)_lineups\.json$", path.name)
    return m.group(1) if m else ""


def _was_played(path: Path) -> bool:
    """Is this squad sheet the sheet of a match that has actually been PLAYED?

    Asked of the CACHE and not of the payload, because the payload cannot answer:
    a predicted sheet and an official one differ by a flag that also covers the
    empty case (v. ``probable_lineups.is_usable_prediction``), and neither says
    whether a ball has been kicked. What the cache knows is which round wrote the
    file, and the two rounds leave different traces — see the module docstring.
    """
    event_id = _event_id(path)
    if not event_id:
        return False
    return any((path.parent / f"api_v1_event_{event_id}{suffix}").exists()
               for suffix in PLAYED_SIBLINGS)


def freshest_lineups(cache_dir: Path, sample: int) -> tuple[list[Path], int]:
    """The freshest warmed sheets OF MATCHES ALREADY PLAYED, newest first — and how
    many predicted ones were stepped over to reach them.

    By modification time and not by match date on purpose: the question is what the
    provider is sending *now*, and the file the egress rewrote twenty minutes ago
    answers it — whichever match it belongs to. But only a played match can answer
    it at all, which is why the predicted sheets are stepped over instead of being
    judged: a formation for Sunday has no statistics because Sunday has not
    happened, and that is not news about the provider.
    """
    files = sorted(cache_dir.glob("api_v1_event_*_lineups.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    played: list[Path] = []
    skipped = 0
    for path in files:
        if not _was_played(path):
            skipped += 1
            continue
        played.append(path)
        if len(played) == sample:
            break
    return played, skipped


def _stat_keys(lineups: dict) -> tuple[set[str], int, int]:
    """(stat keys seen, players carrying statistics, players missing id/name)."""
    seen: set[str] = set()
    rated = broken = 0
    for side in ("home", "away"):
        for entry in (lineups.get(side) or {}).get("players", []) or []:
            player = entry.get("player") or {}
            if any(player.get(f) in (None, "") for f in PLAYER_FIELDS):
                broken += 1
            stats = entry.get("statistics") or {}
            if not stats:
                continue
            rated += 1
            seen |= set(stats)
    return seen, rated, broken


def _check_rows(report: CanaryReport, path: Path, root: str, fields: tuple[str, ...],
                code: str, label: str) -> None:
    """Rows under ``root`` must carry ``fields``. Silent when the file is absent —
    a light live warm does not fetch every endpoint, and demanding one that was
    never asked for would make the canary fire on a cadence, not on a change."""
    data = _read(path)
    if data is None:
        return
    rows = data.get(root) or []
    if not rows:
        return
    missing = sorted({f for f in fields
                      if sum(1 for r in rows if f in r) < 0.9 * len(rows)})
    if missing:
        report.add("alarm", code,
                   f"{label} ({path.name}): campi assenti in gran parte delle "
                   f"righe: {', '.join(missing)}")


def run(*, cache_dir=None, sample: int = 6, now=None) -> CanaryReport:
    """Read the freshest warm cache and judge whether its shape still fits us."""
    now = now or timezone.now()
    cache = _cache_dir(cache_dir)
    report = CanaryReport()

    paths, skipped = freshest_lineups(cache, sample)
    report.stats["skipped_predicted"] = skipped
    if len(paths) < MIN_BATCH:
        report.add("info", "no-data",
                   f"cache con {len(paths)} tabellini giocati: troppo poco per "
                   f"giudicare (ne servono {MIN_BATCH}). "
                   + (f"Le {skipped} distinte previste in cache non contano: sono "
                      f"formazioni di partite non ancora giocate, e non hanno "
                      f"statistiche da controllare."
                      if skipped else "Normale prima della prima giornata."))
        return report

    newest = datetime.fromtimestamp(paths[0].stat().st_mtime, tz=dt_timezone.utc)
    age = now - newest
    report.stats["cache_age_hours"] = round(age.total_seconds() / 3600, 1)
    if age > STALE_AFTER:
        # Said, but not as an alarm: out of season this is simply the truth, and
        # "il calendario non scarica piu'" is a question for health_report, which
        # knows whether a match was due. Here it only means the verdict below
        # describes bytes from a week ago.
        report.add("info", "stale-cache",
                   f"il tabellino piu' recente in cache ha {age.days} giorni: il "
                   f"giudizio qui sotto riguarda dati vecchi, non quelli di oggi.")

    union: set[str] = set()
    rated_per_match: list[int] = []
    broken_total = 0
    for path in paths:
        data = _read(path)
        if data is None:
            report.add("warn", "unreadable",
                       f"{path.name}: illeggibile (scritto a meta'? disco pieno?)")
            continue
        seen, rated, broken = _stat_keys(data)
        union |= seen
        rated_per_match.append(rated)
        broken_total += broken
        report.checked += 1

        event_id = _event_id(path)
        _check_rows(report, cache / f"api_v1_event_{event_id}_shotmap.json",
                    "shotmap", SHOT_FIELDS, "shotmap", "tiri")
        _check_rows(report, cache / f"api_v1_event_{event_id}_incidents.json",
                    "incidents", INCIDENT_FIELDS, "incidents", "eventi partita")

    if report.checked < MIN_BATCH:
        report.add("alarm", "unreadable-batch",
                   f"solo {report.checked} tabellini leggibili su {len(paths)}: "
                   f"la cache dell'egress e' rovinata.")
        return report

    coverage = len(MAPPED_STAT_KEYS & union) / len(MAPPED_STAT_KEYS)
    report.stats["coverage"] = round(coverage, 3)
    report.stats["rated_players_min"] = min(rated_per_match)
    report.stats["core_keys"] = len(CORE_STAT_KEYS)

    lost = sorted(CORE_STAT_KEYS - union)
    if lost:
        one = len(lost) == 1
        report.add("alarm", "stat-keys-lost",
                   f"{len(lost)} colonn{'a' if one else 'e'} che SofaScore manda "
                   f"sempre non c'e' piu' in nessuno degli ultimi "
                   f"{report.checked} tabellini: {', '.join(lost)}. Il voto puro "
                   f"{'la' if one else 'le'} legge: finche' manca"
                   f"{'' if one else 'no'}, ogni partita importata vale meno di "
                   f"quanto sembra.")

    if coverage < MIN_COVERAGE:
        report.add("alarm", "coverage-collapsed",
                   f"copertura delle colonne mappate al {coverage:.0%} (sotto il "
                   f"{MIN_COVERAGE:.0%}): il tabellino non ha piu' la forma su cui "
                   f"e' costruito il modello.")

    if min(rated_per_match) < MIN_RATED_PLAYERS:
        report.add("warn", "few-rated-players",
                   f"una partita del campione ha solo {min(rated_per_match)} "
                   f"giocatori con statistiche (di solito 40-52): o e' appena "
                   f"cominciata, o il tabellino arriva monco.")

    if broken_total:
        report.add("alarm", "player-identity",
                   f"{broken_total} giocatori senza id o nome: l'aggancio "
                   f"all'anagrafica salta e l'import crea doppioni.")

    fresh = sorted(union - MAPPED_STAT_KEYS - KNOWN_EXTRA)
    if fresh:
        # Informational by itself, decisive next to a lost key: same day, one name
        # gone and one arrived, is a rename and not a removal.
        report.stats["new_keys"] = fresh
        report.add("info", "new-stat-keys",
                   f"colonne mai viste prima: {', '.join(fresh)}"
                   + (". Confrontale con quelle sparite qui sopra: potrebbe essere "
                      "un cambio di nome, non una perdita." if lost else ""))

    if report.ok and not lost:
        report.add("info", "shape-ok",
                   f"forma del dato invariata su {report.checked} tabellini "
                   f"(copertura {coverage:.0%}).")
    return report
