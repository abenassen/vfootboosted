# Vfoot Boosted – Frontend (Vite + React + Tailwind)

Questa è una prima versione completa del frontend, con **dati mock** basati sui data contract che abbiamo discusso.

## Funzionalità incluse
- Navigazione responsive: **sidebar** (desktop) + **bottom tabs** (mobile)
- Pagine base: Dashboard, Lega, Squadra, Partite, Mercato
- Pagine speciali:
  - **Formazione**: selezione 11 titolari, scelta portiere (slot dedicato), panchina, **riserve per-titolare**, campo a zone con copertura/qualità.
  - **Match detail**: mappa zone con vincitore/punti/margine/fattore chiave, pannello dettagli zona con macro-metriche e top contributori.

> Nota: puoi usare sia **mock** sia **backend reale** tramite switch API.

---

## Requisiti
- Node.js 18+ (consigliato 20+)
- npm (o pnpm/yarn)

## Avvio in locale

```bash
cd vfoot-frontend
npm install
npm run dev
```

Apri poi:
- Desktop: `http://localhost:5173`
- Mobile: usa la modalità responsive del browser, oppure apri dal telefono sulla tua LAN:
  - `http://<IP_DEL_TUO_PC>:5173`

> Se Vite non espone su LAN, avvia con:
> `npm run dev -- --host`

## Build
```bash
npm run build
npm run preview
```

---

## Switch API (mock/backend)
Il frontend usa un adapter unico in `src/api/index.ts`.

Configura `.env.local` (puoi partire da `.env.example`):

```bash
cp .env.example .env.local
```

Opzioni:

```env
VITE_API_PROVIDER=mock
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

- `VITE_API_PROVIDER=mock` usa `src/mock/api.ts`
- `VITE_API_PROVIDER=backend` usa `src/api/backend.ts` (fetch verso Django)

Override rapido per singola sessione browser:
- aggiungi `?api=mock` oppure `?api=backend` all'URL.

I tipi in `src/types/contracts.ts` restano il contratto condiviso frontend/backend.

---

## Note UX
- Mobile: selettore tab dentro la pagina **Formazione** (Titolari / Rosa / Panchina)
- Desktop: layout a 3 colonne (Rosa / Campo / Panchina e riserve)
