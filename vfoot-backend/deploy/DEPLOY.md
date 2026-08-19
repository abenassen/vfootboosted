# Deploy runbook — Linode (vfoot.it)

How to ship a new version to production, and how to turn the automated polling on
at launch. Written from the 23/07/2026 deploy (`03b099b` → current `main`); the
gotchas below are ones that actually bit.

> **Per la riapertura si segue `REBUILD.md`, non questo.** Il deploy di rientro
> butta il database e ricostruisce la 25-26 dalla cache delle risposte: la
> produzione ha le partite giuste ma estratte con l'estrattore vecchio (31 chiavi
> feature su 47, zero `raw_stats`, zero tiri), e un aggiornamento incrementale
> lascerebbe quel difetto sotto un listone che sembra a posto. Questo file resta
> la procedura per ogni deploy successivo.

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

### 5. Restart, POI il frontend — in quest'ordine

```sh
ssh root@139.162.144.123 'systemctl restart vfoot'
rsync -az --delete vfoot-frontend/dist/ root@139.162.144.123:/srv/vfoot-web/
ssh root@139.162.144.123 'chown -R vfoot:vfoot /srv/vfoot-web'
```

**Prima il backend, poi il frontend** (invertito il 19/08/2026). Fra i due passi
c'è una finestra di qualche secondo in cui le due metà non hanno la stessa
versione, e delle due combinazioni possibili una sola è innocua:

- **backend nuovo + frontend vecchio** — va bene, purché il rilascio sia
  additivo: il bundle vecchio ignora i campi che non conosce. Da verificare ogni
  volta, con `git diff <prod>..HEAD | grep '^-' | grep '"[a-z_]*":'` — se non
  esce nessuna chiave rimossa o rinominata, questa direzione è sicura.
- **frontend nuovo + backend vecchio** — no: il bundle nuovo chiama endpoint che
  ancora non esistono. Al rilascio delle rose in asta, `/auctions/<id>/rosters`
  avrebbe risposto 404 e il riquadro sarebbe rimasto su «Caricamento…» — un
  fallimento silenzioso, che è il tipo peggiore.

Se un rilascio TOGLIE o rinomina qualcosa dalle risposte, nessuno dei due ordini
è sicuro: lì ci vuole una finestra di manutenzione, o due rilasci (prima il campo
nuovo accanto al vecchio, poi la rimozione).

Chi ha la PWA installata resta comunque sulla versione vecchia finché non accetta
l'invito di `UpdateBanner`: il service worker nuovo si installa e aspetta, di
proposito (`pwa/registerSW.ts`), per non ricaricare la pagina a qualcuno che sta
rilanciando in asta. Motivo in più perché la direzione «backend nuovo + frontend
vecchio» debba reggere non per secondi, ma per giorni.

### 6. Verify

```sh
curl -s -o /dev/null -w '%{http_code}\n' https://vfoot.it/            # 200
curl -s https://vfoot.it/ | grep -o 'assets/index-[A-Za-z0-9]*\.js'   # new bundle
curl -s -o /dev/null -w '%{http_code}\n' https://vfoot.it/api/v1/auth/me   # 401, NOT 500
ssh root@139.162.144.123 'journalctl -u vfoot --since "2 min ago" | grep -i error'  # empty
```

## Compressione delle risposte (gzip) — INSTALLATA il 19/08/2026

Il file `deploy/nginx/vfoot-gzip.conf` è in `/etc/nginx/conf.d/` e attivo.
Verificato dopo il reload: bundle 830.493 → 289.182 byte, `/benchmark-voto/`
72.874 → 18.215, `base.css` 22.120 → 6.057, e la PWA regge il `Vary`
(34 voci precacheate su 34 rilette, ricarica offline 200). Quel che segue resta
come storia della decisione e come ricetta per rifarlo su una macchina nuova.

**Prima di questo, il sito non comprimeva né il bundle JS né il JSON.** `nginx.conf` ha
`gzip on` ma `gzip_types` commentato — il default Debian — e senza `gzip_types`
nginx comprime **solo `text/html`**. Misurato su https://vfoot.it il 19/08/2026:

