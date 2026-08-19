# Prospettive e cose da fare

Elaborazione degli spunti raccolti in `idee_commenti.txt`. Ogni voce dice **cosa
si è deciso**, **cosa resta aperto** e **quanto costa**, così che riprendere un
filo non richieda di ricostruirne il contesto da capo.

Stato al 22/07/2026.

---

## 1. Listone vivo tutto l'anno (in corso)

**Il problema.** Una lega nasce tipicamente pochi giorni prima dell'asta, a
mercato di agosto ancora aperto. Il listone quindi *non* è una fotografia
scattata una volta: continua a muoversi per arrivi e cessioni, in agosto e poi di
nuovo a gennaio.

**Il modello deciso.**

1. **Polling periodico da Transfermarkt** che aggiorna le rose.
2. Ogni aggiornamento **semina automaticamente** i ruoli dei nuovi arrivati,
   usando lo stesso criterio della lega — variante ibrida (posizione TM dove è
   inequivocabile) o pura dai dati, secondo `FantasyLeague.role_mode` — con
   disambiguazione dalle categorie storiche quando il giocatore ha dati.
3. Quando il criterio **non basta** (posizione TM ambigua e nessuno storico) si
   apre una decisione per l'admin.
4. **Finché la decisione è aperta, quel giocatore è in limbo**: non compare fra i
   selezionabili all'asta, e un inserimento manuale a roster che lo contiene dà
   errore. La lega per il resto continua a funzionare.

Il punto 4 è la correzione importante rispetto alla prima versione, che bloccava
l'intero mercato: accettabile al listone iniziale, sbagliato a gennaio, dove un
singolo acquisto avrebbe congelato tutta la lega. Il blocco **per-giocatore**
rende lo stesso meccanismo valido tutto l'anno.

**Il congelamento è per-giocatore, non per-lega** (specifica utente 23/07/2026,
testata in `tests_decisions.DepartureReturnTests`). Il ruolo si fissa quando il
giocatore **entra la prima volta** nel listone e non muta più; il listone come
*membership* invece è vivo (arrivi/partenze a ogni poll). Conseguenze:
- se TM **cambia il ruolo** di un giocatore, le leghe dove è **già presente** non
  ne risentono (riga frozen intatta); solo le leghe **create dopo** pescano il
  ruolo aggiornato dal listone di quel momento;
- un giocatore che **parte** per l'estero (stint chiusa) tiene la sua riga come
  storia — non viene cancellato; al **rientro** (gennaio) la riga è preservata,
  quindi il ruolo resta **quello consolidato all'inizio**, anche se TM l'ha
  riclassificato durante l'assenza.

**Risolto (23/07/2026): TM gira dal Linode.** La sonda
`realdata/scripts/probe_transfermarkt.py` (o l'equivalente `curl`) dà dall'IP
Linode `139.162.144.123` esattamente lo stesso esito dell'IP residenziale —
`200`, tabella rosa presente, zero challenge. TM è un origin nginx puro senza
anti-bot, quindi **non** eredita il blocco di SofaScore. Il polling del listone
può stare interamente sul server: niente IP residenziale né Raspberry per questa
parte.

**Fatto: orchestrazione + cadenza.** `manage.py poll_transfermarkt` fa scrape
fresco + import in un colpo, pensato per girare non presidiato. Modello corretto:
il **listone resta LIVE** (stint aperte/chiuse dal mercato reale a ogni import); a
congelarsi sono solo le **attribuzioni di ruolo per-lega** (`LeaguePlayerRole`,
snapshot additivo — i nuovi arrivi vengono seminati, i ruoli esistenti non
derivano mai). Cadenza: **due volte al giorno** (unità `vfoot-tm-poll` in
`deploy/systemd/`), lasciata attiva tutto l'anno perché lo scrape è leggero;
l'utilità è massima a mercato aperto (ago/gen).

Tre presidi aggiunti per l'esecuzione non presidiata (innocui a mano, pericolosi
in automatico): scrape sempre fresco (lo scraper standalone salta la cache), la
stagione TM è **derivata** dalla `CompetitionSeason` così non possono divergere
(altrimenti si confronta la rosa di una stagione contro le stint di un'altra →
partenze fantasma), e si rifiutano sia le chiusure-partenza quando lo scrape è
incompleto (un club mancante farebbe risultare "partita" tutta la sua rosa) sia
le mappature-club sotto `--min-map-score` (un promosso mal accoppiato importerebbe
la rosa sbagliata).

