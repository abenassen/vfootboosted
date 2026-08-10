"""Is the unattended half of the system still working? Deterministic checks.

This is the layer between ``JobRun`` (numbers) and whoever reads them — the daily
email, and later the maintenance agent. It answers in verdicts, not in data.

TWO DESIGN DECISIONS WORTH KNOWING, both about what this must NOT be.

**It is not an LLM's job to notice.** Everything here is arithmetic on rows: a
timer that has not fired, a counter that halved, a match that finished four hours
ago and is still not ready. A model asked "does this look healthy?" will say yes,
warmly, on the day it is not — and will say it differently every morning, so a
human learns nothing from the shape of the message. The model's turn comes after:
why did it break, what is the fix. Detection stays here, where it is boring,
reproducible and free.

**Nothing here alarms about what it cannot see.** A job whose timer was never
enabled is silent for a reason, and a monitor that shouts about the six things the
operator deliberately switched off is a monitor that gets ignored within a week —
taking the seventh, real alarm with it. So the enabled timers are asked for by name
(``systemctl is-enabled``, read-only, works unprivileged), and when systemd is not
there at all — a laptop — the check falls back to "has this job ever run here".

The verdict scale is three-valued and the middle one earns its place: ``alarm``
means something is broken now, ``warn`` means it will be if nobody looks, ``info``
is context that makes the other two readable.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from statistics import median

from django.conf import settings
from django.utils import timezone

from realdata.models import CompetitionSeason, JobRun, Match
from realdata.services import shape_canary

# job -> (systemd unit, expected cadence, how late is too late).
#
# The tolerance is not the cadence: a oneshot that missed one scatto is normal
# (the machine was busy, the egress was slow), a oneshot that missed fifteen is
# not. Each is set so that a single miss is silent and a persistent one is loud —
# which is the distinction the systemd README says nobody currently gets told.
JOBS: dict[str, tuple[str, timedelta, timedelta]] = {
    "tick": ("vfoot-tick.timer", timedelta(minutes=1), timedelta(minutes=15)),
    "sync_calendar": ("vfoot-calendar.timer", timedelta(hours=1),
                      timedelta(hours=3)),
    "poll_transfermarkt": ("vfoot-tm-poll.timer", timedelta(hours=12),
                           timedelta(hours=30)),
}

# Counters whose collapse means the scrape broke rather than the week being quiet.
# Compared against the median of the previous runs, never against a fixed number:
# the right value for "players seen by the Transfermarkt poll" is whatever it was
# last week, and no constant written today survives a season.
# Only counters that are STABLE run to run belong here. Serie A has twenty clubs
# and some five hundred registered players every single poll, so a median is
# meaningful. The calendar sync is deliberately absent: it reads a different number
# of rounds each time (``--auto-rounds``), so its fixture count swings by design and
# a median would cry wolf — it gets its own check, against the rounds it asked for.
WATCHED_COUNTERS = {
    "poll_transfermarkt": ("clubs_scraped", "players"),
}
MIN_FIXTURES_PER_ROUND = 5   # Serie A ships 10; half of that is already a symptom
DROP_RATIO = 0.6          # a counter at <60% of its own median is a collapse
DROP_MIN_HISTORY = 4      # ...but only once there is a median worth the name

EGRESS_POOL = Path("/var/lib/vfoot-egress/sofa_pool.json")
POOL_LOW = 2              # good exit IPs below which SofaScore is about to bite
BLIND_STREAK = 5          # consecutive ticks owed work that imported nothing
SETTLE_AFTER = timedelta(hours=4)   # from kickoff, by when a match should be ready


@dataclass(frozen=True)
class Check:
    level: str      # "alarm" | "warn" | "info"
    code: str
    message: str
    detail: dict = field(default_factory=dict)


@dataclass
class Health:
    at: object = None
    checks: list[Check] = field(default_factory=list)

    def add(self, level: str, code: str, message: str, **detail) -> None:
        self.checks.append(Check(level, code, message, detail))

    @property
    def alarms(self) -> list[Check]:
        return [c for c in self.checks if c.level == "alarm"]

    @property
    def warns(self) -> list[Check]:
        return [c for c in self.checks if c.level == "warn"]

    @property
    def verdict(self) -> str:
        if self.alarms:
            return "alarm"
        return "warn" if self.warns else "ok"

    def as_dict(self) -> dict:
        return {
            "at": self.at.isoformat() if self.at else None,
            "verdict": self.verdict,
            "checks": [{"level": c.level, "code": c.code, "message": c.message,
                        **({"detail": c.detail} if c.detail else {})}
                       for c in self.checks],
        }


# -- systemd ------------------------------------------------------------------

def enabled_units() -> set[str] | None:
    """Which vfoot timers systemd has been told to run. None when there is no
    systemd to ask (a development machine), which is NOT the same as "none are
    enabled" and must not be collapsed into it."""
    if not shutil.which("systemctl"):
        return None
    try:
        # Every timer, filtered here. Passing ``vfoot-*.timer`` to systemctl would
        # be tidier and is a trap: it exits 1 when the glob matches NOTHING, which
        # is indistinguishable from systemd being unreachable — and those two mean
        # opposite things ("nothing is switched on" vs "I cannot tell").
        out = subprocess.run(
            ["systemctl", "list-unit-files", "--type=timer", "--no-legend",
             "--no-pager"],
            capture_output=True, text=True, timeout=20)
    except Exception:  # noqa: BLE001 — no systemd, container, permissions
        return None
    if out.returncode != 0:
        return None
    units = set()
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("vfoot-") and parts[1] == "enabled":
            units.add(parts[0])
    return units


