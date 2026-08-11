# Cosa fare prima di riaprire il sito

Non è un deploy incrementale. La produzione è ferma a `03b099b`, **oltre 200
commit indietro**, e dietro il 503 di manutenzione da fine luglio: quello che
segue non è una checklist di rito, è la differenza fra riaprire e riaprire rotti.

L'ordine conta. I primi due blocchi possono invalidare il resto, quindi si fanno
per primi.

---

## 1. Validare i voti, che si sono mossi

**Perché prima di tutto**: se il confronto dice che qualcosa non torna, cambia il
codice — e ogni prova fatta prima va rifatta.

Il filtro stagione su `player_form` e `player_footprints` ha corretto un difetto
reale (leggevano anche la stagione precedente, mescolata), ma i numeri si sono
spostati:

| | quanto |
|---|---|
| valori di forma cambiati | 17 su 23 |
| impronte cambiate | 21 giocatori su 24 |
| scarto per zona | medio 0,024 · massimo 0,248 |

Le impronte alimentano anche `role_from_footprint`, quindi **qualche ruolo
inferito può essere cambiato**.

- [ ] Rigenerare il **benchmark HTML** (`build_voto_benchmark`) e confrontare MAE
      e punti deboli con l'ultimo giro noto (era 0,35, portieri il punto debole).
- [ ] Rigenerare il **replay della Fantaresilienza**
      (`build_fantaresilienza_report`) e guardare se la classifica giornata per
      giornata si muove in modo spiegabile.
- [ ] Se qualcosa peggiora in modo non spiegabile dalla correzione, **fermarsi**:
      il difetto era reale, ma la sua correzione non è stata validata su una lega
      intera, solo su una rosa.

## 2. I nostri ruoli contro il listone Fantacalcio 2026-27 — FATTO

`Quotazioni_Fantacalcio_Stagione_2026_27.xlsx` (in radice, non versionato) è la
**stessa stagione che si andrà a giocare**: non è un anticipo su una stagione
futura, sono due previsioni sullo stesso campionato. 497 giocatori, 20 squadre,
colonna `R` col ruolo classico e `RM` col Mantra.

Confronto eseguito il 10/08/2026, riusando il matcher di
`voto_puro_discrepancies` (cognome + iniziale, indicizzato sulle squadre in cui
il giocatore ha davvero giocato). 413 agganciati, 84 fuori — nuovi acquisti e
Primavera, che nella nostra banca dati non hanno presenze.

**Accordo 92,7% (383/413), 30 discrepanze.** Concentrate, non sparse:

```
righe = loro, colonne = noi
POR   0 · 0 · 0 · 0      porta: accordo perfetto, 60/60
DIF   0 · 0 · 1 · 0
CEN   0 · 3 · 0 · 21     ← ventuno CEN che per noi sono ATT
ATT   0 · 0 · 5 · 0
```

Ventisei su trenta stanno sull'asse centrocampo↔attacco, e quasi tutte hanno un
`RM` **ambiguo** (`W;A`, `T;A`, `W;T`): sono ali, che il Fantacalcio classico è
costretto a schiacciare in una casella sola e che per convenzione mette a CEN.

Sui big il disaccordo è raro ma non nullo: 2 su 16 con Qt.A ≥ 20 — **Orsolini**
(Qt.A 26) e **Pulisic** (25), entrambi `CEN` per loro e `ATT` per noi.

**Bilancio dei reparti**: −18 CEN e +16 ATT rispetto a loro (−12% / +22%). Non
compromette le rose: per 10 squadre 3-8-8-6 servono 80 CEN e ne abbiamo 138 sui
soli agganciati, margine 1,7×. L'effetto è sui **prezzi d'asta**, non sulla
legalità delle formazioni.

**Non c'è una manopola per avvicinarsi**, e vale la pena saperlo prima di
provarci: il ruolo lo prende la CATEGORIA k-means, non il giocatore, quindi si
sposta un cluster intero o niente. `ROLE_MARGIN_REVIEW` non serve allo scopo —
`needs_decision()` documenta che i discordanti sicuri (De Ketelaere, margine
0,76) sono proprio quelli che un filtro sul margine non cattura.

