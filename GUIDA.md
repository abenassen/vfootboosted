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
