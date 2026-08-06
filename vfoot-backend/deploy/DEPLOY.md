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

## ⚠ Il sito è CHIUSO al pubblico (manutenzione) — dal 28/07/2026

Finché siamo in testing, `vfoot.it` risponde **503** a tutti con una pagina di
cortesia: SPA, `/api`, `/admin`, `/ws`, `/static` — tutto. L'app gira ancora
(`vfoot.service` attivo), semplicemente non è esposta.

- Interruttore: le tre righe `set $manutenzione` / `if …` in `vfoot.it.conf`.
- Pagina servita: `/srv/vfoot-maintenance/maintenance.html` — **fuori** da
  `/srv/vfoot-web` apposta, perché il passo 5 del deploy fa `rsync --delete`
  e la cancellerebbe. Sorgente versionata in `deploy/maintenance/`.
- Esente dal 503: solo `/.well-known/acme-challenge/`, altrimenti si romperebbe
  il rinnovo del certificato.
- La copia versionata della conf nginx è in `deploy/nginx/vfoot.it.conf`; sul
  server c'è un backup del file pre-manutenzione in `/root/backups/`.

**Per riaprire il sito:**
```sh
ssh root@139.162.144.123
# commentare le tre righe set/if nel blocco MANUTENZIONE di
# /etc/nginx/sites-available/vfoot.it.conf, poi:
nginx -t && systemctl reload nginx
curl -s -o /dev/null -w '%{http_code}\n' https://vfoot.it/   # 200
```

**Per vederlo mentre resta chiuso** (tunnel SSH, bypassa nginx):
```sh
ssh -N -L 8001:127.0.0.1:8000 root@139.162.144.123
# poi apri http://127.0.0.1:8001/admin/ — l'API risponde, la SPA no
# (quella la serve nginx: per la SPA usa `npm run dev` in locale)
```

Finché la manutenzione è attiva, i `curl` del passo **Verify** qui sotto
restituiscono `503` invece di `200`/`401`: è il risultato atteso, non un deploy
rotto. Per verificare davvero un deploy, usa il tunnel qui sopra.

## Certificati TLS — rinnovo automatico (sistemato il 28/07/2026)

Il rinnovo era **rotto in silenzio**: certbot non era nemmeno installato e, cosa più
insidiosa, il DNS di tutti e quattro i nomi (`vfoot.it`, `www.vfoot.it`,
`andreadeluca.online`, `www.andreadeluca.online`) ha un record **AAAA** verso
`2a01:7e01::f03c:92ff:fe5e:d45f`, mentre nginx aveva solo `listen 80` / `listen 443`
— che in nginx significa **solo IPv4**. I validatori di Let's Encrypt preferiscono
IPv6 e prendevano `connection refused`. Effetto collaterale già in atto: il sito
WordPress era irraggiungibile da qualunque client IPv6.

Assetto attuale:

- `certbot` 4.0.0 da apt; `certbot.timer` (2 esecuzioni/giorno) abilitato dal pacchetto.
- Entrambi i domini usano **`authenticator = webroot`**, non il plugin nginx. Motivo:
  il plugin riscrive il file di conf a ogni rinnovo, e `vfoot.it.conf` contiene il
  blocco di manutenzione scritto a mano che non vogliamo far rimaneggiare.
  - `vfoot.it` → `-w /var/www/html` (combacia con la `location ^~ /.well-known/…`)
  - `andreadeluca.online` → `-w /var/www/html/andreadeluca.online/public_html`
- `installer = None`, quindi **serve** l'hook che ricarica nginx dopo il rinnovo,
  altrimenti si continua a servire il certificato vecchio:
  `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh`.
- `listen [::]:80` e `listen [::]:443 ssl` aggiunti a **entrambi** i siti.

Se in futuro qualcosa non torna:
```sh
ssh root@139.162.144.123 'certbot certificates'      # scadenze
ssh root@139.162.144.123 'certbot renew --dry-run'   # test completo, no rate limit
ssh root@139.162.144.123 'systemctl list-timers certbot.timer'
```
Attenzione: **non rimuovere** l'esenzione `/.well-known/acme-challenge/` dal blocco di
manutenzione, o il rinnovo torna a fallire.

Backup pre-modifica sul server: `/root/backups/*.precert.20260728-155008` e
`/root/backups/letsencrypt-renewal.20260728-155008/`.

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

Nothing to run by hand. The Transfermarkt import (`vfoot-tm-poll`, twice a day) does
both halves in order: `refresh_current_roles` re-derives the global `CurrentPlayerRole`
from the finished prior season, then each classic league's `LeaguePlayerRole` freeze is
topped up additively. A league created before the first import of a season seeds its
listone at creation and is caught up by the next poll.

