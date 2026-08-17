"""Drive a real auction room against a RUNNING server and measure what a roomful
of people actually costs.

    # in one shell (pin to one core to imitate the Linode's single vCPU):
    taskset -c 0 python manage.py runserver 127.0.0.1:8000 --noreload
    # in another:
    python manage.py auction_load_test --clients 20 --rounds 5

Why this exists: the auction socket is a doorbell, not a delivery. It pushes a
bare ``{"type":"update"}`` and every client then re-reads the whole state over
REST (vfoot/consumers.py, useNudgeSocket.ts). So ONE bid does not cost one
request — it costs one request PER CONNECTED DEVICE, all in the same instant and,
when the league is auctioning in the same room, all from the same public IP.
That multiplication is the number every rate limit has to be sized against, and
guessing it is how you end up throttling your own users mid-auction.

What it reports:
  * the amplification actually observed (requests per auction event);
  * the peak request rate in a 1s and a 100ms window — the two numbers that map
    onto nginx's `rate=` and `burst=`;
  * how long the room takes to converge after an event (first byte to last
    client refreshed), which is what a person experiences as "lag";
  * server CPU seconds burnt, with --server-pid, so it extrapolates to a box
    with a different core count.

It does NOT test nginx: it talks straight to the ASGI server, deliberately, to
measure what the application costs before any filter is put in front of it.
See docs/rate_limit_plan.md.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from rest_framework.authtoken.models import Token

from vfoot.models import AuctionSession, FantasyLeague, FantasyTeam, LeagueMembership

DEFAULT_LEAGUE = "Asta Test"


# --------------------------------------------------------------------------- #
# One simulated device: a socket that listens, and a token that re-reads state  #
# --------------------------------------------------------------------------- #

class Device:
    """A browser tab. Owns a token (its manager's) and re-reads the auction state
    on every nudge, exactly as AuctionRoomPage does."""

    def __init__(self, label, token, auction_id, http, samples):
        self.label = label
        self.token = token
        self.auction_id = auction_id
        self.http = http
        self.samples = samples      # shared list of (start, end, status)
        self.nudges = 0
        self.pending = set()

    async def _refetch(self):
        start = time.monotonic()
        try:
            r = await self.http.get(
                f"/api/v1/auctions/{self.auction_id}",
                headers={"Authorization": f"Token {self.token}"})
            status = r.status_code
        except Exception as exc:                                # noqa: BLE001
            status = type(exc).__name__
        self.samples.append((start, time.monotonic(), status))

    async def run(self, url, stop: asyncio.Event, ready: asyncio.Event):
        from websockets.asyncio.client import connect

        async with connect(url, max_queue=None) as ws:
            ready.set()
            while not stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                except Exception:                               # noqa: BLE001
                    break
                try:
                    kind = json.loads(raw).get("type")
                except (ValueError, TypeError):
                    continue
                if kind != "update":
                    continue
                self.nudges += 1
                # Fire and DON'T await: a browser does not block the socket while
                # it refreshes, and serialising here would hide the real burst.
                task = asyncio.create_task(self._refetch())
                self.pending.add(task)
                task.add_done_callback(self.pending.discard)

        if self.pending:
            await asyncio.gather(*list(self.pending), return_exceptions=True)


# --------------------------------------------------------------------------- #
# Measurement                                                                   #
# --------------------------------------------------------------------------- #

def _peak_rate(starts, window: float) -> float:
    """Highest request count in any `window` seconds, expressed per second."""
    if not starts:
        return 0.0
    ordered = sorted(starts)
    best, left = 0, 0
    for right in range(len(ordered)):
        while ordered[right] - ordered[left] > window:
            left += 1
        best = max(best, right - left + 1)
    return best / window


def _stat_fields(pid: int):
    """/proc/<pid>/stat past the comm field, which is the only one that can
    contain spaces. Index 0 is `state`, i.e. the 3rd field overall."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            return fh.read().rsplit(") ", 1)[1].split()
    except (OSError, IndexError):
        return None


