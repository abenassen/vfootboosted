# Deploy runbook — Linode (vfoot.it)

How to ship a new version to production, and how to turn the automated polling on
at launch. Written from the 23/07/2026 deploy (`03b099b` → current `main`); the
gotchas below are ones that actually bit.

## Server layout

- Host: `ssh -t root@139.162.144.123`
- Repo: `/srv/vfoot-app` — git checkout, branch `main`, remote GitHub, owned by
  user **`vfoot`**. **Run all git/manage commands as `vfoot`, never root** (a
  root-owned object in `.git` breaks the next `vfoot` pull — see gotchas).
- Backend: `vfoot.service` (uvicorn ASGI, `config.asgi:application`, on `:8000`),
  `WorkingDirectory=/srv/vfoot-app/vfoot-backend/src`, venv at
  `/srv/vfoot-app/vfoot-backend/.venv` (Python 3.13).
- DB: **PostgreSQL** `vfoot` (localhost:5432); creds in `/srv/vfoot-app/.env`.
- Frontend: static SPA served by nginx from `/srv/vfoot-web`; nginx (`vfoot.it.conf`)
  proxies `/api`, `/admin`, `/ws` → `:8000`, serves `/static/` from Django's
  `staticfiles/`, and `try_files … /index.html` for client routes.

## Deploy procedure

### 1. Build the frontend locally (server has no node)

```sh
cd vfoot-frontend
VITE_API_PROVIDER=backend \
VITE_API_BASE_URL=/api/v1 \
VITE_GOOGLE_CLIENT_ID=989229675760-6jhl2l8hootj02j3urbm2c68soia67i8.apps.googleusercontent.com \
npm run build          # -> dist/
```
`VITE_API_BASE_URL=/api/v1` is RELATIVE (nginx proxies it); the Google client id is
public (baked into the bundle) and must match, or Google login breaks.

### 2. Backup (always, before migrating)

```sh
ssh root@139.162.144.123 'TS=$(date +%Y%m%d-%H%M%S); mkdir -p /root/backups
  sudo -u postgres pg_dump vfoot > /root/backups/vfoot-db-$TS.sql
  tar czf /root/backups/vfoot-web-$TS.tar.gz -C /srv vfoot-web
  git -C /srv/vfoot-app rev-parse --short HEAD > /root/backups/ROLLBACK_COMMIT-$TS.txt'
```

### 3. Push, then pull on the server (as vfoot)

```sh
git push origin main
ssh root@139.162.144.123 'sudo -u vfoot git -C /srv/vfoot-app pull --ff-only origin main'
```

### 4. Deps, migrate, static (as vfoot)

```sh
ssh root@139.162.144.123 'cd /srv/vfoot-app/vfoot-backend/src
  sudo -u vfoot ../.venv/bin/pip install -r ../requirements.txt   # numpy etc.
  sudo -u vfoot ../.venv/bin/python manage.py migrate --noinput
  sudo -u vfoot ../.venv/bin/python manage.py collectstatic --noinput'
```

### 5. Frontend + restart

```sh
rsync -az --delete vfoot-frontend/dist/ root@139.162.144.123:/srv/vfoot-web/
ssh root@139.162.144.123 'chown -R vfoot:vfoot /srv/vfoot-web; systemctl restart vfoot'
```

### 6. Verify

```sh
curl -s -o /dev/null -w '%{http_code}\n' https://vfoot.it/            # 200
curl -s https://vfoot.it/ | grep -o 'assets/index-[A-Za-z0-9]*\.js'   # new bundle
curl -s -o /dev/null -w '%{http_code}\n' https://vfoot.it/api/v1/auth/me   # 401, NOT 500
ssh root@139.162.144.123 'journalctl -u vfoot --since "2 min ago" | grep -i error'  # empty
```

## Live auction WebSocket (first deploy that ships it)

The auction room is real-time over `wss://vfoot.it/ws/auctions/<id>/`. One-time setup:

1. **Deps** — `pip install -r requirements.txt` now pulls `channels`, `daphne`,
   `channels-redis`, `websockets`. `websockets` is what lets **uvicorn** serve the
   WS handshake; without it the upgrade is refused.
2. **`.env`** — set `REDIS_URL=redis://127.0.0.1:6379/1` (Redis already runs on the
   box). Without it the channel layer falls back to in-memory, which does NOT fan
   out across uvicorn workers, so bids wouldn't reach other watchers. If `vfoot.service`
   runs more than one worker, `REDIS_URL` is mandatory.
3. **nginx** — the `/ws` location must forward the upgrade, not just proxy_pass:

   ```nginx
   location /ws/ {
     proxy_pass http://127.0.0.1:8000;
     proxy_http_version 1.1;
     proxy_set_header Upgrade $http_upgrade;
     proxy_set_header Connection "upgrade";
     proxy_set_header Host $host;
     proxy_read_timeout 3600s;   # auctions are long-lived
   }
   ```
