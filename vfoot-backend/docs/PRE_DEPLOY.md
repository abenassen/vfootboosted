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

## 2. Confrontare i nostri ruoli col listone Fantacalcio 2026-27

Abbiamo un riferimento esterno per la **prossima** stagione:
`Quotazioni_Fantacalcio_Stagione_2026_27.xlsx` in radice — 497 giocatori, 20
squadre, colonna `R` col ruolo classico e `RM` col ruolo Mantra.

```
R  : P 60 · D 176 · C 174 · A 87
RM : Por, Dc, Dd, Ds, B, E, M, C, T, W, A, Pc (anche multipli, es. "Dd;E")
```

È l'occasione di misurare quanto la nostra inferenza si discosta da ciò che i
fantallenatori si aspettano.

- [ ] Agganciare i nomi. Il foglio usa **cognome-prima con iniziale puntata**
      («Martinez Jo.»), quindi vale il metodo già rodato: indicizzare su
      `MatchAppearance` (chi ha davvero giocato per quella squadra), gestire le
      traslitterazioni, e tenere da parte i non agganciati invece di buttarli.
- [ ] Confrontare `R` con il nostro **`CurrentPlayerRole`** (layer 2, quello che
      segna — non `classic_role_seed`, che è solo il seme Transfermarkt).
- [ ] Produrre la matrice di confusione 4×4 e, soprattutto, **l'elenco nominale
      dei disaccordi**: un numero aggregato non dice se sbagliamo sui panchinari
      o sugli attaccanti che tutti conoscono.
- [ ] Guardare i casi ambigui con `RM` multiplo (`Dd;E`, `W;A`, `C;T`): lì il
      disaccordo con `R` è atteso e non è un nostro errore — è la ragione per cui
      il Mantra esiste.

**Nota**: il foglio è della stagione **2026-27**, che per noi è la stagione di
riferimento simulata. Un disaccordo può voler dire che sbagliamo noi, oppure che
il listone anticipa un ruolo che il campo non ha ancora confermato.

## 3. Migrazione e dati

- [ ] **`0022_jobrun`** è una migrazione nuova: va applicata in produzione. Non è
      distruttiva (aggiunge una tabella), ma va messa in conto nella finestra.
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