Quello che il sistema fa già: **15 dei 30 arrivano alla decisione dell'admin** —
i non misurati (metodo `sofa`/`default`) più Berardi, che è misurato e in bilico
(margine 0,21). I sicuri non ci arrivano, per scelta.

- [ ] Guardare a mano gli otto casi dove il Mantra NON giustifica il disaccordo:
      i cinque `ATT→CEN` (Berardi, De Ketelaere, Esposito Se., Ghedjemis,
      Kvernadze) e i tre che coinvolgono la difesa.
- [ ] Decidere se in coda di arbitraggio mostrare anche il ruolo del listone
      accanto al nostro: sarebbe un dato in più per l'admin, senza toccare il
      modello. È la strada meno invasiva, se si vuole convergere.

## 3. Migrazione e dati

- [ ] **`0022_jobrun`** e **`0023_maintenancerun_maintenanceproposal`** sono
      migrazioni nuove: vanno applicate in produzione. Non sono distruttive
      (aggiungono tabelle), ma vanno messe in conto nella finestra.
- [ ] Backup del database **prima** della migrazione (`deploy/backup/`).
- [ ] Verificare che `VFOOT_HEALTH_EMAIL` sia impostato nel `.env` di produzione:
      vuoto significa nessun allarme, che è il default giusto ovunque tranne lì.

## 4. Email

La registrazione via email è già in produzione (`03b099b` la contiene), quindi lo
SMTP Brevo è configurato e il recupero password non porta dipendenze nuove.

- [ ] Verificare comunque che `.env` di produzione abbia `DJANGO_EMAIL_BACKEND`,
      `EMAIL_HOST*` e `DEFAULT_FROM_EMAIL`: **`DEPLOY.md` non le documenta**, e su
      una macchina nuova il recupero fallirebbe senza dire perché.
- [ ] `VFOOT_FRONTEND_BASE_URL` = `https://vfoot.it`, altrimenti il link dentro
      l'email punta altrove.
- [ ] Provare un recupero password vero verso un indirizzo che esiste, una volta.

## 5. PWA, che si collauda solo qui

Dal banco in `http://` l'installazione a schermo intero **non è ottenibile**: su
Android serve un WebAPK, e Chrome lo fa generare a un servizio che deve
raggiungere il manifest da internet. Da un IP di rete degrada a scorciatoia (vedi
`PWA_TESTING.md`).

- [ ] **Disinstallare prima l'app di prova** installata da `http://10.x.x.x:5173`:
      è un'altra origine, quindi un'altra app, con un'altra iscrizione push.
      Tenerle insieme confonde e basta.
- [ ] Installare da `https://vfoot.it` e verificare che si apra **senza barra
      dell'indirizzo** (`pwa-check.html` deve dire *sì* ad «aperta come app
      installata»).
- [ ] Verificare che il bottone «Installa l'app» sparisca da sé.
- [ ] Provare una push vera: `manage.py send_test_push --user <utente>`.
- [ ] Provare l'offline sulla rotta `/home`, che è lo `start_url`.

**Non** è un sintomo da inseguire: l'icona che non compare sulla schermata Home.
Lo decide il launcher Android, non noi, e vale identico per le app del Play Store.

## 6. Il resto del giro

- [ ] Suite completa verde (855 test) sull'ultimo commit che si deploya.
- [ ] `npm run build` e `grep -c "api/v1" dist/sw.js` → deve dire **0**: nessuna
      risposta API nel precache.
- [ ] `npm run test:pwa:offline` sulla build vera.
- [ ] Provare il **secondo** deploy, non il primo: la fascia «È disponibile una
      nuova versione» compare solo quando un worker nuovo trova quello vecchio.
- [ ] Decidere quando togliere il 503 di manutenzione, e con quale preavviso ai
      membri della lega.

---

## Cosa NON è bloccante

Cose vere ma che non tengono chiuso il sito, elencate perché non vengano
riscoperte come sorprese:

- Il WAL su SQLite riguarda solo lo sviluppo: la produzione è PostgreSQL.
- `--lan`, `--owner`, `--cup` e la pagina di diagnosi sono strumenti del banco.
- A dieci richieste simultanee sulla formazione restano ~1,4s: c'è ancora un
  punto caldo oltre a `player_form` e `player_footprints`, ma nessuna pagina apre
  dieci chiamate identiche insieme.