```sh
curl -skI -H 'Accept-Encoding: gzip' https://vfoot.it/            # content-encoding: gzip
curl -skI -H 'Accept-Encoding: gzip' https://vfoot.it/assets/index-IiJ2eRLH.js
#   content-type: application/javascript
#   content-length: 830493        ← nessun content-encoding: 830 KB in chiaro
```

Quanto si guadagna, sui payload veri e a livello 1:

| | oggi | gzip lvl 1 | quando pesa |
|---|---|---|---|
| bundle JS | 814 KB | **283 KB** (−65%) | ogni primo accesso e ogni deploy |
| stato asta | 20,4 KB | **3,0 KB** (−85%) | ogni dispositivo, **ogni rilancio** |
| rose a rose piene | 16,4 KB | **2,2 KB** (−86%) | a ogni aggiudicazione |
| pool listone | 61,1 KB | **11,6 KB** (−81%) | il banditore, a ogni evento |

Costo in CPU — la risorsa scarsa qui: **0,10 ms** per comprimere lo stato
dell'asta, contro i ~15 ms che Django impiega a produrlo. Sotto l'1%.

Il file versionato è `deploy/nginx/vfoot-gzip.conf`, e va in `conf.d/` e non nel
vhost perché le direttive `gzip_*` vivono nel contesto http — stessa ragione di
`vfoot-limits.conf`. Le motivazioni di ogni numero sono commentate lì dentro.

```sh
scp vfoot-backend/deploy/nginx/vfoot-gzip.conf root@139.162.144.123:/etc/nginx/conf.d/
ssh root@139.162.144.123 'nginx -t && systemctl reload nginx'
```

**Verifica** (`content-encoding: gzip` su entrambi, e il JS molto più corto):

```sh
curl -skI -H 'Accept-Encoding: gzip' https://vfoot.it/assets/$(curl -s https://vfoot.it/ \
  | grep -o 'assets/index-[A-Za-z0-9_-]*\.js' | head -1 | cut -d/ -f2) \
  | grep -iE 'content-encoding|content-length'
curl -sk -H 'Accept-Encoding: gzip' -o /dev/null -w '%{size_download}\n' https://vfoot.it/
```

**Rollback**: `rm /etc/nginx/conf.d/vfoot-gzip.conf && nginx -t && systemctl reload nginx`.

**Attenzione, verificato con `nginx -t` su un albero di prova il 19/08/2026:** il
file **non deve** contenere `gzip on`. È già dichiarato in `nginx.conf`, e nello
stesso contesto http una seconda volta non è un doppione innocuo — nginx rifiuta
di partire con `[emerg] "gzip" directive is duplicate`.

### `gzip_static` — parte del deploy dal 19/08/2026

`vfoot-gzip.conf` accende `gzip_static on`, che è inerte finché accanto ai file
non compaiono i `.gz`. Questa riga va fra il passo 1 e il passo 5, e comprime il
bundle **una volta a livello 9** invece che a ogni richiesta: il file scende da
289 a 244 KB, cioè 45 KB in meno per ogni download.

Il risparmio di CPU, invece, è trascurabile e non è il motivo per farlo: gli
asset hanno il nome col digest del contenuto e 30 giorni di cache, quindi il
bundle si scarica solo al primo accesso o dopo un rilascio — qualche decina di
volte, non a ogni visita. Il guadagno vero sono i byte per chi ha la linea
lenta.

```sh
find vfoot-frontend/dist -type f \
  \( -name '*.js' -o -name '*.css' -o -name '*.svg' -o -name '*.json' \
     -o -name '*.webmanifest' -o -name '*.html' \) -size +1k \
  -exec gzip -9 -k -f {} +
```

L'`rsync --delete` del passo 5 li porta su e ripulisce i vecchi da solo: i nomi
degli asset sono col digest del contenuto, quindi un `.gz` stantio non può
sopravvivere accanto a un sorgente cambiato.

