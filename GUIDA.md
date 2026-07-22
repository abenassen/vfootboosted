# Guida comandi — Vfoot Boosted

Percorsi relativi alla radice del repo `~/Nextcloud/vfootboosted`.
Venv backend: `vfoot-backend/.venv`. Stagione reale corrente: **Serie A 26/27** =
`CompetitionSeason id 3` (SofaScore season 95836).

---

## 1) Test backend / frontend

### Avviare l'app (2 terminali)
```bash
# Terminale 1 — backend su :8000
cd vfoot-backend/src
../.venv/bin/python manage.py runserver localhost:8000 --noreload

# Terminale 2 — frontend su :5173, provider = backend reale
cd vfoot-frontend
VITE_API_PROVIDER=backend npm run dev -- --host localhost --port 5173
# poi apri http://localhost:5173 e fai login
```

### Verifiche
```bash
# Backend: check + suite test
cd vfoot-backend/src
../.venv/bin/python manage.py check
../.venv/bin/python manage.py test vfoot realdata players

# Frontend: type-check + build
cd vfoot-frontend
npm run build
```

---

## 2) Scraping calendario (SofaScore)

Transport browser (passa Cloudflare). È un passo di rete.

```bash
# Sync calendario 26/27: crea/aggiorna i Match (idempotente, mostra il diff)
cd vfoot-backend/src
../.venv/bin/python manage.py sync_calendar --year 26/27 --browser
# opzioni: --rounds 1,2 (solo alcune giornate) ; --headful --channel chrome (se headless bloccato)

# Probe: quanto è avanti il calendario (orari confermati vs placeholder)
cd vfoot-backend/src/realdata/services
../../../.venv/bin/python probe_next_season.py --rounds 8
# oppure: python probe_next_season.py --rounds 38   (stagione intera)
```

---

## 3) Scraping rose (Transfermarkt)

Passo 1 = scrape (rete, la lanci tu). Passo 2 = import (offline).
`--season 2026` = stagione 26/27. Competizione Serie A = `IT1`.

```bash
# Passo 1 — scrape squadre (scrive historical-data/serie-a/transfermarkt/IT1/2026/club_*.json)
cd vfoot-backend/src/realdata/services
../../../.venv/bin/python scrape_transfermarkt_squads.py \
  --competition IT1 --season 2026 \
  --cache-dir /home/andrea/Nextcloud/vfootboosted/historical-data/serie-a/transfermarkt

# Passo 2 — import nel DB verso la stagione 26/27 (cs id 3); apre gli stint (pool) + ruoli
cd vfoot-backend/src
../.venv/bin/python manage.py import_transfermarkt_squads \
  --cache-dir /home/andrea/Nextcloud/vfootboosted/historical-data/serie-a/transfermarkt/IT1/2026 \
  --competition-season 3 --dry-run      # prima a vuoto per vedere il mapping
# poi senza --dry-run per scrivere davvero
```

---

## 4) Seed lega di test

```bash
cd vfoot-backend/src
# Lega pre-stagione sul campionato in corso (26/27 = cs 3): rose draftate dal pool,
# listone congelato, calendario non giocato. Idempotente (ricrea la lega omonima).
../.venv/bin/python manage.py seed_preseason_league --competition-season 3 --owner andrea

# Lega demo su stagione CONCLUSA (25-26), con punteggi e partite giocate
../.venv/bin/python manage.py seed_classic_demo_league --owner andrea
```

---

## Note
- `sync_calendar` e l'import TM sono **idempotenti**: rilanciabili senza rischi
  (mostrano solo il diff / aggiornano).
- L'import TM è un **sync ricorrente** (le rose cambiano col mercato): rilanciarlo
  periodicamente tiene il pool aggiornato.
- Frontend in modalità `mock` (senza `VITE_API_PROVIDER=backend`): le pagine su dati
  reali (Serie A, Listone, dettaglio partita) mostrano un errore voluto.

---

## 5) Server: configurare l'invio email (Brevo) e Google

Le credenziali vivono SOLO nel `.env` del server, mai nel repo. Da lanciare tu,
collegato in SSH, sostituendo i valori tra virgolette.

```bash
ssh root@139.162.144.123

# --- Brevo (SMTP) ---
cd /srv/vfoot-app
# rimuove eventuali righe precedenti, poi riscrive
sed -i '/^DJANGO_EMAIL_BACKEND=/d;/^EMAIL_HOST=/d;/^EMAIL_HOST_USER=/d;/^EMAIL_HOST_PASSWORD=/d' .env
cat >> .env << 'FINE'
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp-relay.brevo.com
EMAIL_PORT=587
EMAIL_HOST_USER=IL_TUO_LOGIN_SMTP
EMAIL_HOST_PASSWORD=LA_TUA_CHIAVE_SMTP
EMAIL_USE_TLS=true
FINE

# --- Google (l'ID client NON e' un segreto) ---
sed -i '/^GOOGLE_OAUTH_CLIENT_ID=/d' .env
echo 'GOOGLE_OAUTH_CLIENT_ID=xxxxx.apps.googleusercontent.com' >> .env

systemctl restart vfoot

# --- prova che l'invio funziona davvero ---
cd /srv/vfoot-app/vfoot-backend/src
runuser -u vfoot -- /srv/vfoot-app/vfoot-backend/.venv/bin/python manage.py shell -c \
  "from django.core.mail import send_mail; \
   send_mail('Prova Vfoot', 'Se leggi questo, il relay funziona.', None, ['TUA@EMAIL.IT']); \
   print('inviata')"
```

Il **pulsante Google** ha bisogno dell'ID client anche nel frontend, che e'
compilato: va rifatto il build e ricaricato.

```bash
# in locale
cd vfoot-frontend
VITE_API_PROVIDER=backend VITE_API_BASE_URL=/api/v1 \
  VITE_GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com npx vite build
rsync -az --delete dist/ root@139.162.144.123:/srv/vfoot-web/
ssh root@139.162.144.123 'chown -R vfoot:vfoot /srv/vfoot-web'
```

Finche' `DJANGO_EMAIL_BACKEND` resta sulla console (stato attuale), la
registrazione **non** spedisce nulla: il link finisce nel journal, e si legge con
`journalctl -u vfoot | grep verifica-email`.
