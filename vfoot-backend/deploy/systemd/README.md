# I job schedulati del server (Linode)

**Questo file è l'inventario**: tutto ciò che gira da solo in produzione sta qui.
Un job che non è in questa tabella non esiste — e un job che esiste solo nella
testa di qualcuno è un job che, il giorno che smette di girare, nessuno cerca.

Sono unità systemd, non righe di crontab. La differenza che conta: `Persistent=true`
recupera un'esecuzione saltata mentre il server era spento (cron la perde e basta),
`RandomizedDelaySec` evita di bussare a un sito esterno allo stesso secondo ogni
giorno, e il log finisce nel journal insieme al resto (`journalctl -u vfoot-tick`)
invece che in una mail a root che nessuno legge.

Convenzione: `Type=oneshot` mosso da un timer, `User=vfoot` (tranne dove serve
root, indicato sotto), `WorkingDirectory=/srv/vfoot-app/vfoot-backend/src`,
interprete dal venv del backend. Le unità vive stanno in `/etc/systemd/system/`;
questi file ne sono la copia versionata. L'ambiente (DB, SMTP, VAPID) arriva da
`/srv/vfoot-app/.env`, che `config/settings.py` carica da sé: nessun
`EnvironmentFile` nelle unità.

## Inventario

| unità | cadenza | comando | cosa si rompe se non gira |
|---|---|---|---|
| `vfoot-tick` | ogni minuto | `tick` | i risultati reali non entrano mai: niente live, niente `data_ready`, quindi nessuna giornata concludibile |
| `vfoot-calendar` | ogni ora, ma decide da sé | `sync_calendar --egress --if-due --auto-rounds` | orari e rinvii restano quelli vecchi: le formazioni si bloccano all'ora sbagliata |
| `vfoot-tm-poll` | 04 e 13 UTC | `poll_transfermarkt` | il listone invecchia: i trasferimenti non compaiono |
| `vfoot-egress-refill` | 03/09/15/21 | `sofascore_egress.py refill` ×2 | i pool di IP si esauriscono e SofaScore/TM tornano a bloccarci (**root**) |
| `vfoot-market` | ogni 90 s | `market_tick` | il mercato resta corretto ma **muto**: nessuno viene avvisato di una chiusura o di un sorpasso |
| `vfoot-nudge` | 10:00 | `nudge_conclusions` | l'admin distratto non viene mai richiamato: classifica ferma finché non se ne accorge da solo |
| `vfoot-backup` | 03:15 | `/usr/local/sbin/vfoot-backup` | **nessuna copia dei dati** fra un deploy e l'altro (**root**) |
| `vfoot-health` | 07:30 | `health_report --mail --prune` | nessuno si accorge che uno degli altri sette ha smesso di girare, o che gira e non riporta piu' niente |
| `vfoot-agent` | ogni ora, ma decide da sé | `maintenance_run` | niente diagnosi automatica: il guasto lo scopri lo stesso dalla mail, ma lo capisci e lo correggi tu |
| `vfoot-maintenance` | ogni 5 min | `maintenance_tick` | le proposte che hai approvato non vengono mai eseguite |

Fuori da questa tabella, ma schedulato lo stesso: il rinnovo dei certificati TLS,
che è il timer di sistema `certbot.timer` (vedi `DEPLOY.md`) — di nostro non ha
niente, ma se un giorno il sito diventa irraggiungibile in HTTPS, si guarda lì.

### Il backup è ancora mezzo backup

`vfoot-backup` scrive in `/root/backups`, cioè **sullo stesso disco della cosa che
sta salvando**. Protegge da quello che succede più spesso — una migrazione andata
male, una cancellazione, un deploy da rifare — e non protegge per niente dal caso
in cui si perde il Linode. Perché sia un backup vero manca una copia fuori dal
server (S3/Backblaze, o anche solo un `rsync` notturno verso casa). È una
decisione aperta, non una dimenticanza.

### Perché il calendario ha una cadenza che non si legge nel timer