## Live auction WebSocket (first deploy that ships it)

The auction room is real-time over `wss://vfoot.it/ws/auctions/<id>/`. One-time setup:

1. **Deps** — `pip install -r requirements.txt` now pulls `channels`, `daphne`,
   `channels-redis`, `websockets`. `websockets` is what lets **uvicorn** serve the
   WS handshake; without it the upgrade is refused.
2. **`.env`** — set `REDIS_URL=redis://127.0.0.1:6379/1`. Redis did NOT run on the
   box: this line used to claim it did, and the package was not even installed
   (found and fixed 11/08/2026, `apt install redis-server`, persistenza spenta e
   `maxmemory 64mb` — qui porta solo messaggi transitori). Without it the channel
   layer falls back to in-memory, which does NOT fan out across PROCESSES. Two
   things break, and neither says so: bids don't reach other watchers if
   `vfoot.service` ever runs more than one worker, and — always, even with one —
   the live score push never arrives, because `vfoot-tick` is its own process and
   its nudge dies in its own memory (`vfoot/services/live_realtime.py`).
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

## Il benchmark del voto

Le 40 pagine di `voto_benchmark/` (indice + 38 giornate + divergenze, ~32 MB) sono
servite da nginx su **`https://vfoot.it/benchmark-voto/`**.
Risponde `X-Robots-Tag: noindex, nofollow` e ha `autoindex off`, quindi non si arriva
per caso né dai motori.

**Dall'app ci si arriva da «Voto spiegato»** (`/voto-puro`, paragrafo «Quanto siamo
d'accordo»), e il link NON è scritto a mano: la pagina fa una `HEAD` su
`/benchmark-voto/` e si mostra solo se risponde `ok`. Quindi togliere la cartella dal
server toglie anche il link, senza bisogno di ricordarsene qui — ma se un giorno la si
sposta, il link segue l'indirizzo scritto in `VotoPuroPage.tsx` (`BENCHMARK_URL`) e va
cambiato lì.

Sta in **`/srv/vfoot-benchmark`, fuori da `/srv/vfoot-web`**, per la stessa ragione
della pagina di manutenzione: il passo 5 del deploy fa `rsync --delete` su
`/srv/vfoot-web` e cancellerebbe tutto. (Verificato: dopo un deploy completo la
cartella è ancora al suo posto e risponde 200.)

Per aggiornarlo dopo una ritaratura del modello:
```sh
# in locale (il server ha 1 CPU e ~400 MB liberi: non gli si fa calcolare 380 partite
# mentre serve il sito, e i voti delle due installazioni coincidono — v. vote_fingerprint)
manage.py build_voto_benchmark --season 2
rsync -az --delete voto_benchmark/ root@139.162.144.123:/srv/vfoot-benchmark/
ssh root@139.162.144.123 'chown -R vfoot:vfoot /srv/vfoot-benchmark'
```
Il blocco nginx è in `location ^~ /benchmark-voto/` di `vfoot.it.conf` (copia versionata
in `deploy/nginx/`): `^~` serve a battere il fallback della SPA (`location /`), che
altrimenti risponderebbe `index.html` a ogni file. Backup delle conf precedenti in
`/root/backups/vfoot.it.conf.pre-benchmark-*`.

**E nginx non basta — questo è costato un 404 il 12/08/2026.** Il service worker della
PWA risponde a OGNI navigazione con il guscio dell'app, tranne i percorsi nella sua
`denylist` (`vfoot-frontend/src/sw.ts`): pubblicato senza l'eccezione, il link dava il
**404 dell'app**, non di nginx. E non serve avere la PWA installata per finirci — il
worker si registra alla prima visita normale del sito, quindi riguarda chiunque abbia
aperto vfoot.it una volta. Quindi: **ogni indirizzo statico servito da nginx fuori
dall'app va aggiunto alla denylist del worker**, e i due file devono restare d'accordo.