def _cpu_seconds(pid: int) -> float | None:
    """utime+stime of a process AND its descendants, in seconds.

    The tree walk is not fussiness: launched behind `taskset` or a shell, the pid
    a person has to hand is usually a wrapper that burns no CPU itself, and a
    plain read of it reports a confident, wrong 0.0.
    """
    import os

    fields = _stat_fields(pid)
    if fields is None:
        return None
    ticks = os.sysconf("SC_CLK_TCK")
    # utime/stime are the 14th/15th fields overall → 11 and 12 here.
    total = int(fields[11]) + int(fields[12])

    children = defaultdict(list)
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        f = _stat_fields(int(entry))
        if f:
            children[int(f[1])].append(int(entry))   # f[1] is ppid
    stack = list(children.get(pid, []))
    while stack:
        child = stack.pop()
        f = _stat_fields(child)
        if f:
            total += int(f[11]) + int(f[12])
            stack.extend(children.get(child, []))
    return total / ticks


class Command(BaseCommand):
    help = "Load-test an auction room: N devices, real bids, measured amplification."

    def add_arguments(self, parser):
        parser.add_argument("--base", default="http://127.0.0.1:8000",
                            help="Origin of the running server (default the dev one).")
        parser.add_argument("--league", default=DEFAULT_LEAGUE,
                            help=f"League name (default '{DEFAULT_LEAGUE}').")
        parser.add_argument("--clients", type=int, default=20,
                            help="Simulated devices. 10 managers with a phone each = 20.")
        parser.add_argument("--rounds", type=int, default=5,
                            help="Players put up for auction.")
        parser.add_argument("--bids-per-round", type=int, default=6,
                            help="Raises before the hammer falls.")
        parser.add_argument("--bid-interval", type=float, default=1.5,
                            help="Seconds between raises. 0 = as fast as it goes.")
        parser.add_argument("--server-pid", type=int, default=None,
                            help="PID of the ASGI server, to report its CPU seconds.")

    # -- sync half: everything that touches the ORM ------------------------- #

    def handle(self, *args, **opts):
        try:
            import httpx  # noqa: F401
            import websockets  # noqa: F401
        except ImportError as exc:
            raise CommandError(f"Missing dependency: {exc}. Both are in requirements.txt.")

        # httpx logs one INFO line per request; at 20 devices that is both unreadable
        # and a measurable cost of its own inside the loop we are timing.
        import logging
        logging.getLogger("httpx").setLevel(logging.WARNING)

        league = FantasyLeague.objects.filter(name=opts["league"]).order_by("-id").first()
        if not league:
            raise CommandError(
                f"No league named '{opts['league']}'. Run: manage.py seed_auction_demo --managers 10")

        memberships = list(LeagueMembership.objects.filter(league=league).select_related("user"))
        admin = next((m for m in memberships if m.role == LeagueMembership.ROLE_ADMIN), None)
        managers = [m for m in memberships if m.role != LeagueMembership.ROLE_ADMIN]
        if not admin or not managers:
            raise CommandError("The league needs an admin and at least one manager.")

        teams = {t.manager_id: t for t in FantasyTeam.objects.filter(league=league)}
        roster = []
        for m in managers:
            team = teams.get(m.id)
            if not team:
                continue
            token, _ = Token.objects.get_or_create(user=m.user)
            roster.append({"username": m.user.username, "token": token.key, "team_id": team.id})
        if not roster:
            raise CommandError("No manager has a team in this league.")
        admin_token, _ = Token.objects.get_or_create(user=admin.user)

        session = (AuctionSession.objects
                   .filter(league=league, status=AuctionSession.STATUS_ACTIVE).first())
        auction_id = session.id if session else None

        self.stdout.write(
            f"Lega '{league.name}' id={league.id} — {len(roster)} manager, "
            f"{opts['clients']} dispositivi simulati")

        result = asyncio.run(self._drive(
            base=opts["base"].rstrip("/"), league_id=league.id, auction_id=auction_id,
            admin_token=admin_token.key, roster=roster, clients=opts["clients"],
            rounds=opts["rounds"], bids=opts["bids_per_round"],
            interval=opts["bid_interval"], server_pid=opts["server_pid"]))
        self._report(result, opts)

    # -- async half: the room ------------------------------------------------ #

    async def _drive(self, *, base, league_id, auction_id, admin_token, roster,
                     clients, rounds, bids, interval, server_pid):
        import httpx

        ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
        admin_h = {"Authorization": f"Token {admin_token}"}
        samples: list = []
        events: list = []            # (label, monotonic time the driver got its answer)

        async with httpx.AsyncClient(base_url=base, timeout=60.0) as http:
            if auction_id is None:
                r = await http.post(f"/api/v1/leagues/{league_id}/auctions",
                                    json={"name": "Prova di carico"}, headers=admin_h)
                if r.status_code not in (200, 201):
                    raise CommandError(f"Cannot open the auction: {r.status_code} {r.text[:200]}")
                auction_id = r.json()["auction_id"]
            self.stdout.write(f"Asta id={auction_id}")

            # --- the room fills up ---------------------------------------- #
            stop = asyncio.Event()
            devices, tasks, readies = [], [], []
            for i in range(clients):
                manager = roster[i % len(roster)]
                dev = Device(f"{manager['username']}#{i // len(roster) + 1}",
                             manager["token"], auction_id, http, samples)
                url = f"{ws_base}/ws/auctions/{auction_id}/?token={manager['token']}"
                ready = asyncio.Event()
                devices.append(dev)
                readies.append(ready)
                tasks.append(asyncio.create_task(dev.run(url, stop, ready)))

            t_connect = time.monotonic()
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(r.wait() for r in readies)), timeout=30)
            except asyncio.TimeoutError:
                stop.set()
                raise CommandError(
                    f"Only {sum(r.is_set() for r in readies)}/{clients} sockets came up in 30s.")
            events.append(("apertura pagina", t_connect))
            await asyncio.sleep(2.0)     # let the connect-storm refetches land

            cpu0 = _cpu_seconds(server_pid) if server_pid else None
            t_start = time.monotonic()

            # --- the auction itself ---------------------------------------- #
            errors: Counter = Counter()
            for rnd in range(rounds):
                # Stamp BEFORE the request, always. The server broadcasts the nudge
                # while still handling it, so a client can start its re-read before
                # the driver has its answer: timing from the response would push
                # those re-reads into the previous event's window and report a lag
                # equal to whatever --bid-interval happened to be.
                t0 = time.monotonic()
                r = await http.post(f"/api/v1/auctions/{auction_id}/nominate",
                                    json={"mode": "random"}, headers=admin_h)
                if r.status_code not in (200, 201):
                    errors[f"nominate {r.status_code}"] += 1
                    break
                body = r.json()
                if "nomination_id" not in body:      # pool exhausted
                    self.stdout.write(self.style.WARNING(f"  round {rnd + 1}: {body.get('detail')}"))
                    break
                nom_id = body["nomination_id"]
                events.append((f"chiamata {body.get('player_name', '?')}", t0))
                await asyncio.sleep(interval)

                for k in range(bids):
                    bidder = roster[k % len(roster)]
                    t0 = time.monotonic()
                    r = await http.post(
                        f"/api/v1/nominations/{nom_id}/bid",
                        json={"amount": k + 1},
                        headers={"Authorization": f"Token {bidder['token']}"})
                    if r.status_code not in (200, 201):
                        errors[f"bid {r.status_code}"] += 1
                    else:
                        events.append((f"rilancio {k + 1}", t0))
                    if interval:
                        await asyncio.sleep(interval)

                t0 = time.monotonic()
                r = await http.post(f"/api/v1/nominations/{nom_id}/close", headers=admin_h)
                if r.status_code not in (200, 201):
                    errors[f"close {r.status_code}"] += 1
                events.append(("aggiudicato", t0))
                await asyncio.sleep(max(interval, 0.5))

            # --- settle -------------------------------------------------- #
            await asyncio.sleep(3.0)
            t_end = time.monotonic()
            cpu1 = _cpu_seconds(server_pid) if server_pid else None
            stop.set()
            await asyncio.gather(*tasks, return_exceptions=True)

        return {
            "samples": samples, "events": events, "devices": devices,
            "t_start": t_start, "t_end": t_end, "t_connect": t_connect,
            "cpu": (cpu1 - cpu0) if (cpu0 is not None and cpu1 is not None) else None,
            "errors": errors, "auction_id": auction_id,
        }

    # -- report -------------------------------------------------------------- #

    def _report(self, res, opts):
        samples = res["samples"]
        if not samples:
            raise CommandError("No request was recorded: no nudge ever arrived.")

        starts = [s for s, _e, _st in samples]
        lat = sorted((e - s) * 1000 for s, e, _st in samples)
        by_status = Counter(st for _s, _e, st in samples)
        ok = by_status.get(200, 0)
        elapsed = res["t_end"] - res["t_start"]
        driver_events = [e for e in res["events"] if e[0] != "apertura pagina"]

        def pct(p):
            return lat[min(len(lat) - 1, int(len(lat) * p))]

        w = self.stdout.write
        # The connect storm (every device reads once on connect) is real load but
        # belongs to opening the page, not to a bid: counting it in would inflate
        # the per-event figure and make it un-interpretable.
        during = [s for s in starts if s >= res["t_start"]]

        w("")
        w(self.style.MIGRATE_HEADING("== Cosa e' costata l'asta =="))
        w(f"  dispositivi collegati        {len(res['devices'])}")
        w(f"  eventi d'asta                {len(driver_events)}")
        w(f"  richieste REST generate      {len(samples)} "
          f"({len(samples) - len(during)} all'apertura, {len(during)} durante l'asta)")
        if driver_events:
            w(self.style.WARNING(
                f"  AMPLIFICAZIONE               {len(during) / len(driver_events):.1f} "
                f"richieste per evento d'asta"))
        w(f"  durata                       {elapsed:.1f}s")
        w("")
        w(self.style.MIGRATE_HEADING("== Il ritmo (e' questo che nginx deve lasciar passare) =="))
        w(f"  picco su 1s                  {_peak_rate(starts, 1.0):.0f} req/s")
        w(f"  picco su 100ms               {_peak_rate(starts, 0.1):.0f} req/s istantanei")
        w(f"  media                        {len(samples) / max(elapsed, 0.001):.1f} req/s")
        w("")
        w(self.style.MIGRATE_HEADING("== Cosa vede la stanza =="))
        w(f"  lettura stato p50            {pct(0.50):.0f} ms")
        w(f"  lettura stato p95            {pct(0.95):.0f} ms")
        w(f"  lettura stato max            {lat[-1]:.0f} ms")

        # Split the delay a person feels into its two halves, because they have
        # different cures: how long the doorbell takes to reach the last device
        # (the socket fan-out), and how long that device's read then takes.
        nudge, conv = [], []
        ordered = sorted(res["events"], key=lambda e: e[1])
        for i, (_label, t) in enumerate(ordered):
            nxt = ordered[i + 1][1] if i + 1 < len(ordered) else res["t_end"]
            caused = [(s, e) for s, e, _st in samples if t <= s < nxt]
            if caused:
                nudge.append(max(s for s, _e in caused) - t)
                conv.append(max(e for _s, e in caused) - t)
        if nudge:
            w(f"  campanello all'ultimo         {statistics.median(nudge) * 1000:.0f} ms "
              f"(peggiore {max(nudge) * 1000:.0f} ms)")
        if conv:
            w(f"  stanza allineata dopo         {statistics.median(conv) * 1000:.0f} ms "
              f"(peggiore {max(conv) * 1000:.0f} ms)")
            w("  (misurati dall'istante in cui parte il rilancio, non da quando il server risponde)")
        w("")
        w(self.style.MIGRATE_HEADING("== Errori =="))
        bad = {k: v for k, v in by_status.items() if k != 200}
        if bad or res["errors"]:
            for k, v in sorted(bad.items(), key=lambda kv: str(kv[0])):
                w(self.style.ERROR(f"  letture stato {k}: {v}"))
            for k, v in res["errors"].items():
                w(self.style.ERROR(f"  azioni {k}: {v}"))
        else:
            w(self.style.SUCCESS(f"  nessuno — {ok} letture, tutte 200"))

        if res["cpu"] is not None:
            w("")
            w(self.style.MIGRATE_HEADING("== CPU del server =="))
            if res["cpu"] < 0.05:
                w(self.style.ERROR(
                    "  praticamente zero: --server-pid non e' il processo che serve. "
                    "Passa il pid di python, non quello della shell che lo ha avviato."))
            w(f"  secondi di CPU               {res['cpu']:.1f}s in {elapsed:.1f}s "
              f"({100 * res['cpu'] / max(elapsed, 0.001):.0f}% di un core)")
            if driver_events:
                w(f"  per lettura di stato         "
                  f"{1000 * res['cpu'] / max(1, ok):.0f} ms")
                w(f"  per evento d'asta            "
                  f"{1000 * res['cpu'] / len(driver_events):.0f} ms")
        else:
            w("")
            w("  (CPU non misurata: passa --server-pid per averla)")
