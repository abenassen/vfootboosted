"""Egress layer: a self-refreshing pool of good Surfshark exit IPs, PER TARGET.

Both sites we read challenge by SINGLE-IP reputation, not by IP class, and
Surfshark's server hostnames each front MANY backend IPs that come and go (they
rotate to dodge blocklists). So there is no static "good server" list: we keep a
LIVE pool of backend endpoint IPs whose exit currently passes, and we refill it
from live sources as IPs rotate and reputations drift.

ONE POOL PER TARGET, and it is not tidiness — the reputations are genuinely
independent. Measured on 26 exits the 14/08/2026, sweeping both sites through the
SAME tunnel back to back:

  * 3 of 8 IPs that SofaScore 403s pass Transfermarkt clean. A shared pool throws
    that capacity away.
  * 2 exits SofaScore accepts cannot even open a connection to Transfermarkt
    (`188.240.58.64/.72`: curl 000 on TM, 200 on another CloudFront site from the
    same tunnel). A shared pool hands the TM scrape an IP it calls good, and the
    scrape hits a wall.

The second direction is the dangerous one, so selection is per target: each has
its own probe, its own pool file and its own country preference.

This module is deliberately standalone (stdlib only; it SHELLS OUT to ip/wg and
runs the in-netns probe as a subprocess). It never imports Django or touches the
DB — it is the privileged network+cache half of the pipeline, meant to run as
root on the server, decoupled from the unprivileged import step.

Sources it re-queries to stay fresh:
  * Surfshark catalog API  -> which clusters exist (and their wg pubKey)
  * cluster DNS            -> which backend IPs exist for a cluster right now
  * the target's own probe -> which of those IPs currently pass THAT site

Usage (as root, on a host with the client key in /etc/wireguard/surfshark_wg.conf):
    python3 sofascore_egress.py refill --target 6
    python3 sofascore_egress.py refill --for transfermarkt --target 3
    python3 sofascore_egress.py status --for transfermarkt
    python3 sofascore_egress.py tm-squads --competition IT1 --season 2026 \
            --cache-dir /tmp/tm --delay 90
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import random
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# --- config -----------------------------------------------------------------
HERE = Path(__file__).resolve().parent
# Pool + cache live OUTSIDE the repo tree (this file is deployed inside it): writing
# state into the checkout would dirty it and fight the next git pull. Overridable.
POOL_FILE = Path(os.environ.get("SOFA_POOL", "/var/lib/vfoot-egress/sofa_pool.json"))
TM_POOL_FILE = Path(os.environ.get("TM_POOL", "/var/lib/vfoot-egress/tm_pool.json"))
CLIENT_CONF = Path(os.environ.get("SOFA_WG_CONF", "/etc/wireguard/surfshark_wg.conf"))
PROBE = Path(os.environ.get("SOFA_PROBE", HERE / "sofa_probe_netns.py"))
TM_PROBE = Path(os.environ.get("TM_PROBE", HERE / "tm_probe_netns.py"))
BROWSER_PROBE = Path(os.environ.get("SOFA_BROWSER_PROBE",
                                    HERE / "sofa_probe_browser_netns.py"))
BROWSER_POOL_FILE = Path(os.environ.get("SOFA_BROWSER_POOL",
                                        "/var/lib/vfoot-egress/sofa_browser_pool.json"))
WORKER = Path(os.environ.get("SOFA_WORKER", HERE / "fetch_worker.py"))
TM_WORKER = Path(os.environ.get("TM_WORKER", HERE / "tm_worker.py"))
CACHE_DIR = Path(os.environ.get("SOFA_CACHE", "/var/cache/sofascore"))
VENV_PY = os.environ.get("SOFA_PY", "/srv/vfoot-app/vfoot-backend/.venv/bin/python")
CATALOG = "https://api.surfshark.com/v4/server/clusters/generic"
WG_PORT = 51820
NS = "sofa"
WG = "wgsofa"

# Country codes whose IP ranges historically pass more often (from the sweep):
# western Europe + a couple US. Candidates are drawn from these first; others are
# a fallback so a shifting reputation map never leaves us with nothing.
PREFERRED_CC = ["it", "gb", "es", "ch", "nl", "fr", "de", "at", "pt", "us"]
# Transfermarkt's good set is WIDER: in the 14/08 sweep Skopje and Asunción exits
# served full squads while SofaScore 403'd them. Preferring western Europe here
# would re-import SofaScore's map onto a site that does not share it — so TM keeps
# a couple of near clusters first (latency, nothing more) and then takes the
# catalogue as it comes.
TM_PREFERRED_CC = ["it", "ch", "at"]
# A pooled IP is considered still-fresh (skip re-probing) within this window.
FRESH_SECONDS = 6 * 3600

# --- the last resort: a real browser ------------------------------------------
# When SofaScore refuses every fingerprint curl_cffi can imitate, no exit IP helps
# and the pool empties for nothing (25/09/2026). The fallback is a real headless
# Chromium (fetch_worker --transport browser), through the same tunnel. It is
# heavy on a 1-vCPU box, so it is a MODE with an expiry, not a per-request retry:
# once curl has failed everywhere and the browser has got through, the next hour
# goes straight to the browser, and only then is curl given another chance —
# which is also when a curl_cffi upgrade starts paying off without anyone
# switching anything back. The state lives next to the pools, where health reads
# it: "we are on the browser" is an alarm, "Chrome is challenged, we are on
# Safari" is the warning that comes before it.
TRANSPORT_FILE = Path(os.environ.get("SOFA_TRANSPORT",
                                     "/var/lib/vfoot-egress/sofa_transport.json"))
BROWSER_MODE_SECONDS = 3600
# The browser has a pool of its OWN (target "sofascore-browser"): the curl pool
# says which exits curl gets through, and in the case the browser exists for it
# has just been demoted to nothing. Without its own pool the fallback could only
# try a couple of exits curl had lately seen and never discover a new one — and a
# third of Surfshark's exits are burned on any given day (4 of 10 on 26/09/2026).
BROWSER_ROTATIONS = 2       # extra exits from the curl pool, after the browser's own
BROWSER_POOL_WANT = 2
BROWSER_REFILL_PROBES = 6   # each boots a Chromium: ~10 s and ~200 MB on the Linode
# Chromium installed once for root, outside any home directory, so the path does
# not depend on who ran `playwright install` (see DEPLOY.md).
PLAYWRIGHT_BROWSERS = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/ms-playwright")

# --- the lock ---------------------------------------------------------------
# One netns named `sofa`, one wg interface named `wgsofa`, and `netns_up()` opens
# by DESTROYING both (see netns_down). So two egress users cannot coexist even
# when they want different IPs and write different files: what they collide over
# is the NAMESPACE, not the data. Without this lock a refill starting at 21:00
# runs `ip netns del sofa` under a tick that is mid-fetch inside it, and that
# tick loses its network stack in the middle of a request.
#
# /run is tmpfs, so the lock cannot survive a reboot as a stale file. Every holder
# comes through the root wrapper, so there is never a permissions mismatch.
LOCK_FILE = Path(os.environ.get("EGRESS_LOCK", "/run/vfoot-egress.lock"))


class EgressBusy(RuntimeError):
    """Another holder has the netns; the caller decides whether to wait or skip."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age_seconds(iso: str) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    except Exception:
        return 1e12