`compute_classic_roles` is NOT part of that pipeline — it is the tuning and inspection
tool for the inference itself, and the only way to see what it found:
```sh
# on the server, as vfoot; prod season ids: 1 = 25/26, 2 = 26/27
manage.py compute_classic_roles --season 2 --data-season 1 --dry-run
```
Use it with `--dry-run` to read the categories, the counts by method, and the
"DA DECIDERE PRIMA DELL'ASTA" list before an auction; its `--min-minutes`,
`--categories` and `--runs` knobs are for experiments. **A tuned run does not stick**:
the automatic path always uses the module constants, so it will overwrite a hand-tuned
table within twelve hours. Promote a finding by changing the constant in
`role_inference.py`, not by running the command with different flags.

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

### The scheduled jobs

**The inventory of everything that runs on a timer lives in
`deploy/systemd/README.md`** — what each job is, its cadence, and what breaks when
it stops running. It is one list in one place on purpose: this section used to
carry a second copy of it, and a second copy is the one that goes stale.

Installing and enabling is `deploy/systemd/install.sh`, run as root on the server:

```sh
ssh root@139.162.144.123 'cd /srv/vfoot-app/vfoot-backend/deploy/systemd
  ./install.sh                # copy units + the backup script, daemon-reload, enable NOTHING
  ./install.sh --status'      # what is on, and when it next fires
```

### The sudo bridge (needed only by `tick` and `calendar`)
```sh
scp deploy/egress/vfoot-egress root@139.162.144.123:/usr/local/sbin/vfoot-egress
scp deploy/egress/vfoot-egress.sudoers root@139.162.144.123:/tmp/vfoot-egress.sudoers
ssh root@139.162.144.123 '
  chmod 0755 /usr/local/sbin/vfoot-egress
  install -m 0440 /tmp/vfoot-egress.sudoers /etc/sudoers.d/vfoot-egress
  visudo -cf /etc/sudoers.d/vfoot-egress'           # validate
```
`vfoot-calendar.service` runs `sync_calendar --egress --year <YY/YY> --season-id <id>`;
`vfoot-tick.service` runs `tick` (it finds the due matches from the DB itself).
Without the bridge both fail on every fire — `install.sh` skips enabling them
until it is in place.

### Enable at launch
```sh
ssh root@139.162.144.123 'cd /srv/vfoot-app/vfoot-backend/deploy/systemd
  ./install.sh --enable-all'
```
`vfoot-backup` deserves to go on **before** launch, not at it: it is the only copy
of the data between one deploy and the next, and it depends on nothing.

## Notifiche push / PWA (primo deploy che le porta)

1. **Deps** — `pip install -r requirements.txt` aggiunge `pywebpush` (con
   `py-vapid` e `http-ece`). Se manca, le push si spengono da sole: `push_channel`
   lo importa in modo pigro e l'app parte comunque.
2. **Migrazione** — `manage.py migrate` crea `vfoot_pushsubscription`.
3. **Chiavi VAPID** — una volta sola, sul server:

   ```sh
   python manage.py vapid_keys        # stampa le due righe da mettere in .env
   ```

   **Non rigenerarle mai dopo**: ogni browser lega la propria subscription alla
   chiave pubblica ricevuta al momento dell'iscrizione, quindi cambiarle zittisce
   tutte le installazioni esistenti (il servizio push risponde 401/403) finché
   ognuno non si re-iscrive. Con le chiavi vuote la funzione è semplicemente
   spenta e gli avvisi viaggiano solo per email — stato normale, non guasto.
4. **`.env`** — `VFOOT_VAPID_PUBLIC_KEY`, `VFOOT_VAPID_PRIVATE_KEY`, e
   `VFOOT_VAPID_SUBJECT=mailto:...` (RFC 8292: serve un mailto o un https).
   Controlla anche `VFOOT_FRONTEND_BASE_URL`, che è il link dentro le email e le
   notifiche: in sviluppo punta all'IP locale.
5. **nginx** — nessuna regola nuova, ma il service worker **deve** essere servito
   dalla radice (`/sw.js`) con `Content-Type: application/javascript` e senza
   cache lunga, altrimenti il suo scope si restringe o un aggiornamento non arriva
   mai. La `location /` con `try_files ... /index.html` già lo copre, purché
   `dist/sw.js` sia stato copiato col resto del build.
6. **Verifica** dopo il restart:

   ```sh
   curl -s https://vfoot.it/api/v1/push/config          # {"enabled":true,...}
   curl -s -o /dev/null -w '%{http_code} %{content_type}\n' https://vfoot.it/sw.js
   curl -s https://vfoot.it/manifest.webmanifest | head -c 120
   python manage.py send_test_push --user <username>    # dopo che si è iscritto
   ```

   HTTPS è un prerequisito assoluto (service worker e push non esistono in
   chiaro), ed è già a posto con Let's Encrypt. `localhost` è l'unica eccezione,
   ed è ciò che rende collaudabile lo sviluppo.
