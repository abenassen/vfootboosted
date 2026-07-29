# Provare la PWA e le notifiche da laptop

Domanda di partenza: *esiste un buon modo di testare una webapp su un portatile,
senza iPhone e senza passare dal telefono ogni volta?* Sì per quasi tutto, no per
un pezzo — e vale la pena sapere esattamente dove cade il confine.

Tre livelli, dal più automatico al più manuale.

---

## Livello 1 — automatico, offline, in 5 secondi

```bash
cd vfoot-frontend
npm run dev          # in un terminale
npm run test:pwa     # nell'altro
```

Sei test in `tests/pwa.spec.ts`. Verificano che il manifest sia servito e coerente
(nome, `display: standalone`, `start_url` dentro lo scope, icone 192/512 **e**
maskable), che le icone dichiarate esistano davvero come PNG, che `index.html`
porti `apple-touch-icon` e `theme-color`, che il service worker si registri e
prenda il controllo, e — la parte interessante — **che una push consegnata al
worker diventi la notifica giusta**, con titolo, corpo, tag e destinazione del
click.

La push viene iniettata via DevTools Protocol con
`ServiceWorker.deliverPushMessage`: è **lo stesso evento** che produce una
consegna reale da FCM, meno la rete. Quindi la logica del nostro worker è coperta
per davvero, non simulata a mano.

Serve Chrome vero, non lo shell headless di Playwright: il dominio `ServiceWorker`
del protocollo non esiste nello shell. È già configurato (`channel: 'chrome'` in
`playwright.config.ts`).

Un dettaglio che costa tempo se non lo si sa: **in sviluppo il worker non sta in
`/sw.js`**. Vite lo trasforma al volo e lo serve da `/dev-sw.js?dev-sw` come
modulo ES, mentre la build produce uno script classico in `/sw.js`. Registrare il
percorso di produzione durante `npm run dev` restituisce l'`index.html` della SPA
col MIME sbagliato e la registrazione fallisce in silenzio. Se ne occupa
`workerUrl()` in `src/pwa/registerSW.ts`.

## Livello 2 — l'anello completo, con la rete

```bash
npm run dev
npm run test:pwa:roundtrip
```

Questo esce dalla macchina. Genera una coppia VAPID usa e getta, iscrive un Chrome
vero al servizio push di Google, spedisce un payload cifrato a quell'endpoint con
`pywebpush`, e aspetta che il nostro service worker mostri la notifica. Copre ciò
che il livello 1 non può: la firma VAPID, la cifratura RFC 8291, FCM, e il
risveglio del worker da spento.

Le quattro righe che stampa sono i quattro punti dove può rompersi:

```
1/4  coppia VAPID generata (usa e getta)
2/4  iscritto al servizio push reale (fcm.googleapis.com)
3/4  payload cifrato accettato dal servizio push (HTTP 201)
4/4  notifica mostrata dal service worker: "..." → /decisioni
```

Non usa le chiavi del backend e non ha bisogno del backend acceso: la coppia nasce
e muore nello script, quindi non c'è modo di sporcare la produzione per sbaglio.

**Se questo passa e un telefono non riceve niente, il problema non è nel codice.**

## Livello 2b — il server vero verso il tuo telefono

Gli altri due livelli provano il codice. Questo prova *questo* deployment:

```bash
python manage.py vapid_keys              # una volta sola, poi in .env
python manage.py send_test_push --user andrea
```

Usa le chiavi di questa installazione e le subscription effettivamente in
database. Elenca le installazioni trovate, dice quante consegne sono riuscite, e
**rimuove da sé le subscription morte** (404/410 dal servizio push è l'unico
segnale che esista che un'installazione è sparita).

Da rilanciare dal Linode dopo ogni deploy che tocchi le chiavi.

## Livello 3 — dispositivi reali

### Android: c'è tutto già in casa

`adb` è installato e il telefono è tuo, quindi questo è il test buono, non un
ripiego:

1. Sul telefono: Impostazioni → Opzioni sviluppatore → Debug USB.
2. Collega il cavo, poi `adb devices` (autorizza il popup sul telefono).
3. `adb reverse tcp:5173 tcp:5173` e `adb reverse tcp:8000 tcp:8000` — così
   `localhost:5173` sul telefono è il tuo dev server. **Serve**: senza HTTPS il
   service worker gira solo su `localhost`, e l'IP di rete locale non basta.
4. Su Chrome desktop apri `chrome://inspect`, il telefono compare con le sue
   schede: hai console, rete e pannello Application del dispositivo reale.

Da lì il banner d'installazione arriva da sé (Android emette
`beforeinstallprompt`, che intercettiamo per mostrarlo dal nostro bottone in
Profilo → Notifiche e installazione). Le push funzionano **anche senza
installare**: su Android è iOS l'eccezione, non la regola.