# -- the checks ---------------------------------------------------------------

def _check_jobs(health: Health, now, units: set[str] | None) -> None:
    for job, (unit, cadence, tolerance) in JOBS.items():
        last = JobRun.objects.filter(job=job).order_by("-started_at").first()
        watched = (unit in units) if units is not None else (last is not None)
        if not watched:
            health.add("info", f"{job}:off",
                       f"{job}: timer non attivo, non lo controllo.")
            continue
        if last is None:
            health.add("warn", f"{job}:never",
                       f"{job}: il timer e' acceso ma non ha mai lasciato una "
                       f"riga. Se e' appena stato installato e' normale; entro "
                       f"{_human(tolerance)} deve comparire.")
            continue

        late = now - last.started_at
        if late > tolerance:
            health.add("alarm", f"{job}:silent",
                       f"{job}: ultima esecuzione {_human(late)} fa, ne era "
                       f"prevista una ogni {_human(cadence)}. Il timer non sta "
                       f"scattando o il comando muore prima di scrivere.",
                       last_run=last.started_at.isoformat())
        elif last.ok is None and last.finished_at is None:
            health.add("warn", f"{job}:interrupted",
                       f"{job}: l'ultima esecuzione e' cominciata e non ha mai "
                       f"scritto la fine — uccisa a meta' (riavvio? memoria?).")

        recent = list(JobRun.objects.filter(job=job, started_at__gte=now - timedelta(hours=24))
                      .order_by("-started_at")[:60])
        failed = [r for r in recent if r.ok is False]
        if failed and len(failed) == len(recent):
            health.add("alarm", f"{job}:always-failing",
                       f"{job}: tutte le {len(recent)} esecuzioni delle ultime 24h "
                       f"sono fallite. Ultimo errore: {failed[0].error[:200]}",
                       runs=len(recent))
        elif len(failed) > max(2, len(recent) // 3):
            health.add("warn", f"{job}:flaky",
                       f"{job}: {len(failed)} esecuzioni fallite su {len(recent)} "
                       f"nelle ultime 24h. Ultimo errore: {failed[0].error[:200]}")


def _check_counters(health: Health, now) -> None:
    """A counter that collapses against its own history — the silent break.

    This is the check that catches what an exit code cannot: the provider still
    answers, the job still succeeds, and the number it brings home is a third of
    what it was. Compared to the median of the previous runs and not to the run
    before it, so one bad Sunday does not become the new normal.
    """
    for job, keys in WATCHED_COUNTERS.items():
        runs = list(JobRun.objects.filter(job=job, ok=True, dry_run=False)
                    .exclude(did={}).order_by("-started_at")[:12])
        if len(runs) < DROP_MIN_HISTORY + 1:
            continue
        last, history = runs[0], runs[1:]
        for key in keys:
            past = [r.did.get(key) for r in history if r.did.get(key) is not None]
            if len(past) < DROP_MIN_HISTORY:
                continue
            baseline = median(past)
            value = last.did.get(key, 0)
            if baseline > 0 and value < DROP_RATIO * baseline:
                health.add("alarm", f"{job}:{key}-collapsed",
                           f"{job}: «{key}» e' sceso a {value:g}, contro una "
                           f"mediana di {baseline:g} sulle {len(past)} passate "
                           f"precedenti. Il comando e' andato a buon fine lo "
                           f"stesso: e' il segno di una pagina che risponde ma "
                           f"non contiene piu' quello che leggevamo.",
                           value=value, baseline=baseline)


def _check_blind_tick(health: Health, now) -> None:
    """Ticks that were owed live work and imported nothing — the egress is down.

    One is routine (a blocked exit IP, retried next minute). A run of them means
    the pool is exhausted or the tunnel is down, and every minute of it is a minute
    of a match nobody is seeing."""
    # Bounded to the last hour, not just "the last five owed ticks": five blocked
    # runs spread over three matchdays is a bad IP now and then, five inside an
    # hour is a match going by unread.
    recent = list(JobRun.objects.filter(job="tick", dry_run=False,
                                        started_at__gte=now - timedelta(hours=1))
                  .exclude(due={}).order_by("-started_at")[:BLIND_STREAK])
    if len(recent) < BLIND_STREAK:
        return
    blind = [r for r in recent if not r.did.get("imported")
             and r.did.get("egress_blocked")]
    if len(blind) == BLIND_STREAK:
        health.add("alarm", "tick:blind",
                   f"le ultime {BLIND_STREAK} esecuzioni del tick avevano partite "
                   f"da leggere e non ne hanno importata nessuna: l'egress e' "
                   f"bloccato. Le partite in corso sono ferme.",
                   since=recent[-1].started_at.isoformat())


def _check_calendar_yield(health: Health, now) -> None:
    """The calendar asked for N rounds and brought home how many fixtures?

    Not compared to its own history — ``--auto-rounds`` makes that number swing
    between one round and five by design. Compared to what it ASKED FOR, which is
    written in the same row. A sync that requested five rounds and parsed zero
    fixtures ends its journal line with a cheerful "0 created, 0 updated": exactly
    the shape of a quiet week, and exactly the shape of a broken parser."""
    last = (JobRun.objects.filter(job="sync_calendar", ok=True, dry_run=False)
            .exclude(due={}).order_by("-started_at").first())
    if last is None:
        return
    rounds = last.due.get("rounds") or 0
    fixtures = last.did.get("fixtures", 0)
    if not rounds:
        return
    if fixtures == 0:
        health.add("alarm", "calendar:empty",
                   f"l'ultima lettura del calendario ha chiesto {rounds} turni e "
                   f"non ne ha ricavato nemmeno una partita. La richiesta e' "
                   f"riuscita: e' la pagina ad essere cambiata, o la stagione "
                   f"indicata nell'unita' a non esistere piu'.",
                   rounds=rounds)
    elif fixtures < MIN_FIXTURES_PER_ROUND * rounds:
        health.add("warn", "calendar:thin",
                   f"il calendario ha ricavato {fixtures} partite da {rounds} "
                   f"turni (attese ~{10 * rounds}): la lettura e' parziale.")


def _check_egress_pool(health: Health, now) -> None:
    if not EGRESS_POOL.exists():
        return          # not this machine's job; the silent-timer check covers it
    try:
        data = json.loads(EGRESS_POOL.read_text())
    except (OSError, ValueError):
        health.add("warn", "egress:pool-unreadable",
                   f"il file del pool egress ({EGRESS_POOL}) non si legge.")
        return
    good = [s for s in data.get("servers", []) if s.get("last_ok")]
    if len(good) < POOL_LOW:
        health.add("alarm", "egress:pool-low",
                   f"solo {len(good)} IP di uscita buoni nel pool (soglia "
                   f"{POOL_LOW}): SofaScore sta per tornare a bloccarci. "
                   f"Rimedio: systemctl start vfoot-egress-refill.service",
                   good=len(good))
    else:
        health.add("info", "egress:pool",
                   f"pool egress: {len(good)} IP buoni.")


def _check_stuck_matches(health: Health, now) -> None:
    """Matches the provider says are over and we have never promoted.

    The tick promotes at the +1h confirmation. Something still unpromoted four
    hours after kickoff was skipped, and unlike a failed run it leaves no trace
    anywhere: the league simply keeps showing a provisional vote forever."""
    stuck = list(Match.objects.filter(
        status=Match.STATUS_FINISHED, data_ready=False,
        kickoff__lt=now - SETTLE_AFTER,
        kickoff__gt=now - timedelta(days=14)).order_by("kickoff")[:20])
    if stuck:
        health.add("alarm", "matches:stuck",
                   f"{len(stuck)} partite finite da piu' di {_human(SETTLE_AFTER)} "
                   f"e ancora non definitive: le leghe restano con voti "
                   f"provvisori. La piu' vecchia: {stuck[0]}.",
                   matches=[m.external_id for m in stuck])


def _check_calendar_freshness(health: Health, now) -> None:
    floor = timedelta(minutes=float(
        getattr(settings, "VFOOT_CALENDAR_SYNC_MINUTES", 360)))
    for cs in CompetitionSeason.objects.filter(
            calendar_synced_at__isnull=False).order_by("-id")[:3]:
        age = now - cs.calendar_synced_at
        if age > 2 * floor:
            health.add("warn", "calendar:stale",
                       f"il calendario di {cs} non viene letto da {_human(age)} "
                       f"(il pavimento e' {_human(floor)}): orari e rinvii "
                       f"potrebbero essere vecchi, e il blocco delle formazioni "
                       f"legge quegli orari.")


def _check_shape(health: Health, now) -> None:
    report = shape_canary.run(now=now)
    for finding in report.findings:
        health.add(finding.level, f"shape:{finding.code}", finding.message)


# -- entry point --------------------------------------------------------------

def report(*, now=None, skip_shape: bool = False) -> Health:
    """Run every check and return the verdict."""
    now = now or timezone.now()
    health = Health(at=now)
    units = enabled_units()
    if units is None:
        health.add("info", "systemd:absent",
                   "systemd non interrogabile: controllo solo i job che hanno "
                   "gia' lasciato una riga qui.")

    _check_jobs(health, now, units)
    _check_counters(health, now)
    _check_blind_tick(health, now)
    _check_calendar_yield(health, now)
    _check_egress_pool(health, now)
    _check_stuck_matches(health, now)
    _check_calendar_freshness(health, now)
    if not skip_shape:
        _check_shape(health, now)
    return health


def _human(delta: timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs < 90:
        return f"{secs}s"
    if secs < 5400:
        return f"{secs // 60} min"
    if secs < 172800:
        return f"{secs / 3600:.0f}h"
    return f"{secs // 86400} giorni"