# --- targets ----------------------------------------------------------------
@dataclass(frozen=True)
class Target:
    """What makes one site's egress differ from another's: how you tell a good exit
    from a bad one, and where you write down the answer. Everything else — the
    catalogue, the tunnel, the rotation — is shared."""
    name: str
    probe: Path
    pool_file: Path
    preferred_cc: list[str] = field(default_factory=list)


def target(name: str) -> Target:
    # Built on each call, not once at import, so the SOFA_POOL / TM_POOL env
    # overrides the tests lean on are read when they are set, not before.
    targets = {
        "sofascore": Target("sofascore", PROBE, POOL_FILE, PREFERRED_CC),
        "transfermarkt": Target("transfermarkt", TM_PROBE, TM_POOL_FILE,
                                TM_PREFERRED_CC),
        "sofascore-browser": Target("sofascore-browser", BROWSER_PROBE,
                                    BROWSER_POOL_FILE, PREFERRED_CC),
    }
    try:
        return targets[name]
    except KeyError:
        raise SystemExit(f"unknown target {name!r}; "
                         f"expected one of {', '.join(sorted(targets))}")


SOFASCORE = "sofascore"
TRANSFERMARKT = "transfermarkt"
SOFASCORE_BROWSER = "sofascore-browser"


# --- the lock ---------------------------------------------------------------
@contextlib.contextmanager
def egress_lock(*, wait: float | None, what: str):
    """Hold the exclusive right to the netns for the body of the block.

    ``wait`` is the contract with the caller, and the three values mean three
    different jobs:
      * ``0``    — take it or leave it. The tick asks this way: it runs every
                   minute and a skipped cycle costs nothing, whereas queueing
                   behind a long batch would pile ticks up.
      * ``None`` — block until it is free. Batch work with nowhere else to be.
      * ``N``    — wait up to N seconds, then give up.
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = None if wait is None else time.monotonic() + wait
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if deadline is not None and time.monotonic() >= deadline:
                    raise EgressBusy(
                        f"{what}: egress busy (lock held by another holder)")
                time.sleep(0.25)
        os.ftruncate(fd, 0)
        os.write(fd, f"{what} pid={os.getpid()} since={_now()}\n".encode())
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


@contextlib.contextmanager
def tunnel(endpoint_ip: str, peer_pubkey: str, priv_key: str, addr: str, *,
           wait: float | None, what: str):
    """Lock, raise a tunnel pinned to `endpoint_ip`, tear it down on the way out.

    The lock has to span the whole namespace lifetime, not just its creation —
    releasing it while still working inside `sofa` would let the next holder
    delete the namespace out from under this one. So the two are the same block,
    and every netns user goes through here.

    Yields True on a real handshake, False if none came (caller demotes and
    rotates); either way the namespace is gone by the time the block exits.
    """
    with egress_lock(wait=wait, what=what):
        ok = netns_up(endpoint_ip, peer_pubkey, priv_key, addr)
        try:
            yield ok
        finally:
            netns_down()


# --- client identity --------------------------------------------------------
def _client_identity() -> tuple[str, str]:
    """(private_key, address) from the wg-quick conf; the [Peer] is ignored — we
    supply our own peer per server, which is where the rotation happens."""
    if not CLIENT_CONF.exists():
        sys.exit(f"Missing {CLIENT_CONF} — copy the Surfshark client key there.")
    key = addr = ""
    for line in CLIENT_CONF.read_text().splitlines():
        s = line.strip()
        if s.startswith("PrivateKey") and "=" in s:
            key = s.split("=", 1)[1].strip()
        elif s.startswith("Address") and "=" in s:
            addr = s.split("=", 1)[1].split(",")[0].strip()
    if not key or not addr:
        sys.exit(f"Could not read PrivateKey/Address from {CLIENT_CONF}")
    return key, addr


# --- netns + wireguard (root) ----------------------------------------------
def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def netns_down() -> None:
    _run(["ip", "netns", "del", NS])
    _run(["ip", "link", "del", WG])
    subprocess.run(["rm", "-rf", f"/etc/netns/{NS}"])


def netns_up(endpoint_ip: str, peer_pubkey: str, priv_key: str, addr: str) -> bool:
    """Bring a tunnel up in netns NS pinned to endpoint_ip. Returns True on a real
    handshake. The host default route is untouched (only this ns uses the tunnel)."""
    netns_down()
    keyf = Path("/dev/shm") / f".sofa_{os.getpid()}"
    keyf.write_text(priv_key + "\n")
    try:
        os.makedirs(f"/etc/netns/{NS}", exist_ok=True)
        Path(f"/etc/netns/{NS}/resolv.conf").write_text("nameserver 1.1.1.1\n")
        _run(["ip", "netns", "add", NS])
        _run(["ip", "link", "add", WG, "type", "wireguard"])
        _run(["ip", "link", "set", WG, "netns", NS])
        _run(["ip", "-n", NS, "addr", "add", addr, "dev", WG])
        _run(["ip", "netns", "exec", NS, "wg", "set", WG,
              "private-key", str(keyf),
              "peer", peer_pubkey,
              "endpoint", f"{endpoint_ip}:{WG_PORT}",
              "allowed-ips", "0.0.0.0/0", "persistent-keepalive", "25"])
        _run(["ip", "-n", NS, "link", "set", WG, "up"])
        _run(["ip", "-n", NS, "route", "add", "default", "dev", WG])
        for _ in range(20):
            r = _run(["ip", "netns", "exec", NS, "wg", "show", WG, "latest-handshakes"])
            parts = r.stdout.split()
            if len(parts) >= 2 and parts[1].isdigit() and int(parts[1]) > 0:
                return True
            time.sleep(0.5)
        return False
    finally:
        keyf.unlink(missing_ok=True)


def passed(verdict: str) -> bool:
    """Did the probe pass? Read the FIRST WORD, never the whole string.

    A probe is allowed to qualify its verdict — TM's says
    ``PASS (20 clubs, 25 players)``, because "how full was the page" is exactly
    what you want in the log when a pool starts drifting. Comparing the whole
    string to "PASS" silently rejected six good exits on the first real run and
    reported an empty pool with no error anywhere.
    """
    return verdict.split(" ", 1)[0] == "PASS"


def _child_env() -> dict:
    """What the in-netns children run with: ours, plus where Chromium lives."""
    return {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": PLAYWRIGHT_BROWSERS}


def browser_installed() -> bool:
    """Is there a Chromium for the fallback? Asked before booting one, so a server
    without it does not spend a refill's worth of probes finding out."""
    return any(Path(PLAYWRIGHT_BROWSERS).glob("chromium*"))


