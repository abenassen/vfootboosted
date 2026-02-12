# Vfoot Boosted – Frontend (Vite + React + Tailwind)

Questa è una prima versione completa del frontend, con **dati mock** basati sui data contract che abbiamo discusso.

## Funzionalità incluse
- Navigazione responsive: **sidebar** (desktop) + **bottom tabs** (mobile)
- Pagine base: Dashboard, Lega, Squadra, Partite, Mercato
- Pagine speciali:
  - **Formazione**: selezione 11 titolari, scelta portiere (slot dedicato), panchina, **riserve per-titolare**, campo a zone con copertura/qualità.
  - **Match detail**: mappa zone con vincitore/punti/margine/fattore chiave, pannello dettagli zona con macro-metriche e top contributori.

> Nota: i dati sono **mock** (simulati) e vengono serviti da `src/mock/api.ts`.

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

## Dove cambiare i dati
- Mock contratti: `src/mock/data.ts`
- Mock “API”: `src/mock/api.ts`

Quando collegherai il backend:
- sostituisci `src/mock/api.ts` con chiamate HTTP reali (fetch/axios)
- mantieni i tipi TS in `src/types/contracts.ts` come contratto condiviso

---

## Note UX
- Mobile: selettore tab dentro la pagina **Formazione** (Titolari / Rosa / Panchina)
- Desktop: layout a 3 colonne (Rosa / Campo / Panchina e riserve)

