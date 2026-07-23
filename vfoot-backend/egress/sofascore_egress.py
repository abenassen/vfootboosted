"""SofaScore egress layer: a self-refreshing pool of good Surfshark exit IPs.

SofaScore/Cloudflare challenges by SINGLE-IP reputation, not by IP class, and
Surfshark's server hostnames each front MANY backend IPs that come and go (they
rotate to dodge blocklists). So there is no static "good server" list: we keep a
LIVE pool of backend endpoint IPs whose exit currently passes SofaScore, and we
refill it from live sources as IPs rotate and reputations drift.

This module is deliberately standalone (stdlib only; it SHELLS OUT to ip/wg and
runs the in-netns probe as a subprocess). It never imports Django or touches the
DB — it is the privileged network+cache half of the pipeline, meant to run as
root on the server, decoupled from the unprivileged import step.

Sources it re-queries to stay fresh:
  * Surfshark catalog API  -> which clusters exist (and their wg pubKey)
  * cluster DNS            -> which backend IPs exist for a cluster right now
  * a SofaScore probe      -> which of those IPs currently pass

Usage (as root, on a host with the client key in /etc/wireguard/surfshark_wg.conf):
    python3 sofascore_egress.py refill --target 6
    python3 sofascore_egress.py status
    python3 sofascore_egress.py probe 84.17.58.200 <cluster-pubkey>
"""

from __future__ import annotations

import argparse
import json
import os
import random
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# --- config -----------------------------------------------------------------
HERE = Path(__file__).resolve().parent
POOL_FILE = Path(os.environ.get("SOFA_POOL", HERE / "sofa_pool.json"))
CLIENT_CONF = Path(os.environ.get("SOFA_WG_CONF", "/etc/wireguard/surfshark_wg.conf"))
PROBE = Path(os.environ.get("SOFA_PROBE", HERE / "sofa_probe_netns.py"))
WORKER = Path(os.environ.get("SOFA_WORKER", HERE / "fetch_worker.py"))
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
# A pooled IP is considered still-fresh (skip re-probing) within this window.
FRESH_SECONDS = 6 * 3600


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age_seconds(iso: str) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    except Exception:
        return 1e12


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


def probe_in_netns() -> tuple[str, str]:
    """Run the SofaScore probe inside the current netns. Returns (exit_ip, verdict)."""
    r = _run(["ip", "netns", "exec", NS, VENV_PY, str(PROBE)])
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


def candidate_ips(known: set[str]) -> list[tuple[str, str, str]]:
    """(endpoint_ip, cluster, pubkey) drawn from preferred clusters first, skipping
    IPs already in the pool. Freshly resolved, so it follows Surfshark's rotation."""
    clusters = [d for d in _catalog() if d.get("pubKey") and d.get("connectionName")]
    rank = {cc: i for i, cc in enumerate(PREFERRED_CC)}
    clusters.sort(key=lambda d: (rank.get((d.get("countryCode") or "").lower(), 99),
                                 d.get("load", 99)))
    out: list[tuple[str, str, str]] = []
    for d in clusters:
        for ip in _resolve_ips(d["connectionName"]):
            if ip not in known:
                out.append((ip, d["connectionName"], d["pubKey"]))
    return out


# --- pool store -------------------------------------------------------------
def load_pool() -> list[dict]:
    if POOL_FILE.exists():
        try:
            return json.loads(POOL_FILE.read_text()).get("servers", [])
        except Exception:
            return []
    return []


def save_pool(servers: list[dict]) -> None:
    POOL_FILE.write_text(json.dumps({"updated": _now(), "servers": servers}, indent=2))


def good_servers(servers: list[dict]) -> list[dict]:
    """Currently-usable entries, freshest first."""
    ok = [s for s in servers if s.get("last_ok")]
    ok.sort(key=lambda s: s["last_ok"], reverse=True)
    return ok


# --- operations -------------------------------------------------------------
def refill(target: int, max_probes: int, delay: float) -> None:
    priv, addr = _client_identity()
    servers = load_pool()
    by_ip = {s["endpoint_ip"]: s for s in servers}
    n_good = len(good_servers(servers))
    print(f"pool: {len(servers)} known, {n_good} good; target {target} good.")
    if n_good >= target:
        print("already at target; nothing to do.")
        return
    cands = candidate_ips(known=set(by_ip))
    print(f"{len(cands)} fresh candidate IP(s) to try.")
    probes = 0
    try:
        for ip, cluster, pub in cands:
            if len(good_servers(servers)) >= target or probes >= max_probes:
                break
            probes += 1
            if not netns_up(ip, pub, priv, addr):
                print(f"  {ip:16s} {cluster:26s} NO_HANDSHAKE")
                time.sleep(delay); continue
            exit_ip, verdict = probe_in_netns()
            print(f"  {ip:16s} {cluster:26s} {verdict:12s} exit={exit_ip}")
            if verdict == "PASS":
                rec = by_ip.get(ip) or {"endpoint_ip": ip}
                rec.update({"cluster": cluster, "pubKey": pub, "exit_ip": exit_ip,
                            "last_ok": _now(), "last_checked": _now(), "fail_count": 0})
                if ip not in by_ip:
                    servers.append(rec); by_ip[ip] = rec
                save_pool(servers)
            time.sleep(delay)
    finally:
        netns_down()
    print(f"done: {len(good_servers(servers))} good IP(s) in pool ({probes} probed).")