def probe_in_netns(tgt: Target) -> tuple[str, str]:
    """Run the target's probe inside the current netns. Returns (exit_ip, verdict)."""
    r = _run(["ip", "netns", "exec", NS, VENV_PY, str(tgt.probe)], env=_child_env())
    out = r.stdout + r.stderr
    exit_ip = verdict = ""
    for line in out.splitlines():
        if line.startswith("EXITIP="):
            exit_ip = line[len("EXITIP="):].strip()
        elif line.startswith("VERDICT="):
            verdict = line[len("VERDICT="):].strip()
    return exit_ip, (verdict or "NO_OUTPUT")


# --- catalog + candidate IPs ------------------------------------------------
def _catalog() -> list[dict]:
    req = urllib.request.Request(CATALOG, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=20))


def _resolve_ips(host: str) -> list[str]:
    """Current backend IPs of a cluster (a few DNS resolutions, deduped)."""
    ips: set[str] = set()
    for _ in range(2):
        try:
            for res in socket.getaddrinfo(host, WG_PORT, socket.AF_INET, socket.SOCK_DGRAM):
                ips.add(res[4][0])
        except socket.gaierror:
            pass
        time.sleep(0.2)
    return sorted(ips)


def candidate_ips(known: set[str], preferred_cc: list[str]) -> list[tuple[str, str, str]]:
    """(endpoint_ip, cluster, pubkey) drawn from preferred clusters first, skipping
    IPs already in the pool. Freshly resolved, so it follows Surfshark's rotation.

    ``known`` is the pool OF ONE TARGET, and that is the whole point: an IP this
    target has never met is a fresh candidate here even if the other target
    demoted it yesterday. Passing the union would re-couple the two reputations
    and throw away the 3-in-8 of SofaScore's rejects that serve TM fine.
    """
    clusters = [d for d in _catalog() if d.get("pubKey") and d.get("connectionName")]
    rank = {cc: i for i, cc in enumerate(preferred_cc)}
    clusters.sort(key=lambda d: (rank.get((d.get("countryCode") or "").lower(), 99),
                                 d.get("load", 99)))
    out: list[tuple[str, str, str]] = []
    for d in clusters:
        for ip in _resolve_ips(d["connectionName"]):
            if ip not in known:
                out.append((ip, d["connectionName"], d["pubKey"]))
    return out