È l'unico job la cui frequenza **non** sta nel suo `.timer`: quello scatta ogni
ora e basta, e a decidere è `--if-due`. Il motivo è che non esiste un insieme di
"giorni di gara" da scrivere in un `OnCalendar` — la Serie A gioca dal venerdì al
lunedì più gli infrasettimanali, e l'unica cosa che sa quando si gioca è il
calendario stesso, cioè proprio ciò che il job aggiorna. Un'unità con dentro i
giorni sarebbe vera per una settimana e poi falsa senza dirlo.

Le due cadenze stanno in `settings.py` (tararle non tocca le unità):

* **pavimento** `VFOOT_CALENDAR_SYNC_MINUTES` (6h) — il massimo che il calendario
  può restare non letto, comunque vadano le cose. È la rete che prende una
  partita comparsa in un giorno che il calendario che abbiamo dice vuoto;
* **denso** `VFOOT_CALENDAR_MATCHDAY_MINUTES` (1h) — quando c'è un calcio
  d'inizio *in vista*.

«In vista» sono due cose, e la seconda è quella che si dimentica (costanti in
`calendar_sync.py`):

1. **uno sta arrivando**, entro `DENSE_BEFORE_KICKOFF` — **diciotto ore**, cioè
   una durata, non le 18:00. Sembra tanto ed è voluto: la densità la decide il
   calendario che stiamo aggiornando, quindi una finestra stretta ancorata
   all'orario che *crediamo* sarebbe fitta nel momento sbagliato se quell'orario
   si fosse spostato **prima**. E quella è la direzione pericolosa, perché il
   blocco delle formazioni legge `Match.kickoff` e lascerebbe schierare a palla
   che rotola. Diciotto ore non è una finestra sull'orologio: è un margine di
   sfiducia sul dato che possediamo;
2. **uno sarebbe dovuto cominciare e non risulta cominciato**, entro
   `DENSE_AFTER_MISSED_KICKOFF` (6h). Una partita che alle 21 crediamo iniziata
   alle 20 ed è ancora `scheduled` o `postponed` o sta partendo adesso (e il tick
   lo dirà entro un paio di minuti) o il nostro calendario è sbagliato — ed è il
   momento di guardare, non di tacere. Senza questo ramo, un rinvio per maltempo
   annunciato **subito dopo** una passata resta invisibile fino al pavimento, sei
   ore dopo: la partita ricomincia alle 22 e noi non lo sappiamo.

Costo: **6 richieste a passata invece di ~40**, perché `--auto-rounds` guarda solo
il turno prossimo e i successivi quattro (più i turni arretrati che devono ancora
una partita), e il restringimento arriva fino al lato che *scarica* — limitare solo
la lettura offline non toglierebbe una singola richiesta.

| | passate | richieste |
|---|---|---|
| giorno vuoto (solo pavimento) | 4 | 24 |
| giorno di gara (ogni ora) | ~20 | ~120 |
| **prima**, tutti i giorni uguali | 4 | 160 |

Cioè costa **meno di prima anche nel giorno di gara**, e sull'anno gira intorno a
~60 richieste al giorno contro 160. Il denso non è stato comprato: è avanzato.

### L'agente propone, l'esecutore fa — e sono due unità apposta

`vfoot-agent` e `vfoot-maintenance` sono lo stesso lavoro spezzato in due, e la
spaccatura è il presidio, non un dettaglio di packaging.

**`vfoot-agent` gira come `vfoot` senza sudo**: legge, cerca, fa girare i test, crea
un branch sotto `fix/`. Non riavvia niente, non applica niente, non ha una voce in
`/etc/sudoers.d`. Scrive una *proposta*, il cui `kind` viene da un insieme chiuso.

**`vfoot-maintenance` è codice normale**, nessun modello coinvolto: rilegge la
proposta, la **rivalida da capo** contro le liste in
`realdata/services/maintenance.py`, e solo allora attraversa il ponte sudo
`/usr/local/sbin/vfoot-maintenance` — che a sua volta ricontrolla tutto una seconda
volta, in shell.

Due cancelli indipendenti, in due linguaggi, perché l'ingresso dell'agente contiene
messaggi d'errore che vengono dai siti che scrapiamo: nessuna frase in un prompt può
essere l'ultima difesa. Un modello completamente dirottato può, al massimo, proporre
una delle cinque cose dell'insieme — e per tre di quelle serve comunque il tuo sì.