Attenzione anche alla propagazione: un utente che ha già il worker VECCHIO continua a
vedere il 404 dell'app finché quel worker non viene sostituito — cosa che avviene
aprendo l'app e accettando l'avviso di aggiornamento, oppure chiudendo tutte le schede
di vfoot.it e riaprendo il link. In finestra anonima funziona sempre, perché lì non c'è
nessun worker registrato.

## Deployare il CALCOLO DEI VOTI — la parte che i sei passi sopra non coprono

**Scritto l'11/08/2026 perché quel giorno il deploy era formalmente corretto e i voti
in produzione erano diversi da quelli in locale.** Impronte del modello identiche,
codice identico, e 350 presenze con un ruolo diverso più 218 con un voto diverso su
11.902. Nessuna delle cause era nel codice appena deployato: erano tutte nei DATI e
nell'ambiente della macchina. Il codice si deploya con `git pull`; il calcolo dei voti
no, perché dipende da tabelle che le migrazioni non creano e che nessuno dei passi
sopra nomina.

### Verifica, prima di tutto il resto

`vote_fingerprint` risponde alla sola domanda che conta — le due installazioni
calcolano gli stessi voti? — e va lanciato su ENTRAMBE, con lo stesso nome di
stagione (per nome, non per id: gli id sono diversi su ogni database).

```sh
# in locale
manage.py vote_fingerprint --season-name "Serie A 2025-2026" --out /tmp/fp_locale.txt
# sul server, come vfoot
manage.py vote_fingerprint --season-name "Serie A 2025-2026" --out /tmp/fp_prod.txt
# poi si portano giù i due file e si diffano
diff <(sort fp_locale.txt) <(sort fp_prod.txt) | head -40
```

Come si legge il risultato:

* **impronte del modello diverse** (pesi/`SCORING_CODE_VERSION`/modello) → è il
  codice o la calibrazione: il server non ha ancora fatto `git pull`, o
  `vote_reference.json` è di un'altra versione dei pesi;
* **impronte del modello uguali, impronta dei voti diversa** → sono i dati, e la
  lista sotto dice quali. Il `diff` per presenza dice chi: se cambia il RUOLO è
  l'inferenza, se cambia solo il voto è l'esposizione o una soglia.

### I quattro dati che il calcolo pretende, e che nessuna migrazione porta

1. **Gli intervalli di presenza in campo** (`PlayerOnPitchInterval`). Senza, il
   codice ripiega su una stima («un titolare gioca dal fischio d'inizio, un
   subentrato finisce la partita») che sbaglia di oltre venti punti percentuali il
   pericolo addebitato a un difensore su sette. In produzione erano **zero** per
   tutta la 2025-26. Si ricostruiscono dalla cache, senza rete:
   ```sh
   manage.py import_sofascore_intervals --competition-season <id stagione dati>
   ```
2. **La casella in distinta** (`MatchAppearance.raw_stats['position']`), che dice chi
   era in porta e disambigua chi ha pochi minuti. Gli import nuovi la salvano; per le
   righe vecchie: `manage.py backfill_sofascore_position --season <id>`.
3. **Il tag portiere** (`Player.is_goalkeeper`), che viene dal cartellino
   Transfermarkt e quindi esiste solo per chi sta in una rosa importata. In produzione
   c'è solo la rosa della stagione NUOVA, quindi i portieri della stagione MISURATA
   che non giocano più in serie A non erano marcati — e finivano nel raggruppamento
   per stile come giocatori di movimento. Il calcolo non si fida più del solo tag, ma
   il tag serve al resto dell'app:
   ```sh
   manage.py backfill_goalkeeper_flag --season <id stagione dati>
   ```
4. **I ruoli**, ricalcolati DOPO i tre punti sopra — altrimenti restano quelli
   inferiti sui dati incompleti:
   ```sh
   manage.py compute_classic_roles --season <id rose> --data-season <id dati>
   ```

### E una differenza che NON è un difetto

