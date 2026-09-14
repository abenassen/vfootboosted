"""Bridge from the DB-aware side (calendar sync + tick) to the root egress.

The egress must run as root (netns + WireGuard tunnel); this app runs as the
unprivileged ``vfoot`` user. So we cross the privilege boundary with ONE narrow
``sudo`` call to a fixed wrapper that runs the egress and warms the shared cache
(``settings.VFOOT_SOFASCORE_CACHE``). This module NEVER touches the network itself
— it asks the egress to warm the cache, and the existing OFFLINE import / calendar
sync then read that cache. The single ``run_egress`` seam is what tests mock, so
the DB-aware wiring is exercised without root or a tunnel.

Returns a plain bool: True = cache warmed (proceed to the offline read), False =
the egress was blocked / unavailable (skip this cycle, try again next tick — the
on-disk cache makes a later retry free).
"""
from __future__ import annotations

import logging
import subprocess
from collections.abc import Iterable

from django.conf import settings

log = logging.getLogger(__name__)

# Quante righe dell'egress tenere quando fallisce. Poche apposta: serve la
# diagnosi, non il verbale. L'egress dice l'IP usato in cima e il motivo in fondo,
# e sono le due righe che contano.
FAILURE_TAIL = 4


def _wrapper() -> str:
    # A fixed path so the sudoers rule can be exact (no wildcards on the binary).
    return getattr(settings, "VFOOT_EGRESS_WRAPPER", "/usr/local/sbin/vfoot-egress")


def run_egress(args: list[str], *, timeout: float = 900.0) -> bool:
    """Run ``sudo -n <wrapper> <args>``. True iff it exits 0 (cache warmed).

    With ``VFOOT_EGRESS_SIMULATED`` on, the request is served by a generator
    instead of by the network (see ``egress_sim``). That switch lives HERE, at the
    one point that crosses to the outside world, so a simulated championship
    exercises the real scheduler, the real live poll and the real import — only the
    bytes are invented. Off by default, and the module is not even imported then.
    """
    if getattr(settings, "VFOOT_EGRESS_SIMULATED", False):
        from realdata.services import egress_sim

        return egress_sim.run(args)
    cmd = ["sudo", "-n", _wrapper(), *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - sudo/wrapper missing, timeout, etc.
        log.warning("egress non eseguibile (%s: %s): %s",
                    type(exc).__name__, exc, " ".join(args))
        return False
    if r.returncode != 0:
        # PERCHE' SI SCRIVE. Fino al 14/09/2026 qui si teneva il codice di uscita e
        # si buttava tutto il resto, quindi il journal di una serata intera diceva
        # solo "egress blocked; will retry" — vero e inutilizzabile. L'errore che
        # aveva inchiodato la pipeline (una stretta di mano TLS tagliata) e' saltato
        # fuori solo rilanciando a mano la stessa fetch novanta minuti dopo. Il
        # processo l'aveva gia' letto e l'aveva gettato via.
        log.warning("egress rc=%s per [%s]\n%s", r.returncode, " ".join(args),
                    _tail(r.stderr, r.stdout))
    return r.returncode == 0


def _tail(stderr: str, stdout: str) -> str:
    """Le ultime righe non vuote di cio' che l'egress ha detto.

    Prima stderr — e' li' che il worker riversa l'errore vero quando
    l'orchestratore decide che non e' un problema di IP — e stdout come ripiego,
    perche' la narrazione dell'orchestratore (quale IP, quante rotazioni) e' su
    stdout e senza stderr e' comunque meglio di niente.
    """
    for stream in (stderr, stdout):
        righe = [l.rstrip() for l in (stream or "").splitlines() if l.strip()]
        if righe:
            return "\n".join(f"    {l}" for l in righe[-FAILURE_TAIL:])
    return "    (nessun output)"


def warm_matches(event_ids: Iterable[int], kind: str) -> bool:
    """Warm the cache for these SofaScore event ids (kind: 'live' | 'final')."""
    ids = ",".join(str(i) for i in event_ids)
    if not ids:
        return True
    return run_egress(["fetch", "--match-ids", ids, "--kind", kind,
                       "--cache-dir", str(settings.VFOOT_SOFASCORE_CACHE)])


def warm_probable(event_ids: Iterable[int]) -> bool:
    """Warm ONLY the squad sheets of these matches — the predicted lineups.

    Separato da ``warm_matches`` perche' e' un lavoro di altra natura e di altra
    priorita': una richiesta a partita invece di quattro (o ventisei), e chi lo
    chiama deve poter rinunciare. V. ``services.probable_lineups``.
    """
    ids = ",".join(str(i) for i in event_ids)
    if not ids:
        return True
    # --max-rotations 1: UN tentativo, e su un blocco si rinuncia. Il valore di
    # serie e' 6, cioe' "consuma fino a sei IP buoni pur di finire": giusto per i
    # voti di domenica, sbagliato qui. Un IP provato-buono speso il giovedi' per
    # una formazione prevista e' un IP che puo' non esserci quando serve.
    return run_egress(["fetch", "--match-ids", ids, "--kind", "probable",
                       "--max-rotations", "1",
                       "--cache-dir", str(settings.VFOOT_SOFASCORE_CACHE)])


def scrape_tm_squads(cache_dir, competition: str, season: int, *,
                     delay: float, attempts: int, timeout: float) -> bool:
    """Scrape Transfermarkt squads into `cache_dir`, through the egress.

    Transfermarkt used to be reachable straight from the server and this call did
    not exist. Since 13/08/2026 it sits behind AWS WAF, which challenges the
    datacenter IP with a 202 and an empty body, so the TM scrape now takes the
    same road SofaScore always has: root, netns, a pooled Surfshark exit — and its
    OWN pool, because an exit SofaScore likes is not one Transfermarkt does.

    The timeout has to cover the whole run and the run is deliberately slow (one
    page per `delay`, twenty-odd pages), so the caller sizes it from those two.
    """
    return run_egress(["tm-squads", "--competition", competition,
                       "--season", str(season), "--cache-dir", str(cache_dir),
                       "--delay", str(delay), "--attempts", str(attempts)],
                      timeout=timeout)


def warm_schedule(year: str, rounds: Iterable[int] | None = None) -> bool:
    """Warm the cache for a season's fixture list (e.g. year='26/27').

    ``rounds`` narrows it to those matchdays — one request each instead of all
    thirty-eight. The narrowing has to reach the FETCHING side to be worth
    anything: limiting only what the offline reader then reads saves database
    work and not a single request.
    """
    args = ["schedule", "--year", year,
            "--cache-dir", str(settings.VFOOT_SOFASCORE_CACHE)]
    if rounds:
        args += ["--rounds", ",".join(str(r) for r in rounds)]
    return run_egress(args)