# --- pool store -------------------------------------------------------------
def load_pool(tgt: Target) -> list[dict]:
    if tgt.pool_file.exists():
        try:
            return json.loads(tgt.pool_file.read_text()).get("servers", [])
        except Exception:
            return []
    return []


def save_pool(tgt: Target, servers: list[dict], **meta) -> None:
    """Keys other than the servers (``last_refill``) survive a save that does not
    mention them: the demote after a failed warm must not erase what the last
    refill found out."""
    tgt.pool_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        doc = json.loads(tgt.pool_file.read_text())
    except (OSError, ValueError):
        doc = {}
    doc.update(meta, target=tgt.name, updated=_now(), servers=servers)
    tgt.pool_file.write_text(json.dumps(doc, indent=2))


def good_servers(servers: list[dict]) -> list[dict]:
    """Currently-usable entries, freshest first."""
    ok = [s for s in servers if s.get("last_ok")]
    ok.sort(key=lambda s: s["last_ok"], reverse=True)
    return ok


# --- operations -------------------------------------------------------------
def refill(tgt: Target, want: int, max_probes: int, delay: float) -> None:
    priv, addr = _client_identity()
    servers = load_pool(tgt)
    by_ip = {s["endpoint_ip"]: s for s in servers}
    n_good = len(good_servers(servers))
    print(f"[{tgt.name}] pool: {len(servers)} known, {n_good} good; want {want} good.")
    if n_good >= want:
        print("already at target; nothing to do.")
        return
    cands = candidate_ips(known=set(by_ip), preferred_cc=tgt.preferred_cc)
    print(f"{len(cands)} fresh candidate IP(s) to try.")
    probes = 0
    # Exits that refused EVERY fingerprint, and in how many countries. One is a
    # burned IP; the same verdict from exits in several countries is SofaScore
    # refusing curl_cffi itself — the 25/09/2026 case, where this loop kept
    # probing and demoting for a fault no IP could fix.
    challenged_all = passed_now = 0
    countries: set[str] = set()
    for ip, cluster, pub in cands:
        if len(good_servers(servers)) >= want or probes >= max_probes:
            break
        probes += 1
        # Per probe, not per run: a refill sweeping twenty candidates would
        # otherwise hold the namespace for minutes, and the tick behind it starves.
        with tunnel(ip, pub, priv, addr, wait=None,
                    what=f"refill:{tgt.name}") as up:
            if not up:
                print(f"  {ip:16s} {cluster:26s} NO_HANDSHAKE")
                time.sleep(delay); continue
            exit_ip, verdict = probe_in_netns(tgt)
        print(f"  {ip:16s} {cluster:26s} {verdict:12s} exit={exit_ip}")
        if verdict.startswith("CHALLENGE_ALL"):
            challenged_all += 1
            countries.add(cluster.split("-", 1)[0])
        if passed(verdict):
            passed_now += 1
            rec = by_ip.get(ip) or {"endpoint_ip": ip}
            rec.update({"cluster": cluster, "pubKey": pub, "exit_ip": exit_ip,
                        "last_ok": _now(), "last_checked": _now(), "fail_count": 0})
            if ip not in by_ip:
                servers.append(rec); by_ip[ip] = rec
            save_pool(tgt, servers)
        time.sleep(delay)
    n_good = len(good_servers(servers))
    refused = fingerprint_refused(challenged_all, countries, passed_now)
    # Written down as a verdict, not only as counts, so health reads the same rule
    # instead of keeping its own copy of it.
    save_pool(tgt, servers, last_refill={
        "at": _now(), "probed": probes, "good": n_good,
        "challenged_all": challenged_all, "countries": sorted(countries),
        "fingerprint_refused": refused})
    print(f"done: {n_good} good IP(s) in [{tgt.name}] pool ({probes} probed).")
    if refused:
        print(f"!! {challenged_all} exits in {len(countries)} countries refused "
              f"EVERY fingerprint: this is SofaScore against curl_cffi, not IP "
              f"reputation. Refilling will not help; upgrade curl_cffi.")
        if tgt.name == SOFASCORE:
            # Get the browser its exits NOW, while nobody is waiting on them: the
            # next warm will need them, and a live tick is the worst moment to
            # boot six Chromiums looking for one.
            refill_browser_pool()


def refill_browser_pool() -> None:
    if not browser_installed():
        print(f"no Chromium under {PLAYWRIGHT_BROWSERS}: the browser fallback is "
              f"not installed (see DEPLOY.md).")
        return
    refill(target(SOFASCORE_BROWSER), want=BROWSER_POOL_WANT,
           max_probes=BROWSER_REFILL_PROBES, delay=3.0)