### Desktop: installabile per davvero

Chrome su Linux installa la PWA come app a sé (icona nell'`⋮` della barra
indirizzi, o `chrome://apps`). Non è un surrogato: prova manifest, `display:
standalone`, il worker e le push reali sullo stesso percorso di un telefono
Android. Il pannello **Application** di DevTools ha manifest, service worker,
"Update on reload", "Offline", e un campo *Push* per spedire un payload a mano.

### iOS: qui il confine

**Non si può provare iOS da un portatile Linux.** Non c'è motore Safari-per-iOS,
il Simulator vuole un Mac, e le farm cloud (BrowserStack e simili) vanno bene per
il layout ma sull'installazione in schermata Home e sulle push sono inaffidabili:
la sessione è effimera e il permesso di notifica va concesso a mano sul
dispositivo.

Quel che si può fare, e che copre quasi tutto:

- **provare il percorso iOS-specifico dell'interfaccia** senza un iPhone. Le
  istruzioni d'installazione compaiono in base a `isIOS()` e `isStandalone()` in
  `src/pwa/install.ts`; con Chrome in emulazione dispositivo (Device Toolbar →
  iPhone) lo user agent diventa quello di iOS e la card mostra i quattro passaggi
  del tasto Condividi. Serve a controllare che il testo e i passaggi siano giusti,
  **non** che le push funzionino;
- **scrivere il codice per costruzione**: niente assunzioni, solo feature
  detection. `supportsPush()` e `pushBlockedReason()` esistono per questo: su iOS
  non installato non offriamo un bottone che fallirebbe, spieghiamo perché;
- **chiedere a un membro della lega con l'iPhone di fare il collaudo una volta.**
  In una lega da dieci amici questo è il canale di test giusto, non un
  compromesso: dieci minuti di una persona coprono l'unico caso che la macchina
  non vede.

---

## Cosa NON deve entrare in cache

L'errore che rende una PWA peggiore del sito che sostituisce: mettere in cache le
risposte API. Un utente vedrebbe i voti della settimana scorsa senza niente a
schermo che lo spieghi, e il bug sparisce appena apri DevTools.

La regola nel `vite.config.ts`: si precarica **solo l'output di build** — JS e CSS
con l'hash del contenuto nel nome, quindi immutabili per costruzione — e nulla
sotto `/api/`, mai. Da verificare dopo ogni modifica alla configurazione:

```bash
npm run build
grep -c "api/v1" dist/sw.js     # deve dire 0
```

## Il secondo deploy, non il primo

Un worker nuovo si installa e poi **aspetta** che tutte le schede dell'app si
chiudano prima di prendere il controllo. Su un telefono con l'app sempre aperta
quel momento non arriva mai, e la gente resta su una build vecchia per giorni.

Per questo `UpdateBanner` offre "È disponibile una nuova versione → Aggiorna", e
la scelta resta all'utente: ricaricare da soli sotto qualcuno che sta rilanciando
a un'asta sarebbe peggio di una versione di ritardo.

Come provarlo: `npm run build && npm run preview`, apri, poi cambia una riga di
codice, ricostruisci e ricarica. Deve comparire la fascia in basso.

## Le insidie note

| Sintomo | Causa |
|---|---|
| Nessun banner d'installazione su iPhone | Normale: Safari non lo emette. Va fatto a mano dal tasto Condividi. |
| Notifiche mai chieste su iPhone | Le push su iOS esistono **solo** dalla webapp in schermata Home. |
| Il permesso non si può più chiedere | Si chiede una volta sola: dopo un rifiuto serve passare dalle impostazioni del sito. |
| 401/403 dal servizio push | Chiavi VAPID cambiate dopo l'iscrizione: ogni browser ha legato la subscription alla chiave ricevuta. Non rigenerarle. |
| 404/410 dal servizio push | Installazione sparita. `push_channel` cancella la riga da sé. |
| Consegna riuscita, notifica assente | Dispositivo offline (il messaggio resta in coda) o permesso revocato a livello di sistema operativo. |
| Il service worker non si registra in `npm run dev` | Percorso sbagliato: in sviluppo è `/dev-sw.js?dev-sw`, non `/sw.js`. |