def _demote(servers: list[dict], ip: str) -> None:
    for s in servers:
        if s["endpoint_ip"] == ip:
            s["fail_count"] = s.get("fail_count", 0) + 1
            s["last_ok"] = None          # drops it out of good_servers()
            s["last_checked"] = _now()
    save_pool(servers)


def fetch(match_ids: str, kind: str, cache_dir: Path, max_rotations: int) -> int:
    """Fetch the given match ids through a good pooled IP, rotating on a block.

    The match ids come from the DB-aware caller (calendar/scheduler) — this side
    only decides WHICH exit IP to use, never WHICH matches. Self-validating: a
    clean run confirms the IP (last_ok bumped), a block demotes it and rotates."""
    priv, addr = _client_identity()
    cache_dir.mkdir(parents=True, exist_ok=True)
    servers = load_pool()
    if not good_servers(servers):
        print("pool empty — refilling first.")
        refill(target=3, max_probes=15, delay=3.0)
        servers = load_pool()

    tried: set[str] = set()
    for _ in range(max_rotations):
        good = [s for s in good_servers(servers) if s["endpoint_ip"] not in tried]
        if not good:
            print("no untried good IP left — refilling.")
            refill(target=3, max_probes=15, delay=3.0)
            servers = load_pool()
            good = [s for s in good_servers(servers) if s["endpoint_ip"] not in tried]
            if not good:
                print("still no good IP — giving up."); return 3
        srv = good[0]
        ip = srv["endpoint_ip"]
        tried.add(ip)
        print(f"using {srv['exit_ip']} via {srv['cluster']} ({ip})")
        try:
            if not netns_up(ip, srv["pubKey"], priv, addr):
                print("  no handshake; demoting + rotating.")
                _demote(servers, ip); continue
            r = _run(["ip", "netns", "exec", NS, VENV_PY, str(WORKER),
                      "--match-ids", match_ids, "--kind", kind,
                      "--cache-dir", str(cache_dir)])
            sys.stdout.write(r.stdout)
            if r.returncode == 0:
                srv["last_ok"] = _now(); srv["fail_count"] = 0
                save_pool(servers)
                print("  OK — cache warmed.")
                return 0
            if r.returncode == 3:
                print("  blocked on this IP; demoting + rotating.")
                _demote(servers, ip); continue
            print(f"  worker error (rc={r.returncode}); not an IP problem:")
            sys.stderr.write(r.stderr); return r.returncode
        finally:
            netns_down()
    print("exhausted rotations."); return 3


def status() -> None:
    servers = load_pool()
    good = good_servers(servers)
    print(f"pool file: {POOL_FILE}")
    print(f"{len(servers)} entries, {len(good)} currently good:")
    for s in good:
        age = _age_seconds(s["last_ok"]) / 3600
        print(f"  {s['exit_ip']:16s} via {s['cluster']:24s} ok {age:.1f}h ago  "
              f"fails={s.get('fail_count', 0)}")


def probe_one(ip: str, pub: str) -> None:
    priv, addr = _client_identity()
    try:
        if not netns_up(ip, pub, priv, addr):
            print("NO_HANDSHAKE"); return
        exit_ip, verdict = probe_in_netns()
        print(f"exit={exit_ip}  verdict={verdict}")
    finally:
        netns_down()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refill", help="probe fresh candidate IPs, keep the ones that PASS")
    r.add_argument("--target", type=int, default=6, help="stop once this many good IPs are pooled")
    r.add_argument("--max-probes", type=int, default=30, help="cap probes per run (rate-limit safety)")
    r.add_argument("--delay", type=float, default=3.0, help="seconds between probes")
    sub.add_parser("status", help="show the current pool")
    p = sub.add_parser("probe", help="probe one endpoint IP")
    p.add_argument("ip"); p.add_argument("pubkey")
    f = sub.add_parser("fetch", help="fetch match ids through a good pooled IP, rotating on block")
    f.add_argument("--match-ids", required=True, help="comma-separated match ids")
    f.add_argument("--kind", choices=["live", "final"], default="final")
    f.add_argument("--cache-dir", default=str(CACHE_DIR))
    f.add_argument("--max-rotations", type=int, default=6)
    args = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit("must run as root (netns + wireguard)")
    if args.cmd == "refill":
        refill(args.target, args.max_probes, args.delay)
    elif args.cmd == "status":
        status()
    elif args.cmd == "probe":
        probe_one(args.ip, args.pubkey)
    elif args.cmd == "fetch":
        sys.exit(fetch(args.match_ids, args.kind, Path(args.cache_dir), args.max_rotations))


if __name__ == "__main__":
    main()