**Dipendenza:** il job va deployato col codice corrente — produzione è ferma a
`03b099b` e non ha `poll_transfermarkt`.

---

## 2. Polling dati partite: RISOLTO — Surfshark in netns sul Linode

**Diagnosi corretta (23/07/2026).** Il blocco NON è per classe di IP: è un
**Cloudflare managed challenge per reputazione del SINGOLO IP**, variabile per-IP e
nel tempo. L'IP del Linode è bruciato (403); molti IP hosting Surfshark passano
tranquillamente. Verificato via `curl_cffi` (impersonate chrome): dall'uscita
Surfshark `84.17.58.201` (DataCamp, `hosting=True`) TUTTI gli endpoint tornano 200.

**Confermato che risolve dal Linode.** WireGuard Surfshark in un **network
namespace** sul Linode → l'uscita è l'IP del server Surfshark (non del Linode), e
SofaScore torna 200 su tutti gli endpoint (lineups/shotmap/incidents/heatmap + www).
Il netns isola il tunnel: SSH e l'app sul server restano sulla rotta normale. Quindi
il polling partite gira interamente lato server, come TM — **niente Raspberry, niente
IP dedicato da comprare.**

**Strumenti pronti (in scratchpad + `/root/` sul Linode):**
- `sofa_vpn_sweep.sh` — sweep netns dal laptop che mappa i server Surfshark che
  passano (sequenziale/ripartibile per non innescare il rate-limit handshake), →
  `sofa_vpn_pool.json`. Tasso di successo osservato ~21%, `PASS` concentrati in
  Europa occ. (IT/UK/ES/CH) + qualche USA.
- `linode_sofa_vpn_test.sh` + `sofa_probe_full.py` — validazione sul Linode (fatta).
- Chiave client Surfshark in `/etc/wireguard/surfshark_wg.conf` (laptop e Linode);
  `wireguard-tools` installato sul Linode.