Le rose Transfermarkt sono una fotografia, e due installazioni che l'hanno scattata
in giorni diversi hanno rose diverse (l'11/08/2026: 660 tesserati in locale, 638 in
produzione). Un giocatore la cui posizione TM c'è da una parte e non dall'altra può
avere un ruolo diverso in modo del tutto legittimo — nella variante `mitigated` una
posizione certa vince sulla misura. Dopo aver sistemato i quattro punti sopra restava
esattamente un caso così su 11.902 presenze (L. Pellegrini, `attacking midfield` in
produzione e niente in locale): quello si spiega, non si ripara.

### L'unico numero che il `git pull` porta davvero: lo snapshot del listone

`vfoot/data/player_ratings_snapshot.json` è l'eccezione alla frase con cui si apre
questo capitolo. Non è codice: sono i valori del listone, calcolati in locale dove
ci sono le zone feature, e spediti col sorgente perché **il database magro** di chi
collabora non può ricalcolarli. Il lettore lo usa solo quando dalle zone non esce
niente (`season_player_ratings`), e in produzione — dove le zone ci sono — non
dovrebbe entrare mai. Su una stagione **non ancora giocata** invece entrava, perché
lì non c'è niente da calcolare.

Il 13/08/2026 quel file, indicizzato sulle chiavi primarie di chi lo scriveva,
raccontava alla 26-27 di produzione la 25-26 di locale, giocatore per giocatore
sbagliato: 554 con presenze e media in un campionato non cominciato. Adesso le
chiavi sono quelle del provider (`sofascore:76457`) e il file viene servito solo se
questa installazione ha giocato le stesse partite su cui è stato costruito, quindi
il caso non si ripresenta da sé. Restano due cose da fare a mano, e sono qui perché
nessuna delle due si vede da fuori:

* **rigenerarlo quando cambia il modello**, in locale e subito dopo
  `calibrate_vote_reference`:
  `manage.py build_player_ratings_snapshot` (poi commit del file). Se resta indietro
  `tests_player_ratings_snapshot` fallisce, e in produzione il log lo dice — ma i
  numeri intanto si vedono;
* **non spedirci mai una stagione simulata.** Il comando salta da solo le stagioni
  con partite "finite" che il calendario mette nel futuro, che è la firma di
  `simulate_sofascore_season`. Se un giorno stampa `SALTATA`, è quello che deve fare.

### Il deploy del calcolo dei voti, in ordine

```sh
# 1-5 come sopra (build, backup, push, pull, migrate, restart), poi:
ssh root@139.162.144.123 'cd /srv/vfoot-app/vfoot-backend/src
  sudo -u vfoot ../.venv/bin/python manage.py backfill_sofascore_position --season 1
  sudo -u vfoot ../.venv/bin/python manage.py import_sofascore_intervals --competition-season 1
  sudo -u vfoot ../.venv/bin/python manage.py backfill_goalkeeper_flag --season 1
  sudo -u vfoot ../.venv/bin/python manage.py compute_classic_roles --season 2 --data-season 1
  systemctl restart vfoot'          # l'impronta del modello e' anche chiave di cache
# poi la verifica: vote_fingerprint su entrambe, e diff
```
Ognuno di questi comandi è idempotente: rilanciarlo non fa danni, e il `backfill` del
tag portiere scrive solo verso il vero. `systemctl restart` serve perché i voti si
mettono in cache sotto l'impronta del modello: cambiando una costante l'impronta
cambia e la cache si invalida da sé, ma il processo vecchio tiene comunque in memoria
le scale già lette.

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
**Both** sources now egress through a **Surfshark WireGuard tunnel in a netns**
(`egress/`), rotating over self-refreshing pools of good exit IPs. Dedicated client
key at `/etc/wireguard/surfshark_wg.conf`; pools and cache live outside the repo
(`/var/lib/vfoot-egress/`, `/var/cache/sofascore`).

- **SofaScore** (match data): the Linode IP is Cloudflare-blocked. Pool:
  `sofa_pool.json`. Units: `vfoot-tick`, `vfoot-calendar`.