def fingerprint_refused(challenged_all: int, countries, passed_now: int) -> bool:
    """The refill's verdict on WHAT is being refused.

    The refusal alone does not say it: a burned exit gets the same
    ``403 "challenge"`` on every fingerprint too (26/09/2026, four London exits in
    a row, while Milan and Rome passed on Safari). What says it is that NOTHING
    passed in the same run — one exit getting through proves the fingerprint is
    fine — from exits in at least two countries, so one bad neighbourhood cannot
    fake it."""
    return passed_now == 0 and challenged_all >= 3 and len(set(countries)) >= 2


def _demote(tgt: Target, servers: list[dict], ip: str) -> None:
    for s in servers:
        if s["endpoint_ip"] == ip:
            s["fail_count"] = s.get("fail_count", 0) + 1
            s["last_ok"] = None          # drops it out of good_servers()
            s["last_checked"] = _now()
    save_pool(tgt, servers)


# --- transport state -------------------------------------------------------
def load_transport() -> dict:
    try:
        return json.loads(TRANSPORT_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_transport(state: dict) -> None:
    TRANSPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRANSPORT_FILE.write_text(json.dumps(state, indent=2))


def worker_report(stdout: str) -> dict:
    """What the worker said about fingerprints (see fetch_worker's header)."""
    rep = {"challenged_all": False, "used": None, "challenged": []}
    for line in (stdout or "").splitlines():
        if line.startswith("CHALLENGED_ALL"):
            rep["challenged_all"] = True
        elif line.startswith("FINGERPRINT "):
            for tok in line.split()[1:]:
                k, _, v = tok.partition("=")
                if k == "used":
                    rep["used"] = v or None
                elif k == "challenged":
                    rep["challenged"] = [x for x in v.split(",") if x]
    return rep


def _note_curl(state: dict, rep: dict, ok: bool) -> None:
    cur = state.setdefault("curl", {})
    cur["checked_at"] = _now()
    if rep["challenged"] or ok:
        cur["challenged"] = rep["challenged"]
    if ok:
        cur["ok_at"] = _now()
        cur["used"] = rep["used"]
        # curl got through: whatever browser episode was running is over.
        state.pop("browser", None)
    elif rep["challenged_all"]:
        cur["challenged_all_at"] = _now()


def browser_mode(state: dict) -> bool:
    until = (state.get("browser") or {}).get("until")
    return bool(until) and _age_seconds(until) < 0


def _rescue_candidates(browser_pool: list[dict], curl_pool: list[dict],
                       state: dict, tried: set[str]) -> list[dict]:
    """Exits to try the browser through, best evidence first: the ones the
    browser's own pool vouches for (freshest first), then the one it last worked
    on, then a couple the curl pool saw most recently — "recently seen" is the best
    evidence left that an exit is alive at all when curl has been demoting
    everything for a fault no IP caused."""
    last = (state.get("browser") or {}).get("ip")
    recent = sorted(curl_pool, key=lambda s: s.get("last_checked") or "", reverse=True)
    recent.sort(key=lambda s: s["endpoint_ip"] != last)
    out, seen = [], set(tried)
    for srv in [*good_servers(browser_pool), *recent[:BROWSER_ROTATIONS]]:
        if srv["endpoint_ip"] not in seen:
            seen.add(srv["endpoint_ip"])
            out.append(srv)
    return out


class _Warm:
    """One warm, across both transports. What they share is whether a fetch has
    already happened: only the FIRST run may purge (a warm is a warm, not a replay
    of the last one — fetch_worker's header), every later one is the same warm
    continuing on another exit or transport and must keep what it already got."""

    def __init__(self, worker_args: list[str], cache_dir: Path, wait: float | None):
        self.args = worker_args
        self.cache_dir = cache_dir
        self.wait = wait
        self.attempted = False
        self.tgt = target(SOFASCORE)
        self.priv, self.addr = _client_identity()

    def run_worker(self, srv: dict, transport: str) -> subprocess.CompletedProcess | None:
        """None when the tunnel came up without a handshake."""
        ip = srv["endpoint_ip"]
        with tunnel(ip, srv["pubKey"], self.priv, self.addr, wait=self.wait,
                    what=f"warm:sofascore:{transport}") as up:
            if not up:
                return None
            r = _run(["ip", "netns", "exec", NS, VENV_PY, str(WORKER),
                      *self.args, "--cache-dir", str(self.cache_dir),
                      *(["--transport", "browser"] if transport == "browser" else []),
                      *(["--resume"] if self.attempted else [])], env=_child_env())
        self.attempted = True
        sys.stdout.write(r.stdout)
        return r


def _warm(worker_args: list[str], cache_dir: Path, max_rotations: int,
          wait: float | None = 0.0) -> int:
    """Run the fetch worker (with the given args) through a good pooled IP, rotating
    on a block. This side only decides WHICH exit IP to use, never WHAT to fetch —
    the caller (calendar/scheduler) passes the worker args. Self-validating: a clean
    run confirms the IP (last_ok bumped), a block demotes it and rotates.

    When curl cannot get through anywhere, the browser gets a go before giving up
    (see BROWSER_MODE_SECONDS), and while its mode lasts it goes first.

    ``wait`` is how long to queue for the netns; the tick passes 0 because a
    skipped minute is cheaper than a pile of ticks waiting behind a batch job.
    Returns 4 when it gave up on the lock — distinct from 3 (blocked), because
    "someone else is using the tunnel" and "our IPs are burned" want opposite
    reactions from whoever reads the logs.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    w = _Warm(worker_args, cache_dir, wait)
    state = load_transport()
    try:
        if browser_mode(state):
            print("browser mode: curl was challenged everywhere within the hour — "
                  "reading with the browser.")
            if _browser_warm(w, state) == 0:
                return 0
            print("the browser failed too; trying curl anyway.")
        rc = _curl_warm(w, state, max_rotations)
        if rc != 3:
            return rc
        print("curl could not get through; last resort: the browser.")
        return _browser_warm(w, state)
    except EgressBusy as exc:
        print(f"  {exc}; skipping this cycle."); return 4


def _curl_warm(w: _Warm, state: dict, max_rotations: int) -> int:
    tgt = w.tgt
    servers = load_pool(tgt)
    if not good_servers(servers):
        print("pool empty — refilling first.")
        refill(tgt, want=3, max_probes=15, delay=3.0)
        servers = load_pool(tgt)

    tried: set[str] = set()
    for _ in range(max_rotations):
        good = [s for s in good_servers(servers) if s["endpoint_ip"] not in tried]
        if not good:
            print("no untried good IP left — refilling.")
            refill(tgt, want=3, max_probes=15, delay=3.0)
            servers = load_pool(tgt)
            good = [s for s in good_servers(servers) if s["endpoint_ip"] not in tried]
            if not good:
                print("still no good IP — giving up."); return 3
        srv = good[0]
        ip = srv["endpoint_ip"]
        tried.add(ip)
        print(f"using {srv['exit_ip']} via {srv['cluster']} ({ip})")
        r = w.run_worker(srv, "curl")
        if r is None:
            print("  no handshake; demoting + rotating.")
            _demote(tgt, servers, ip); continue
        rep = worker_report(r.stdout)
        if r.returncode == 0:
            srv["last_ok"] = _now(); srv["fail_count"] = 0
            save_pool(tgt, servers)
            _note_curl(state, rep, ok=True); save_transport(state)
            print("  OK — cache warmed.")
            return 0
        if r.returncode == 3:
            _note_curl(state, rep, ok=False); save_transport(state)
            print("  blocked on this IP; demoting + rotating.")
            _demote(tgt, servers, ip); continue
        print(f"  worker error (rc={r.returncode}); not an IP problem:")
        sys.stderr.write(r.stderr); return r.returncode
    print("exhausted rotations."); return 3


def _browser_warm(w: _Warm, state: dict) -> int:
    """The last resort, rotating over the browser's OWN pool and refilling it when
    it runs dry — the same self-validating loop as curl's: a clean run vouches for
    the exit, a refusal demotes it. It never touches the curl pool."""
    if not browser_installed():
        print(f"  no Chromium under {PLAYWRIGHT_BROWSERS}: no browser fallback "
              f"on this server (see DEPLOY.md).")
        return 3
    btgt = target(SOFASCORE_BROWSER)
    tried: set[str] = set()
    for attempt in range(2):
        bpool = load_pool(btgt)
        for srv in _rescue_candidates(bpool, load_pool(w.tgt), state, tried):
            ip = srv["endpoint_ip"]
            tried.add(ip)
            print(f"browser via {srv.get('exit_ip')} ({ip})")
            r = w.run_worker(srv, "browser")
            if r is None:
                print("  no handshake; next exit.")
                _demote(btgt, bpool, ip)
                continue
            if r.returncode == 0:
                _vouch(btgt, bpool, srv)
                _enter_browser_mode(state, ip)
                print("  OK — cache warmed by the browser.")
                return 0
            if r.returncode != 3:
                # No playwright, a crash: the browser is not there, and another
                # exit will not bring it.
                print(f"  browser unavailable (rc={r.returncode}):")
                sys.stderr.write(r.stderr)
                return _browser_failed(state)
            print("  the browser was refused too; demoting + next exit.")
            _demote(btgt, bpool, ip)
        if attempt == 0:
            print("no exit left for the browser — refilling its pool.")
            refill_browser_pool()
    return _browser_failed(state)


def _vouch(tgt: Target, servers: list[dict], srv: dict) -> None:
    rec = next((s for s in servers if s["endpoint_ip"] == srv["endpoint_ip"]), None)
    if rec is None:
        rec = {k: srv.get(k) for k in ("endpoint_ip", "cluster", "pubKey", "exit_ip")}
        servers.append(rec)
    rec.update(last_ok=_now(), last_checked=_now(), fail_count=0)
    save_pool(tgt, servers)


def _enter_browser_mode(state: dict, ip: str) -> None:
    prev = state.get("browser") or {}
    state["browser"] = {
        "since": prev.get("since") or _now(),
        # Set once per episode and never pushed forward by a success, or a
        # browser that keeps working would keep curl out forever.
        "until": prev.get("until") if browser_mode(state) else
        datetime.fromtimestamp(time.time() + BROWSER_MODE_SECONDS,
                               timezone.utc).isoformat(timespec="seconds"),
        "last_ok": _now(), "ip": ip,
    }
    save_transport(state)


def _browser_failed(state: dict) -> int:
    state.setdefault("browser", {})["failed_at"] = _now()
    save_transport(state)
    return 3


def fetch(match_ids: str, kind: str, cache_dir: Path, max_rotations: int,
          wait: float = 0.0) -> int:
    return _warm(["--match-ids", match_ids, "--kind", kind], cache_dir,
                 max_rotations, wait)


def schedule(year: str, cache_dir: Path, max_rotations: int,
             rounds: str | None = None, wait: float = 120.0) -> int:
    # ``rounds`` narrows the warm to those matchdays: one request each instead of
    # all thirty-eight, which is what lets the calendar sync run hourly on a match
    # day. Absent = the whole season, as before.
    args = ["--schedule-year", year]
    if rounds:
        args += ["--rounds", rounds]
    # Hourly, not per-minute: worth a couple of minutes of queueing rather than
    # losing the slot to whoever holds the tunnel right now.
    return _warm(args, cache_dir, max_rotations, wait)


# --- transfermarkt ----------------------------------------------------------
def _tm_page(tgt: Target, priv: str, addr: str, servers: list[dict],
             worker_args: list[str], *, wait: float | None,
             max_rotations: int) -> tuple[int, str]:
    """One tm_worker invocation through a good pooled IP, rotating on a block.

    ONE PAGE PER TUNNEL, and that is the design, not an accident. With the pages
    a minute or two apart a whole squad scrape holds the namespace for half an
    hour, and the tick behind it would starve for the whole live window. So the
    lock is taken per page and released during the wait: in those sixty seconds
    the tick comes and goes without ever noticing. The price is a WireGuard
    handshake per page (~1-2s), which at this cadence is noise.
    """
    tried: set[str] = set()
    for _ in range(max_rotations):
        good = [s for s in good_servers(servers) if s["endpoint_ip"] not in tried]
        if not good:
            refill(tgt, want=2, max_probes=15, delay=3.0)
            servers[:] = load_pool(tgt)
            good = [s for s in good_servers(servers) if s["endpoint_ip"] not in tried]
            if not good:
                return 3, "no good exit IP for transfermarkt"
        srv = good[0]
        ip = srv["endpoint_ip"]
        tried.add(ip)
        with tunnel(ip, srv["pubKey"], priv, addr, wait=wait,
                    what="tm-squads") as up:
            if not up:
                _demote(tgt, servers, ip); continue
            r = _run(["ip", "netns", "exec", NS, VENV_PY, str(TM_WORKER),
                      *worker_args])
        if r.returncode == 0:
            srv["last_ok"] = _now(); srv["fail_count"] = 0
            save_pool(tgt, servers)
            return 0, r.stdout
        if r.returncode == 3:
            print(f"  bloccati su {srv['exit_ip']}; declasso e ruoto.")
            _demote(tgt, servers, ip); continue
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    return 3, "rotazioni esaurite"


def tm_squads(competition: str, season: int, cache_dir: Path, *, delay: float,
              jitter: float, attempts: int, max_rotations: int,
              wait: float | None) -> int:
    """Scrape a competition's squads into `cache_dir`, one page per tunnel.

    Writes exactly what the in-process scraper wrote — ``club_<id>.json`` holding
    ``{"club": ..., "players": [...]}`` — so the Django import on the other side
    of the privilege boundary reads the same files it always did and knows nothing
    about any of this.
    """
    tgt = target(TRANSFERMARKT)
    priv, addr = _client_identity()
    cache_dir.mkdir(parents=True, exist_ok=True)
    servers = load_pool(tgt)
    if not good_servers(servers):
        print("[transfermarkt] pool vuoto — riempio prima.")
        refill(tgt, want=2, max_probes=15, delay=3.0)
        servers = load_pool(tgt)

    common = ["--competition", competition, "--season", str(season),
              "--out", str(cache_dir), "--attempts", str(attempts)]
    rc, out = _tm_page(tgt, priv, addr, servers, [*common, "--mode", "clubs"],
                       wait=wait, max_rotations=max_rotations)
    sys.stdout.write(out if out.endswith("\n") else out + "\n")
    if rc != 0:
        print("nessun club elencato — TM irraggiungibile o bloccato.")
        return rc
    try:
        clubs = json.loads((cache_dir / "clubs.json").read_text())
    except (OSError, ValueError) as exc:
        print(f"clubs.json illeggibile: {exc}"); return 1
    print(f"{len(clubs)} club da leggere, una pagina ogni ~{delay:.0f}s.")

    scraped = failed = 0
    for i, club in enumerate(clubs, 1):
        # The gap is not politeness to Transfermarkt — 21 pages a day never
        # tripped anything there (the 202 was a reputation rule on the datacenter
        # IP, not a rate). It protects the SURFSHARK exit, which we share with
        # strangers and which the pool cannot cheaply replace.
        time.sleep(delay + random.uniform(0, jitter))
        rc, out = _tm_page(tgt, priv, addr, servers,
                           [*common, "--mode", "squad",
                            "--club", json.dumps(club, ensure_ascii=False)],
                           wait=wait, max_rotations=max_rotations)
        line = (out or "").strip().splitlines()
        tail = line[-1] if line else f"rc={rc}"
        if rc == 0:
            scraped += 1
        else:
            failed += 1
        print(f"  [{i}/{len(clubs)}] {club.get('name', '?')}: {tail}")
    print(f"fatto: {scraped} club letti, {failed} falliti.")
    # A partial scrape is NOT a failure here: the import downstream already treats
    # an unread club as a blank in our knowledge rather than an empty squad, and
    # zero clubs is the case that raises. Exiting non-zero on 19/20 would throw
    # away nineteen good rosters over one timeout.
    return 0 if scraped else 3


def status(tgt: Target) -> None:
    servers = load_pool(tgt)
    good = good_servers(servers)
    print(f"[{tgt.name}] pool file: {tgt.pool_file}")
    print(f"{len(servers)} entries, {len(good)} currently good:")
    for s in good:
        age = _age_seconds(s["last_ok"]) / 3600
        print(f"  {s['exit_ip']:16s} via {s['cluster']:24s} ok {age:.1f}h ago  "
              f"fails={s.get('fail_count', 0)}")


def probe_one(tgt: Target, ip: str, pub: str) -> None:
    priv, addr = _client_identity()
    with tunnel(ip, pub, priv, addr, wait=None, what=f"probe:{tgt.name}") as up:
        if not up:
            print("NO_HANDSHAKE"); return
        exit_ip, verdict = probe_in_netns(tgt)
    print(f"exit={exit_ip}  verdict={verdict}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    # `--for` names the SITE; `--target` stayed a number so the deployed unit files
    # and every runbook line keep working unchanged.
    r = sub.add_parser("refill", help="probe fresh candidate IPs, keep the ones that PASS")
    r.add_argument("--for", dest="site", default=SOFASCORE,
                   choices=[SOFASCORE, TRANSFERMARKT, SOFASCORE_BROWSER],
                   help="which site's pool")
    r.add_argument("--target", type=int, default=6, help="stop once this many good IPs are pooled")
    r.add_argument("--max-probes", type=int, default=30, help="cap probes per run (rate-limit safety)")
    r.add_argument("--delay", type=float, default=3.0, help="seconds between probes")
    st = sub.add_parser("status", help="show the current pool")
    st.add_argument("--for", dest="site", default=SOFASCORE,
                    choices=[SOFASCORE, TRANSFERMARKT, SOFASCORE_BROWSER, "all"])
    p = sub.add_parser("probe", help="probe one endpoint IP")
    p.add_argument("--for", dest="site", default=SOFASCORE,
                   choices=[SOFASCORE, TRANSFERMARKT, SOFASCORE_BROWSER])
    p.add_argument("ip"); p.add_argument("pubkey")
    f = sub.add_parser("fetch", help="fetch match ids through a good pooled IP, rotating on block")
    f.add_argument("--match-ids", required=True, help="comma-separated match ids")
    # 'probable' e' il giro delle formazioni previste: UNA richiesta a partita, e
    # chi lo lancia gli passa --max-rotations 1, perche' su un blocco deve
    # rinunciare invece di consumare altri IP buoni del pool.
    f.add_argument("--kind", choices=["live", "final", "probable"], default="final")
    f.add_argument("--cache-dir", default=str(CACHE_DIR))
    f.add_argument("--max-rotations", type=int, default=6)
    f.add_argument("--wait", type=float, default=0.0,
                   help="seconds to queue for the tunnel (0 = skip if busy)")
    sc = sub.add_parser("schedule", help="warm a season's fixture list (for calendar sync)")
    sc.add_argument("--year", required=True, help="season year, e.g. 26/27")
    sc.add_argument("--rounds", help="comma-separated rounds; default = whole season")
    sc.add_argument("--cache-dir", default=str(CACHE_DIR))
    sc.add_argument("--max-rotations", type=int, default=6)
    sc.add_argument("--wait", type=float, default=120.0)
    tm = sub.add_parser("tm-squads", help="scrape Transfermarkt squads into a cache dir")
    tm.add_argument("--competition", default="IT1")
    tm.add_argument("--season", type=int, required=True, help="start year, 2026 = 26/27")
    tm.add_argument("--cache-dir", required=True)
    tm.add_argument("--delay", type=float, default=90.0,
                    help="seconds between pages (protects the shared VPN exit)")
    tm.add_argument("--jitter", type=float, default=20.0)
    tm.add_argument("--attempts", type=int, default=3)
    tm.add_argument("--max-rotations", type=int, default=4)
    tm.add_argument("--wait", type=float, default=300.0)
    args = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit("must run as root (netns + wireguard)")
    if args.cmd == "refill":
        refill(target(args.site), args.target, args.max_probes, args.delay)
    elif args.cmd == "status":
        for name in ([SOFASCORE, TRANSFERMARKT, SOFASCORE_BROWSER]
                     if args.site == "all" else [args.site]):
            status(target(name))
    elif args.cmd == "probe":
        probe_one(target(args.site), args.ip, args.pubkey)
    elif args.cmd == "fetch":
        sys.exit(fetch(args.match_ids, args.kind, Path(args.cache_dir),
                       args.max_rotations, args.wait))
    elif args.cmd == "schedule":
        sys.exit(schedule(args.year, Path(args.cache_dir), args.max_rotations,
                          args.rounds, args.wait))
    elif args.cmd == "tm-squads":
        sys.exit(tm_squads(args.competition, args.season, Path(args.cache_dir),
                           delay=args.delay, jitter=args.jitter,
                           attempts=args.attempts,
                           max_rotations=args.max_rotations, wait=args.wait))


if __name__ == "__main__":
    main()