**Egress layer COSTRUITO e testato (23/07/2026)** — `vfoot-backend/egress/`
(standalone, stdlib; sul Linode in `/root/egress/`, isolato dall'app congelata):
- `sofascore_egress.py` — pool auto-rinfrescante di IP-uscita buoni. Sorgenti vive:
  catalogo Surfshark + DNS dei cluster (per seguire la rotazione IP) + sonda
  SofaScore. Comandi: `refill` (scopre candidati, pinna e sonda, tiene i PASS),
  `status`, `probe`, `fetch`. Testato: da 420 candidati costruisce un pool; `fetch`
  di una partita reale scarica lineups/shotmap/incidents/heatmap nel cache dal
  Linode via l'IP del pool, con rotazione+declassamento al blocco (auto-validante).
- `fetch_worker.py` — gira DENTRO il netns; riceve match id (mai dal DB), scalda la
  cache; exit 3 = bloccato → l'orchestratore ruota IP.
- Chiave Surfshark DEDICATA al Linode in `/etc/wireguard/surfshark_wg.conf` (l'uso
  personale della VPN non interferisce). `wireguard-tools` installato.

**Struttura del polling (concordata).** Due loop distinti, non uno:
- **Loop A — sync calendario** (cadenza grossa: poche volte/die, più denso i giorni
  di gara). Via egress scarica lo schedule stagione → riconcilia il calendario DB
  (partite/orari/rinvii/stato). Risponde a "quali match e quando". Prende i rinvii
  *programmati*.
- **Loop B — tick** (ogni 1-2 min). NON ri-scarica la lista: legge il DB + orologio e
  agisce solo sui match in finestra live/finalizzazione. Ciclo per-match
  **stato-prima**: (1) fetch leggero stato `/event/{id}`; (2) `inprogress` → dati
  live; (3) `finished` → stampa `finished_at` → finalizzazione +15m (provvisorio) e
  +1h (conferma → `data_ready=True`, ufficiale); (4) `notstarted/postponed` con
  timestamp cambiato → riconcilia il calendario nel DB. Il caso 4 rende il tick
  **auto-correttivo** sui rinvii dell'ultimo secondo (quelli che il Loop A perde).

**Lato DB-aware COSTRUITO (23/07/2026), validato in produzione, DISABILITATO.**
`realdata/services/live_ingest.py` + `egress_client.py`, agganciati a `tick` e a
`sync_calendar --egress` (test in `tests_live_pipeline`). `tick` decide QUALI match
sono dovuti (calendario DB), l'egress scalda la cache attraverso il ponte `sudo`
stretto (`/usr/local/sbin/vfoot-egress`, sudoers `vfoot`→root), poi il codice
OFFLINE esistente la legge: `poll_live` aggiorna stato/punteggio/kickoff (riusa la
mappa di `calendar_sync`, cattura fine-partita e rinvii last-second); `finalize`
scalda il set completo + `ingest_sofascore_season` → `data_ready`. Lo stato avanza
solo su warm riuscito (egress bloccato ⇒ ritenta al tick dopo). Validato sul Linode:
ponte `sudo` ok, `schedule 26/27` scaldato via tunnel nella cache reale.

Unità systemd tutte staged e **spente**: `vfoot-tm-poll`, `vfoot-egress-refill`
(indipendenti, accendibili subito), `vfoot-calendar` (Loop A, `--egress`),
`vfoot-tick` (Loop B). Al lancio: `systemctl enable --now` (vedi `deploy/DEPLOY.md`).
Resta solo da **rendere operativo** (accendere i timer) al go-live.

---

## 3. Profilo utente

**Il difetto.** Esiste solo `auth/me` in lettura. I dati dell'utente compaiono
come etichetta inerte dentro "Le mie leghe", che è anche il posto sbagliato:
l'utente esiste al di là della lega.

**Da decidere prima di scrivere codice**, perché sono scelte sull'identità e non
tecnicalità:

- lo username è modificabile, o è l'identificatore stabile?
- cambiare email fa ripartire la verifica? Nel frattempo l'account resta attivo?
- si può impostare una password su un account nato da Google (oggi ha una
  password inutilizzabile)? Il flusso naturale è il reset via email.
- scollegare l'account Google: permesso solo se esiste una password, altrimenti
  l'utente si chiude fuori.

**Costo.** Mezza giornata una volta prese le decisioni.

---

## 4. Spiegazione del voto (fatto, estendibile)

Implementata: dalla pagella si apre "perché questo voto?" e si vede lo scarto
dalla media del ruolo in **punti di voto**.

**Estensioni naturali**, in ordine di utilità:
- la stessa spiegazione nel listone, come sintesi stagionale del giocatore;
- confronto fra due giocatori sullo stesso metro (utile in asta);
- spiegazione del *fantavoto*, che oggi si ferma al voto puro e non racconta i
  bonus.

---

## 5. Webapp installabile (PWA): FATTA — resta il collaudo su iPhone

Manifest, icone (comprese le *maskable*, che Android ritaglia), service worker
scritto a mano perché deve gestire `push` e `notificationclick`, avviso di
aggiornamento, e le notifiche push agganciate al canale che già esisteva per le
email (`league_notifications`: due canali, una sola decisione su *cosa* dire).

La cache è configurata come dice la nota di prima: si precarica **solo** l'output
di build, con l'hash del contenuto nel nome, e nulla sotto `/api/`. Un test lo
verifica (`grep -c "api/v1" dist/sw.js` deve dire 0).

Come si prova, tutto in **`vfoot-backend/docs/PWA_TESTING.md`**. In breve:
`npm run test:pwa` è offline in 5 secondi e include una push consegnata al worker
via DevTools Protocol; `npm run test:pwa:roundtrip` fa l'anello vero con VAPID,
cifratura e FCM; `manage.py send_test_push --user X` prova *questo* server verso
il tuo telefono. Android si collauda dal cavo con `adb reverse` +
`chrome://inspect`.

**Cosa resta**: generare le chiavi VAPID in produzione (`manage.py vapid_keys`) e
il collaudo su iOS, che da Linux non è simulabile — serve dieci minuti di un
membro della lega con l'iPhone. Su iOS le push esistono solo dall'app aggiunta
alla schermata Home, e Safari non lo propone: l'istruzione è in Profilo →
Notifiche e installazione, ma il passaparola dell'admin resta il canale vero.

Da sapere per non dubitare del codice: la **prima** iscrizione può richiedere una
ventina di secondi (misurati 28 su un browser freddo), perché è il browser che si
registra al proprio servizio push. L'interfaccia lo dice, altrimenti sembra rotta.

---

## 6. Mobile: selezione e navigazione

Le liste a discesa sono il punto debole segnalato. Da guardare insieme per
capire *quali*: il selettore di lega e competizione sono già compatti, mentre
listone e mercato hanno liste lunghe dove uno swipe o una ricerca incrementale
cambierebbero l'esperienza.

Da valutare anche la formazione, che su schermo piccolo è la pagina più densa.

---

## 7. Notiziario della lega

La home di lega oggi è statica: dice com'è messa la squadra, non che cosa è
**successo**. Un flusso di notizie — acquisti e svincoli, offerte rilanciate e
concluse, decisioni prese e consultazioni aperte, giornate chiuse, cambi di
ruolo, arrivi e partenze dal listone reale — la rende il posto dove si torna,
e insieme dà a chi non segue giorno per giorno tutto quello che gli serve.

Buona notizia architetturale: **gli eventi in gran parte esistono già**, solo
sparsi. `MarketEvent` e `AuctionEvent` sono log append-only con tipo, attore,
payload JSON e istante, cioè già la forma giusta; `LeagueDecision` ha apertura,
consultazione ed esito con chi ha deciso e quando; la rosa conserva lo storico
dei contratti; le giornate hanno una conclusione datata. Manca il posto dove
confluiscono e la resa in italiano.

Due strade, e conviene sceglierle consapevolmente:

- **Tabella unica `LeagueEvent`**, scritta dai servizi che già sanno (lo stesso
  `record_event` del mercato a offerte, generalizzato). Lettura banale e
  paginabile, un aggancio per sorgente, e lo storico esistente si recupera
  rigiocando `MarketEvent` e le decisioni risolte.
- **Aggregazione a lettura**, interrogando ogni sorgente e fondendo per data.
  Nessuna migrazione e nessun backfill, ma una query che si allarga a ogni
  sorgente nuova e paginazione scomoda.

La prima, salvo sorprese: il costo è un hook per sorgente, una volta.

Tre cose da decidere prima di scrivere codice, tutte di prodotto:

1. **Il rumore.** Un'asta da 500 giocatori non può diventare 500 righe. Serve
   aggregazione ("Panda ha chiuso l'asta con 25 acquisti") e probabilmente una
   soglia di rilevanza, come già facciamo per la coda dell'admin.
2. **La visibilità.** Tutto a tutti, o certi eventi solo a chi riguardano? Una
   consultazione è di lega, un'offerta persa è personale.
3. **Il rapporto con le notifiche.** Un flusso di eventi è esattamente ciò da
   cui pesca un riepilogo per email o una push (§5): conviene disegnarlo
   sapendo che quella sarà la seconda lettura, non solo la home.

---

## 8. Coinvolgimento: commenti, chat, meme

Richiede scelte di prodotto prima che tecniche. Una nota architetturale utile: il
meccanismo `LeagueDecision` costruito per i ruoli è **generico** (tipo, oggetto,
opzioni, esito, voto consultivo) e regge già discussioni e votazioni di lega su
qualunque argomento. Un thread di commenti è vicino, non lontano.

Da decidere: moderazione, notifiche, e se i contenuti restano dentro la lega o
sono pubblici.

---

## 9. Bot WhatsApp

Richiede un servizio esterno (API Business o simili), con costi e verifica del
numero. Da valutare rispetto all'alternativa più semplice: notifiche push della
PWA, che non dipendono da terzi e arrivano sullo stesso telefono.

---

## 10. Notifiche del mercato: il cron che serve davvero (31/07/2026)

**Cosa non serve.** La scadenza di una sessione di mercato **non** ha bisogno di
un processo che la sorvegli. `market_engine.sync_session` è chiamato da
`_live_session`, e quindi da ogni endpoint del mercato: la sessione risulta
chiusa alla prima richiesta che arriva dopo `closes_at`, e chi prova a offrire
oltre il termine riceve «Nessuna sessione di mercato aperta». Nessun cron è
richiesto per la correttezza — vedi `tests_market_close.py`.

**Cosa serve.** Le notifiche. Alla chiusura ogni offerta ancora in testa passa in
validazione, e le persone coinvolte vanno avvisate:

- a chi era in testa: *ti sei aggiudicato X, in attesa di validazione*;
- a chi è stato superato e non lo sa;
- all'admin: *ci sono N offerte da validare*;
- (a offerta matura per le 24h, lo stesso avviso senza aspettare la chiusura.)

Quello all'admin **va ripetuto finché la coda non è vuota**, non mandato una
volta sola alla chiusura. La coda non si smaltisce da sola: nessun percorso
automatico porta un'offerta da `accepted` a `settled`, solo il bottone
dell'admin. Un'offerta dimenticata lì dentro tiene il giocatore impegnato — non
è riofferibile nemmeno nella sessione successiva — e la rosa di chi l'ha vinta
resta ferma. Dal 02/08/2026 la coda almeno sopravvive alla sessione ed è
raggiungibile (prima spariva con essa), ma resta invisibile a chi non apre
Gestione lega.

Queste **non possono partire da sole**: non c'è nessuna richiesta a cui
agganciarle, ed è proprio quando nessuno sta guardando che l'avviso conta.
`manage.py market_tick` esiste già, è idempotente, e oggi non è agganciato a
nulla — nessun cron, nessun timer systemd, nessuna riga nel deploy.

**Il lavoro**, in ordine:

1. ~~mettere `market_tick` nel cron del Linode (ogni 60–90 s)~~ — **FATTO
   (02/08/2026)**: unità `vfoot-market` ogni 90 s, staged e spenta come le altre.
   L'inventario di tutto lo schedulato è in `deploy/systemd/README.md`;
2. fargli emettere le notifiche sugli eventi che genera, sul canale
   `league_notifications` che già serve email e push (§5) — una sola decisione su
   *cosa* dire, due modi di dirlo;
3. decidere **cosa merita un avviso**: la chiusura sì di sicuro; il singolo
   sorpasso è utile ma può diventare rumore in una contesa vivace, e vale la pena
   guardarlo dopo il primo mercato vero.

Prerequisito condiviso con §5: le chiavi VAPID in produzione.

---

## Debiti tecnici aperti

- **Portieri: voto compresso.** Sette valori distinti contro i dodici dei
  difensori, perché la deviazione standard del loro indice è quasi doppia. Si
  correggerebbe con uno `spread_k` dedicato al canale, da calibrare. Nota che
  sui portieri **noi battiamo fantacalcio.it** (0,785 contro 0,606 verso il
  rating indipendente): il problema è la granularità, non la qualità.
- **Aura non riverificata dopo la correzione delle coordinate.** I tiri erano
  collocati nella metà campo sbagliata; i vettori di zona su cui poggia la
  modalità Aura giravano su quei dati. Ora sono corretti ma non ho verificato
  cosa cambia per quella modalità.
- **Uno script `vfoot-deploy`**, sorella di `vfoot-dev` e `vfoot-sim`, che
  racchiuda i sei passi di `DEPLOY.md` con l'host scritto dentro. Oggi il
  rilascio è una ricetta da ricopiare a mano, e per farlo fare a Claude servono
  tre permessi larghi — `Bash(ssh *)`, `Bash(scp *)`, `Bash(rsync *)` — che non
  sono vincolati a nessuna destinazione: autorizzano quei comandi verso qualunque
  macchina. Con lo script diventerebbero una regola sola, `Bash(./vfoot-deploy
  *)`, e il Linode sarebbe l'unico posto raggiungibile. In più i passi
  diventerebbero ripetibili singolarmente (`backup`, `frontend`, `verify`) e i
  controlli finali smetterebbero di dipendere dalla memoria. Rimandato il
  19/08/2026 per non allungare un rilascio già pronto.
- **Blocco formazione al fischio d'inizio**, mai implementato.
- **Produzione ferma** al commit `03b099b`. Il deploy richiede migrazioni,
  reimportazione e ricalcolo dei ruoli.