- **Transfermarkt** (listone): *used to* be reachable straight from the Linode.
  Since **13/08/2026** it sits behind CloudFront + AWS WAF, which challenges the
  datacenter IP with a `202` and an empty body — a 2xx, so it arrives looking like
  a competition with no teams rather than like a block. Pool: `tm_pool.json`.
  Unit: `vfoot-tm-poll.{service,timer}`.

**One pool per site, and it is not tidiness.** Sweeping 26 exits against both sites
through the same tunnel (14/08/2026): 3 of 8 IPs SofaScore 403s serve TM perfectly,
and 2 IPs SofaScore accepts cannot even open a connection to TM. A shared pool
throws away capacity in one direction and hands the TM scrape a wall in the other.

`vfoot-egress-refill.{service,timer}` tops **both** pools up (two `ExecStart` lines).

**One netns, so one lock.** `NS = "sofa"` is a single OS object and `netns_up()`
opens by destroying it, so any two egress users collide over the *namespace* even
when they want different IPs and write different files. Everything goes through
`egress_lock()` on `/run/vfoot-egress.lock`: the tick asks with `wait=0` (a skipped
minute is cheaper than a queue), batch jobs wait. The TM scrape takes it **per
page**, not per run — at 90s a page a full scrape spans half an hour, and holding
the namespace throughout would starve the tick for the whole window.

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

### Sorveglianza — da accendere INSIEME al resto, non dopo

`vfoot-health` (07:30) guarda ogni mattina se gli altri sette hanno davvero girato e
se quello che riportano ha ancora senso, e manda una mail **solo se qualcosa non
va**. Le prime settimane sono quelle in cui si rompe di più: accenderlo dopo
significa non avere il registro proprio nei giorni in cui serve.

Una riga nel `.env` prima di accenderlo, altrimenti il controllo gira e non ha a chi
dirlo (lo segnala su stderr, quindi nel journal, ma nessuno lo legge):

```sh
VFOOT_HEALTH_EMAIL=abenassen@gmail.com     # più destinatari: separati da virgola
```

Provalo a mano prima, che è gratis:

```sh
sudo -u vfoot /srv/vfoot-app/vfoot-backend/.venv/bin/python \
  /srv/vfoot-app/vfoot-backend/src/manage.py health_report
```

Cosa vede, e perché non è un `systemctl status` in salsa nostra, sta in
`deploy/systemd/README.md` (sezioni «Il registro delle esecuzioni» e «Il canarino
sulla forma del dato»). In breve: prende i due guasti che non hanno codice d'uscita
— il job che ha smesso di scattare, e il job che scatta, riesce, e non riporta più
niente perché la pagina che leggeva è cambiata.

### Agente di manutenzione — si accende DOPO, e in sola lettura

Il backend c'è tutto (`vfoot-agent` + `vfoot-maintenance`, vedi
`deploy/systemd/README.md` e `docs/maintenance_agent_plan.md`), ma il piano è
accenderlo **dopo** il go-live e tenerlo in sola lettura due o tre settimane: non si
può giudicare se le sue diagnosi valgono guardandolo agire.

`install.sh` installa da sé il ponte sudo `/usr/local/sbin/vfoot-maintenance` e ne
valida la regola sudoers **prima** di copiarla (un file rotto in `/etc/sudoers.d`
toglie sudo a tutti). Nel `.env` servono:

```sh
VFOOT_AGENT_CMD=/srv/vfoot-app/vfoot-backend/deploy/agent/vfoot-agent-claude
# VFOOT_MAINTENANCE_AUTO resta assente/false: durante il rodaggio ogni proposta
# aspetta un umano. apply_patch non entra nel livello automatico MAI, comunque.
```

Provalo prima col finto, che non chiama nessun modello e non costa niente:

```sh
sudo -u vfoot ... manage.py maintenance_run --force   # con VFOOT_AGENT_CMD=.../vfoot-agent-fake
sudo -u vfoot ... manage.py maintenance_review        # cosa aspetta un sì
sudo -u vfoot ... manage.py maintenance_tick --dry-run
```

