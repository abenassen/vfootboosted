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
danni. Sta come allegato della release `dev-db`, **in un archivio cifrato**: il
repository è pubblico, e dentro ci sono dati di Serie A raccolti da Transfermarkt
e SofaScore, che usare per sviluppare è una cosa e ripubblicare un'altra.

**La passphrase te la dà Andrea** per canale privato. Non è nel repository, non è
nelle note della release, e non deve finirci.

```sh
gh release download dev-db --pattern 'vfoot-dev-db.7z'
7z x vfoot-dev-db.7z                                   # chiede la passphrase
mv vfoot-dev-db.sqlite3 vfoot-backend/src/db.sqlite3
```

Serve `7z` (`apt install p7zip-full`, `brew install p7zip`, o 7-Zip su Windows).

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
../.venv/bin/python manage.py export_dev_db           # -> dist/ (gitignorato)

# Cifrare DA DENTRO dist/, non da fuori: altrimenti l'archivio si porta dietro il
# percorso e chi lo apre si ritrova il file in una cartella `dist/` che non
# aspettava — con le istruzioni sopra che non funzionano piu'.
cd ../../dist
7z a -t7z -mhe=on -p vfoot-dev-db.7z vfoot-dev-db.sqlite3
gh release upload dev-db vfoot-dev-db.7z --clobber
```

`-mhe=on` cifra anche l'indice: senza la passphrase l'archivio non rivela nemmeno
cosa contiene. La **prima volta** la release va creata, non solo aggiornata:
`gh release create dev-db <file> --notes-file <note> --latest=false`.

Una passphrase lunga e casuale (25 caratteri va bene), mai riusata altrove, e
mai nelle note. Quello che pubblichi è per sempre: se un domani la passphrase
sfugge, la copia già scaricata da qualcuno resta leggibile, e l'unico rimedio è
caricare un archivio nuovo con una passphrase nuova.

Il comando usa l'API di backup di SQLite, quindi lo snapshot è coerente anche
col dev server acceso, e anonimizza sempre (email, password, token API) a meno
di `--no-anonymize`. Le subscription push si svuotano **in ogni caso**, anche con
`--no-anonymize`: sono indirizzi di un dispositivo preciso, non dati di un
account, e questo file finisce in una release pubblica.

Nella copia snella il **voto puro non è ricalcolabile** (mancano le zone
feature): le giornate già concluse si vedono, ricalcolarne una no, e le pagelle
di Serie A restano vuote. Per lavorare sul modello di voto serve
`--keep-zones`.

## Lavorare sulla UI ora che c'è un service worker

Da luglio 2026 il frontend è una PWA, e **il service worker gira anche in
sviluppo**. È deliberato (è ciò che rende collaudabili installazione e notifiche
senza un telefono), ma cambia una cosa nella vita di tutti i giorni:

- **Se vedi contenuti vecchi che non corrispondono al codice, è lui.** DevTools →
  Application → Service Workers → spunta **"Update on reload"** e lascialo
  spuntato mentre sviluppi. In caso di dubbio, "Unregister" e ricarica.
- In sviluppo il worker sta in `/dev-sw.js?dev-sw`, non in `/sw.js`: Vite lo
  trasforma al volo. Se ne occupa `workerUrl()` in `src/pwa/registerSW.ts` — non
  cambiare quel percorso senza leggere il commento.
- **Nulla sotto `/api/` va messo in cache, mai.** Un worker che serve una risposta
  API vecchia mostra i voti della settimana scorsa senza niente a schermo che lo
  spieghi. Se tocchi `vite.config.ts`, riverifica:

  ```sh
  npm run build && grep -c "api/v1" dist/sw.js     # deve dire 0
  ```

Script utili, tutti da `vfoot-frontend`:

```sh
npm run test:pwa            # manifest, worker, notifiche — offline, 5 secondi
npm run test:pwa:offline    # costruisce e prova che la shell si apra senza rete
npm run test:pwa:roundtrip  # anello push completo: esce in rete, serve il venv
```

Servono **Chrome vero** (non lo shell headless di Playwright): è già configurato
in `playwright.config.ts`. Il dettaglio di cosa provano e cosa no sta in
`vfoot-backend/docs/PWA_TESTING.md`.

Due cose che sembrano guasti e non lo sono:

- in Profilo → Notifiche e installazione può comparire *"Le notifiche push non
  sono attive su questo server"*: è lo stato normale finché non esistono le chiavi
  VAPID (`manage.py vapid_keys`), e gli avvisi viaggiano per email;
- `npm run test:e2e:mock` riporta **1 skipped**: quello smoke test guida
  un'interfaccia precedente ed è marcato `fixme` con l'elenco di cosa è vecchio.
  Riscriverlo è un lavoro a sé, non un tuo errore di setup.

## Note sparse

- `?api=mock` in coda a qualsiasi URL fa girare la pagina sui dati finti senza
  toccare il backend: comodo per lavorare su un componente isolato.
- Il DB è SQLite in sviluppo e PostgreSQL in produzione. Per il lavoro sulla UI
  è indifferente, ma evita SQL grezzo specifico di SQLite.
- Convenzioni di codice e stato del progetto: `AGENTS.md`. Deploy: `vfoot-backend/deploy/DEPLOY.md`.
