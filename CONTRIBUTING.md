# Lavorare a Vfoot — avvio da zero

Guida per chi arriva sul progetto da un'altra macchina e lavora
principalmente sull'**interfaccia**. Dal clone all'app funzionante con dati
veri sono una decina di minuti, quasi tutti di `npm install`.

## Cosa serve

- Python **3.12+**
- Node **22+**
- `git`, e `gh` (GitHub CLI) per scaricare il database

## Setup

### 1. Clone

```sh
git clone git@github.com:abenassen/vfootboosted.git
cd vfootboosted
```

### 2. Backend: venv e dipendenze

```sh
python3 -m venv vfoot-backend/.venv
vfoot-backend/.venv/bin/pip install -r vfoot-backend/requirements.txt
```

### 3. Frontend: dipendenze

```sh
cd vfoot-frontend && npm install && cd ..
```

### 4. File di configurazione

Nessuno dei due è nel repo (contengono roba specifica della macchina):

```sh
cp .env.example .env
cp vfoot-frontend/.env.example vfoot-frontend/.env.local
```

Nel `.env` appena copiato genera una secret key:

```sh
vfoot-backend/.venv/bin/python -c \
  "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

e incollala in `DJANGO_SECRET_KEY`. Le altre righe vanno bene come sono
(`DJANGO_DEBUG=true`, `DB_ENGINE=sqlite`).

In `vfoot-frontend/.env.local` cambia **una** riga:

```
VITE_API_PROVIDER=backend
```

Il valore di default è `mock`, che fa girare la UI su dati finti senza
backend — utile, ma non è quello che vuoi qui. Il `VITE_API_BASE_URL` non
toccarlo: lo gestisce lo script del punto 6.

### 5. Il database

Il DB non è nel repo: è un file SQLite da 51 MB, e i binari in git fanno solo
danni. Sta come allegato di una release:

```sh
gh release download dev-db --pattern 'vfoot-dev-db.sqlite3.gz'
gunzip vfoot-dev-db.sqlite3.gz
mv vfoot-dev-db.sqlite3 vfoot-backend/src/db.sqlite3
```

Contiene la Serie A 2025/26 importata (1.706 giocatori, 1.145 partite, 34.523
presenze) e una lega classic demo a 10 squadre con 36 giornate già giocate e
refertate — quindi calendario, classifica, rose, formazioni e tabellini sono
tutti popolati e navigabili.

**Credenziali:** utente `andrea`, password `vfoot-dev` (è anche superuser, per
`/admin`). Tutti gli account nel dump hanno quella password: sono account di
test, l'anonimizzazione è fatta apposta perché il file è pubblico.

### 6. Avviare

```sh
./vfoot-dev local
```

Avvia backend e frontend insieme e stampa l'indirizzo. `./vfoot-dev status`
dice cosa gira, `./vfoot-dev stop` ferma tutto. Se vuoi provare l'app dal
telefono sulla stessa rete usa `./vfoot-dev lan`: rileva da solo l'IP della
macchina e riallinea i quattro punti in cui compare.

> Non avviare i server a mano se puoi evitarlo: l'indirizzo dell'host compare
> in quattro file diversi, e tenerli d'accordo a mano è esattamente il tipo di
> errore che poi si manifesta come pagina bianca o 400 DisallowedHost.

## Cosa NON funziona con questo database

Il dump è alleggerito togliendo `PlayerZoneFeature` e `TeamZoneFeature`: erano
il 93% degli 865 MB originali. Sono gli input grezzi per zona da cui il voto
puro viene **ricalcolato a ogni lettura**. Senza di loro:

- ricalcolare o concludere una giornata dà voti vuoti;
- le pagelle della Serie A reale (`classic_pagella`) non si popolano;
- il tuning del voto puro e `compute_classic_roles` non hanno dati.

Le giornate **già** concluse si vedono normalmente: i tabellini sono salvati in
`FantasyFixtureDetail` e non vengono ricalcolati.

Se ti serve lavorare sul modello di scoring e non sulla UI, chiedi il dump
completo: si genera con `manage.py export_dev_db --keep-zones`.

## Rigenerare il dump (per chi ha il database completo)

```sh
cd vfoot-backend/src
../.venv/bin/python manage.py export_dev_db --gzip     # -> dist/ (gitignorato)
gh release upload dev-db ../../dist/vfoot-dev-db.sqlite3.gz --clobber
```

Il comando usa l'API di backup di SQLite, quindi lo snapshot è coerente anche
col dev server acceso, e anonimizza sempre (email, password, token API) a meno
di `--no-anonymize`.

## Note sparse

- `?api=mock` in coda a qualsiasi URL fa girare la pagina sui dati finti senza
  toccare il backend: comodo per lavorare su un componente isolato.
- Il DB è SQLite in sviluppo e PostgreSQL in produzione. Per il lavoro sulla UI
  è indifferente, ma evita SQL grezzo specifico di SQLite.
- Convenzioni di codice e stato del progetto: `AGENTS.md`. Deploy: `vfoot-backend/deploy/DEPLOY.md`.