Se `VFOOT_AGENT_CMD` non è impostata, `install.sh --enable agent` salta l'unità
invece di riempire il journal di errori. La sorveglianza deterministica
(`vfoot-health`) non dipende dall'agente: senza di lui il sistema è sorvegliato lo
stesso, solo senza diagnosi automatica.

### Enable at launch
```sh
ssh root@139.162.144.123 'cd /srv/vfoot-app/vfoot-backend/deploy/systemd
  ./install.sh --enable-all'
```
`--enable-all` accende anche `agent` e `maintenance`. Se vuoi il go-live senza
agente, elencali a mano: `--enable tick --enable calendar --enable tm-poll
--enable egress-refill --enable market --enable nudge --enable digest
--enable backup --enable health`.

`--enable digest` non è opzionale come gli altri: senza, aprire una consultazione
di lega non avvisa più nessuno (né mail né push) e non c'è nulla di visibilmente
rotto. Vedi `systemd/README.md`, «Il digest è l'unica strada».
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

## Stemmi caricati dagli utenti (primo deploy che li porta)

1. **Deps** — nessuna nuova: `pillow` era già in `requirements.txt`. Verifica
   però che quella build abbia il WebP, altrimenti gli stemmi escono in PNG
   (funziona, pesa di più):

   ```sh
   ../.venv/bin/python -c "import PIL.features as f; print(f.check('webp'))"
   ```

2. **Migrazione** — `manage.py migrate` crea `vfoot_crestimage` e
   `vfoot_crestreport`. Su PostgreSQL la migrazione fa anche un
   `ALTER COLUMN data SET STORAGE EXTERNAL`: dentro c'è un WebP, già compresso,
   e senza quello TOAST proverebbe a comprimerlo di nuovo a ogni scrittura. Su
   SQLite (sviluppo) quel passo non fa nulla.

3. **nginx** — nessuna regola nuova, ed è il punto: i byte stanno nel database e
   li serve l'app, sotto `/api/v1/crest-images/<hash>`, che ricade nella
   `location ~ ^/(api|admin)/` già esistente. **Non** serve una `location
   /media/` (non c'è, e non deve esserci: `MEDIA_ROOT` resta vuoto).

4. **Backup** — niente da cambiare: le immagini sono righe, quindi vengono già
   dentro il `pg_dump` notturno. Il tar dei media resta quello che era, cioè
   quasi sempre vuoto.

5. **Taglie e limiti** — `DJANGO_CREST_UPLOAD_RATE` (default `30/day` per
   utente) se serve stringere. Il tetto sul file è nel codice
   (`services/crest_images.py`: 2 MB, 16 megapixel), e il `client_max_body_size
   32M` di nginx è comodamente sopra.

6. **Verifica** dopo il restart, con un token qualsiasi:

   ```sh
   curl -s -X POST https://vfoot.it/api/v1/crest-images \
     -H "Authorization: Token $TOK" -F "file=@prova.jpg"     # {"hash":"...","bytes":...}
   curl -sD - -o /dev/null https://vfoot.it/api/v1/crest-images/$HASH \
     | grep -Ei 'HTTP/|content-type|cache-control|x-content-type'
   ```

   Attese: `200`, `image/webp`, `public, max-age=31536000, immutable`, `nosniff`.
   L'endpoint che serve i byte **non** chiede il token, ed è voluto: un `<image>`
   dentro un SVG non può mandare l'intestazione `Authorization`. A proteggerlo è
   l'indirizzo, che è lo sha256 del contenuto.

7. **Moderazione** — le segnalazioni arrivano per mail a `VFOOT_FEEDBACK_EMAIL`
   (la stessa delle segnalazioni generali) e si smistano dall'admin di Django,
   dove `CrestImage` ha le miniature e l'azione «revoca». La prima linea però è
   l'admin di lega, dalla scheda Roster della gestione lega.