4. **Verify** after restart:
   ```sh
   curl -s -o /dev/null -w '%{http_code}\n' \
     -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
     -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: x==' \
     https://vfoot.it/ws/auctions/1/    # 101/400/403 (a reachable WS), NOT 502
   ```

## Rollback

Restore from the backup made in step 2:
```sh
ssh root@139.162.144.123 'cd /srv/vfoot-app
  sudo -u vfoot git checkout <ROLLBACK_COMMIT>
  sudo -u postgres psql -c "DROP DATABASE vfoot;" -c "CREATE DATABASE vfoot OWNER vfoot;"
  sudo -u postgres psql vfoot < /root/backups/vfoot-db-<TS>.sql
  rm -rf /srv/vfoot-web && tar xzf /root/backups/vfoot-web-<TS>.tar.gz -C /srv
  systemctl restart vfoot'
```
Additive migrations are low-risk; the pg_dump is the real safety net.

## Gotchas (these actually bit)

- **git as `vfoot`, not root.** A `git` command run as root writes root-owned objects
  into `/srv/vfoot-app/.git/objects`, and the next `sudo -u vfoot git pull` fails with
  "insufficient permission". Fix: `chown -R vfoot:vfoot /srv/vfoot-app/.git`.
- **Unpinned deps.** `numpy` is imported at app startup (role inference), so a missing
  dep fails the whole boot, not just a feature. `requirements.txt` now pins it plus the
  scraper deps — always run `pip install -r requirements.txt` in step 4.
- **Frontend env.** Build with the three VITE_ vars above; the default base URL is
  `localhost:8000` (dev), wrong for prod.

## Per-season data (not created by migrations)

Classic roles need the season-level inference run once, BEFORE real leagues open their
listone (reads the FINISHED prior season; see `listone.py` for the freeze model):
```sh
# on the server, as vfoot; prod season ids: 1 = 25/26, 2 = 26/27
manage.py compute_classic_roles --season 2 --data-season 1 --dry-run   # then without --dry-run
```
The per-league `LeaguePlayerRole` freeze then happens automatically when each real
league is created (seeded from `SeasonPlayerRole`), and is additive thereafter.

## Automated polling — ENABLE AT LAUNCH (kept OFF until then)

Everything is staged and **disabled**. Turn it on at launch.

### Data sourcing recap
- **Transfermarkt** (listone): reachable directly from the Linode; `poll_transfermarkt`
  wraps scrape+import. Unit: `vfoot-tm-poll.{service,timer}` (twice daily).
- **SofaScore** (match data): the Linode IP is Cloudflare-blocked, so it egresses
  through a **Surfshark WireGuard tunnel in a netns** (`egress/`), rotating over a
  self-refreshing **pool of good exit IPs**. Dedicated client key at
  `/etc/wireguard/surfshark_wg.conf`. Pool/cache live outside the repo
  (`/var/lib/vfoot-egress/`, `/var/cache/sofascore`). Unit:
  `vfoot-egress-refill.{service,timer}` tops the pool up.

The **DB-aware wiring IS built** (`realdata/services/live_ingest.py` + `egress_client.py`,
wired into `tick` and `sync_calendar --egress`, tested in `tests_live_pipeline`). The
tick decides which matches are due (DB calendar), warms them through the egress via a
narrow sudo bridge, then reads the warm cache with the existing offline import.

### Install the units + the sudo bridge (disabled)
```sh
scp deploy/systemd/*.{service,timer} root@139.162.144.123:/etc/systemd/system/
scp deploy/egress/vfoot-egress root@139.162.144.123:/usr/local/sbin/vfoot-egress
scp deploy/egress/vfoot-egress.sudoers root@139.162.144.123:/tmp/vfoot-egress.sudoers
ssh root@139.162.144.123 '
  chmod 0755 /usr/local/sbin/vfoot-egress
  install -m 0440 /tmp/vfoot-egress.sudoers /etc/sudoers.d/vfoot-egress
  visudo -cf /etc/sudoers.d/vfoot-egress            # validate
  systemctl daemon-reload'                          # do NOT enable yet
```
The `vfoot-calendar.service` runs `sync_calendar --egress --year <YY/YY> --season-id <id>`;
`vfoot-tick.service` runs `tick` (it finds the due matches from the DB itself).

### Enable at launch
```sh
ssh root@139.162.144.123 '
  systemctl enable --now vfoot-tm-poll.timer          # listone stays current (TM)
  systemctl enable --now vfoot-egress-refill.timer    # keeps the IP pool full
  systemctl enable --now vfoot-calendar.timer         # Loop A: calendar via egress
  systemctl enable --now vfoot-tick.timer'            # Loop B: live/finalization
```
`vfoot-tm-poll` and `vfoot-egress-refill` are independent and can be enabled anytime;
`vfoot-calendar`/`vfoot-tick` need the sudo bridge above.