Esiste anche un'unità separata perché **l'approvazione arriva ore dopo la proposta**:
leggi la mail a colazione, o premi il bottone da una spiaggia, e a quel punto il
processo dell'agente è morto da un pezzo. Qualcosa di vivo su un timer deve essere la
cosa che agisce.

Perché il timer dell'agente scatta ogni ora ma non costa niente: `maintenance_run`
guarda il verdetto e, se è verde, esce prima di aprire il portafoglio — stessa forma
di `sync_calendar --if-due`. **A svegliarlo è il verdetto rosso, non l'orologio**: un
agente che ogni mattina legge dati sani è un agente che prima o poi ti rassicura
sulla mattina sbagliata.

Il livello automatico (`VFOOT_MAINTENANCE_AUTO`) **parte spento**: finché è spento
ogni proposta aspetta un umano, che è tutto il senso del rodaggio. E `apply_patch`
non entra nel livello automatico a nessuna impostazione, mai.

Da terminale, durante il rodaggio:

```sh
manage.py maintenance_review              # cosa aspetta un sì
manage.py maintenance_review --show 12    # una proposta per intero, col diff
manage.py maintenance_review --approve 12 # la esegue il prossimo tick
manage.py maintenance_review --reject 12 --why "sbagliato il nome"
```

Un rifiuto non è solo un no: l'impronta torna all'agente alla passata successiva, e
la stessa idea non si ripresenta domani mattina.

### Le due dipendenze da conoscere

`vfoot-tick` e `vfoot-calendar` escono verso SofaScore attraverso il ponte sudo
`/usr/local/sbin/vfoot-egress`: **accesi senza quello fallirebbero a ogni scatto**.
L'installer se ne accorge e li salta invece di riempire il journal di errori.
Gli altri cinque non dipendono da niente e si possono accendere quando si vuole.

`vfoot-market` e `vfoot-nudge` mandano email e push: senza le credenziali Brevo e
le chiavi VAPID nel `.env` non falliscono — semplicemente non notificano nulla, il
che è peggio, perché sembra che funzionino. Verificarlo al primo giro.

## Installare e accendere

```sh
# sul server, come root, dal checkout
cd /srv/vfoot-app/vfoot-backend/deploy/systemd

./install.sh --dry-run          # cosa farebbe
./install.sh                    # copia unità + script di backup, daemon-reload, NON accende
./install.sh --status           # cosa è acceso e quando scatta il prossimo
```

Installare **non** accende: è la postura con cui il server sta oggi, tutto pronto
e spento. Accendere è un gesto separato:

```sh
./install.sh --enable tm-poll --enable backup    # uno alla volta
./install.sh --enable-all                        # go-live
```

### Prima di accendere un job nuovo

Ognuno di questi si può provare a mano, e conviene farlo: un comando che gira ogni
minuto e sbaglia, sbaglia 1440 volte al giorno.

```sh
sudo -u vfoot /srv/vfoot-app/vfoot-backend/.venv/bin/python \
  /srv/vfoot-app/vfoot-backend/src/manage.py poll_transfermarkt --dry-run
sudo -u vfoot ... manage.py tick --dry-run
sudo -u vfoot ... manage.py market_tick --dry-run
sudo -u vfoot ... manage.py nudge_conclusions --dry-run
sudo -u vfoot ... manage.py health_report        # legge e basta, non muta niente
/usr/local/sbin/vfoot-backup --dry-run
```

`sync_calendar` non ha un `--dry-run`, ma ha `--offline`, che gli fa leggere solo
la cache già scaricata.

`poll_transfermarkt` è idempotente e ha tre presidi per l'esecuzione non
presidiata: scrape sempre fresco (mai cache vecchia), stagione TM derivata dalla
`CompetitionSeason` (non possono divergere), e rifiuto sia delle partenze quando
lo scrape è incompleto sia delle mappature-club sotto soglia (`--min-map-score`).

## Aggiungere un job

Tre cose, nessuna delle quali opzionale:

1. i due file `vfoot-<nome>.{service,timer}` qui dentro;
2. il nome in `ALL_UNITS` dentro `install.sh`;
3. **una riga nella tabella qui sopra**, con la colonna "cosa si rompe" compilata
   davvero — se non si riesce a scriverla, vale la pena chiedersi se il job serve.

## Quando qualcosa non torna

```sh
python manage.py health_report         # il verdetto: cosa è rotto e perché
systemctl list-timers 'vfoot-*'        # quando ha girato, quando rigira
journalctl -u vfoot-tick --since today # cosa ha detto
systemctl status vfoot-backup.service  # l'ultimo esito
```

Un `oneshot` che fallisce **non** ferma il timer: riproverà allo scatto successivo.
Comodo per un errore passeggero (rete giù), infido per uno permanente — che resta
a fallire in silenzio finché qualcuno non guarda. `vfoot-health` è quel qualcuno:
guarda ogni mattina e scrive solo se c'è da scrivere.

## Il registro delle esecuzioni, e perché non basta il journal

Ogni job lascia una riga in `JobRun` (tabella `realdata_jobrun`): quando è partito,
quanto è durato, com'è finito, e **due dizionari** — `due`, cioè quello che doveva
fare, e `did`, cioè i numeri che ha portato a casa.

I due insieme sono il punto. Il journal racconta bene una storia a un umano, e non
sa distinguere le due righe che contano davvero:

* un tick che non ha importato niente **perché non c'era niente da importare** —
  mille volte al giorno, la normalità;
* un tick che non ha importato niente **mentre c'erano tre partite in corso** —
  l'egress a terra, e nessuno che se ne accorga fino a lunedì.

Nel journal sono identiche. Nel registro, la prima ha `due` vuoto e la seconda no.
Tutto ciò che `health_report` sa dire poggia su questa differenza.

Il registro serve anche a prendere il guasto che **non somiglia a un guasto**: una
pagina che risponde ancora e non contiene più quello che leggevamo. Il comando esce
0, il journal dice «applied», e l'unico segno è un numero che si dimezza. Il
controllo `*-collapsed` confronta l'ultima passata con la **mediana delle
precedenti** — mai con una soglia fissa, perché il valore giusto per «giocatori
visti dal polling Transfermarkt» è quello della settimana scorsa, e nessuna costante
scritta oggi sopravvive a una stagione.

Volume: il tick scrive ~1440 righe al giorno. `--prune` (che `vfoot-health` fa da
sé) tiene 14 giorni le righe tranquille e 90 quelle che sono servite a qualcosa.

## Il canarino sulla forma del dato

`health_report` guarda anche i **byte** che l'egress ha appena scaricato, e chiede
una cosa che l'importatore non può chiedere a sé stesso: le colonne su cui è
costruito il voto puro ci sono ancora?

È il presidio contro il guasto peggiore di tutti. SofaScore rinomina `duelWon` un
martedì: la richiesta riesce, il JSON si legge, `.get("duelWon")` torna `None`, e in
banca dati entra una stagione di giocatori senza duelli — con il voto puro, che è
una somma pesata, che scivola verso il 6.0 per tutti. Nessun codice d'uscita lo
vede, e nemmeno la suite di test, che gira su dati registrati col nome vecchio.

Le soglie sono **misurate**, non scelte: sulle 600 partite di Serie A in
`historical-data/`, 31 colonne compaiono in almeno il 99,5% delle partite, e
nell'unione di due partite consecutive ci sono tutte e 31 in **599 finestre su
599**. Per questo il canarino chiede due partite e non una (quattro partite su 600
ne perdono una per puro caso), e per questo le quattordici colonne rare —
`penaltySave` c'è nel 6% delle partite — sono deliberatamente fuori: la loro assenza
è calcio, non un guasto.

Quando una colonna sparisce, il rapporto la nomina, e nella riga sotto elenca le
colonne **mai viste prima**. Se lo stesso giorno sparisce `duelWon` e compare
`duelsWon`, non è una perdita: è un cambio di nome, e si sa già cosa correggere
(`DISTRIBUTED_STAT_MAP` in `realdata/services/sofascore_adapter.py`).
