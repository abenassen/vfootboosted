# Ingestione live: un orologio solo, e un passaggio pesante ogni k

Stato: **FATTO** il 07/08/2026. Piano concordato lo stesso giorno; i riferimenti
`file:riga` qui sotto sono alla revisione `e327d53`, cioè a PRIMA del lavoro, e
restano perché servono a capire da dove si partiva.

Come è andata, in due righe: i numeri misurati sul banco sono quelli previsti
(65 richieste → 26 per l'import, e 4 sul giro leggero), e i voti non si sono
mossi di un millesimo. La verifica delle due cose che il passo 2 lasciava aperte
ha però trovato un terzo fatto che il piano non aveva previsto, e che cambiava il
comportamento in peggio: è scritto in fondo, sotto **Quello che la verifica ha
aggiunto**.

## Il problema

Oggi ci sono **due orologi indipendenti** dentro la stessa finestra live
(`match_scheduler.py:105-118`):

* **live poll**, ogni `VFOOT_LIVE_POLL_MINUTES` (2), timbro `data_checked_at`:
  aggiorna solo stato, punteggio ed eventuale calcio d'inizio
  (`live_ingest.poll_live`, `live_ingest.py:78-88`);
* **live import**, ogni `VFOOT_LIVE_IMPORT_MINUTES` (10), timbro
  `data_imported_at`: import completo per giocatore, cioè i voti
  (`live_ingest._warm_and_import`, `live_ingest.py:90-108`).

Tre conseguenze, tutte misurate:

1. **I due orologi competono.** Il commento in `match_scheduler.py:111-114` lo dice:
   se condividessero il timbro, il poll — scattando cinque volte più spesso —
   continuerebbe a spostare in avanti la scadenza dell'import, che non arriverebbe
   mai. Averli separati risolve quel guaio ma ne lascia un altro: i due passaggi
   falliscono in modo diverso (l'egress può essere bloccato) e ciascuno sposta il
   proprio timbro senza che l'altro lo sappia.
2. **I voti si muovono ogni dieci minuti**, che in produzione è troppo per una
   pagina che si guarda mentre si gioca.
3. **Il passaggio pesante è molto più pesante del necessario.** Vedi sotto.

## Quanto costa oggi, per partita

Da `egress/fetch_worker.py:34-46`:

| | richieste a SofaScore |
|---|---|
| **poll** (`kind="live"`) | **3** — evento (stato+punteggio), `player_stats_records`, `incidents_records` |
| **import** (`kind="final"`) | **~30** — le stesse 3, più `shots_records`, **più una heatmap per ogni giocatore con minuti > 0** (~22), **più `warm_schedule`** (stagioni → turni → eventi di ogni turno) |

Il rapporto è un ordine di grandezza. In Serie A le partite in contemporanea sono
2-3, non dieci: il traffico assoluto non è drammatico, ma il rapporto è la ragione
per cui i due passaggi sono separati, e la storia degli IP bruciati dice di non
sprecarlo.

Due sprechi identificati dentro quelle ~30:

* **`warm_schedule` a ogni import live.** Non serve il calendario: serve *trovare*
  la partita. L'importer la risolve a partire dall'elenco eventi invece che
  dall'id — è scritto in `live_ingest.py:91-96`, ed è la stessa trappola che
  AGENTS.md segnala già ("l'importer salta tutto ciò che lo schedule non chiama
  finished"). A partita in corso l'indirizzo lo conosciamo: `match.external_id`.
* **Le heatmap a metà partita.** Il commento in `fetch_worker.py:35-37` dice che
  hanno senso *solo a partita finita*, e `import_live` le scarica lo stesso perché
  usa `kind="final"`.

## Il voto puro ha davvero bisogno delle heatmap?

**Quasi mai.** `classic_rating._features` (`classic_rating.py:1199-1206`) somma
`PlayerZoneFeature` **su tutte le zone** (`annotate(v=Sum("value"))`, il commento
dice "total_over_zones"): la somma su tutte le zone di uno stat distribuito è lo
stat aggregato di partenza, quindi per il grosso del modello la heatmap si
semplifica e i dati veri sono gli stessi `player_stats_records` che il poll
leggero **già scarica ogni due minuti**.

L'eccezione è una: `_zone_presence` (`classic_rating.py:1351-1370`) la heatmap la
usa davvero e la ricostruisce — è la misura POSIZIONALE con cui si addebita il
pericolo concesso, cioè il termine di **esposizione difensiva**.

Manca anche il dettaglio degli esiti dei tiri (`shots_goal`/`post`/`blocked`, vedi
`SHOT_TYPE_TO_FEATURE` in `classic_rating.py:361`), che viene da `shots_records`:
**una** richiesta, non ventidue.

### L'ostacolo, e dov'è

`sofascore_adapter.py:570-572`:

```python
if total == 0:      # nessun punto heatmap per questo giocatore
    no_heatmap += 1
    continue        # esce dal giro: NESSUNA riga scritta per lui
```

Senza heatmap l'adapter non scrive nulla, **nemmeno i totali**. Non è che le zone
vengano approssimate: non esistono, e il voto puro non trova niente da sommare. È
questa riga a rendere oggi impossibile un voto da dati leggeri.

## Il disegno

**Un orologio solo.** Il passaggio leggero detta la cadenza; ogni k-esimo giro
porta con sé anche quello pesante. Sparisce la competizione fra due timbri, e la
regola diventa leggibile: "ogni 2 minuti i voti, ogni 8 anche le zone".

    poll leggero   ██ ██ ██ ██ ██ ██ ██ ██
    passo pesante  ██          ██          ██        (ogni k)

Il contatore avanza sul passaggio **leggero**; quello pesante è un flag: se
l'egress lo blocca, si ritenta al giro dopo senza perdere il leggero.

**Due manopole, di natura diversa, e la distinzione conta.**

* il **tempo** — ogni quanto scatta il giro leggero (`VFOOT_LIVE_POLL_MINUTES`);
* la **forma** — k, quanti giri leggeri per un pesante.

Il tempo dice quanto in fretta scorre; k dice com'è fatto il comportamento. Serve
a tenerle separate soprattutto per il banco di prova: vedi 3-bis.

k si può esprimere come multiplo dell'intervallo del poll (`k *
live_poll_interval()` confrontato con `data_imported_at`) senza aggiungere una
colonna contatore. Il compromesso: se un giro leggero salta perché l'egress è
bloccato, il pesante scatta lo stesso a tempo invece di seguire i giri
effettivamente fatti. Con un contatore vero su `Match` seguirebbe i giri; da
decidere in fase di scrittura, l'effetto pratico è piccolo.

## I passi, nell'ordine

### 1. Import live per id, senza `warm_schedule`

Percorso di import che risolve la partita dal suo `external_id` invece che
dall'elenco eventi. Si torna al calendario **solo se la risoluzione fallisce**
(l'indirizzo è statico, ma può cambiare: il fallback è la rete di sicurezza, non
la strada maestra).

Indipendente da tutto il resto: si può fare e verificare da solo.

*Tocca*: `live_ingest.py:90-108`, l'importer (`import_sofascore` /
`sofascore_adapter`).

### 2. Totali anche senza heatmap

Far scrivere le feature di un giocatore senza punti heatmap in una zona
**degenere** invece di scartarlo. Siccome `_features` somma su tutte le zone, i
totali restano corretti qualunque sia la distribuzione.

Due cose da sorvegliare, entrambe verificabili:

* **aura non deve leggere le righe degeneri** — un giocatore tutto ammassato in una
  casella falserebbe i duelli di zona. C'è già un campo `method` sulle righe
  (`_upsert_zone_features`, `sofascore_adapter.py:680`) che serve a marcarne la
  provenienza: usarlo per distinguerle;
* **il passaggio pesante deve sovrascriverle** — l'import cancella e riscrive le
  zone, quindi al primo giro completo dovrebbero sparire da sole. Da confermare.

*Tocca*: `sofascore_adapter.py:570-572` e il percorso di scrittura zone.

### 3. Un solo orologio

Sparisce `VFOOT_LIVE_IMPORT_MINUTES`; resta la cadenza del poll più un
**moltiplicatore** (es. `VFOOT_LIVE_HEAVY_EVERY=4`). Il pianificatore smette di
avere due rami dentro `_in_live_window` e ne ha uno con un flag.

*Tocca*: `match_scheduler.py:36-51` e `105-118`, `tick.py:100-128`,
`config/settings.py:218,226`, e `vfoot-sim:238` — vedi 3-bis, che non è una
rifinitura successiva.

*Test da aggiornare*: `realdata/tests_calendar_scheduler.py` (13 riferimenti,
inclusi quattro `@override_settings(VFOOT_LIVE_IMPORT_MINUTES=10)` alle righe
308-326) e `realdata/tests_live_pipeline.py` (2).

### 3-bis. `vfoot-sim` va cambiato nello stesso passo, non dopo

Lo script esporta oggi `VFOOT_LIVE_IMPORT_MINUTES=2` (`vfoot-sim:238`). Due
ragioni per cui non è una riga da aggiornare con calma:

* **Se la variabile sparisce da `settings.py` e resta nello script, l'export
  diventa un no-op silenzioso.** (Motivo in più per toglierla del tutto: vedi la
  regola qui sotto.) Il banco girerebbe alla cadenza di produzione
  mentre il commento sopra la riga continua a promettere due minuti: esattamente la
  classe di guaio che questo documento esiste per non ripetere (un ambiente che
  sembra giusto e non lo è, senza un errore da nessuna parte).
* **Il banco deve conservare la FORMA, non appiattirla.** Oggi import = poll = 2
  minuti, cioè k=1: nel banco *ogni* giro leggero è anche pesante, e la
  distinzione fra i due semplicemente non esiste. Un banco a k=1 non potrebbe
  mostrare l'unico comportamento nuovo che ci interessa — il voto provvisorio
  senza esposizione difensiva che si assesta al giro pesante: nasconderebbe
  proprio il rischio che abbiamo deciso di accettare.

**La regola: di default il banco è IDENTICO alla produzione — stesso k e stesso
tempo. L'accelerazione resta possibile, ma va chiesta.**

Non è pignoleria: un banco che di default differisce dal prodotto mente di
default, e chi ci guarda dentro non ha modo di sapere che sta misurando un'altra
cosa. È esattamente il guaio che è costato un'ora il 07/08/2026, e sparisce solo
se i due coincidono finché qualcuno non dice il contrario. Chiedere di accelerare
è una riga sulla riga di comando — e in quel momento si SA di guardare qualcosa
di più veloce del vero:

    VFOOT_LIVE_POLL_MINUTES=1 ./vfoot-sim napoli-inter

(lo script usa già il costrutto `${VAR:-default}`, quindi un valore esportato da
fuori vince; basta che lo script non ne imponga uno suo.)

Il default è sostenibile perché **con lo schema nuovo non c'è più niente di lento
da aspettare**. La ragione per cui l'override esiste è scritta sopra quella riga —
*"aspettare dieci minuti per vedere muovere un voto rende impossibile capire se la
cosa funziona o si è rotta"* — e riguarda i voti, che ora si muovono sul giro
**leggero**: già ogni due minuti in produzione. Per un test del WebSocket, dei
voti live, delle notifiche, due minuti bastano e avanzano. Resta lungo solo il
giro pesante (8' con k=4), e serve aspettarlo solo quando si sta guardando
proprio quello: le zone, aura, il rientro dell'esposizione difensiva. Per quel
caso — e solo per quello — si accelera a mano.

Quindi al passo 3 la riga `vfoot-sim:238` non va aggiornata: va **tolta**.

Il pavimento del banco non è la cortesia verso SofaScore (con
`VFOOT_EGRESS_SIMULATED` non esce nulla in rete) ma due cose interne: la cadenza
del tick (`VFOOT_TICK_EVERY`, 60s nello script) e la risoluzione al minuto del
generatore (`season_simulator.status_at`) — sotto il minuto due giri consecutivi
leggono lo stesso identico stato.

Regola generale che ne discende, e che vale oltre questo caso: **quando una
manopola cambia nome o sparisce, l'override del banco va cambiato nello stesso
commit.** Un banco che diverge dal prodotto non è un banco più comodo, è un banco
che mente.

## Deciso di NON fare

**Il passaggio pesante innescato dal gol.** Era il punto 4 della proposta ed è
stato tolto: una volta che il passaggio leggero aggiorna i voti, il gol è già
intercettato lì. Legarci anche le zone significherebbe far arrivare al tick i
campi cambiati dal poll (`_apply_status` li restituisce già,
`live_ingest.py:51-75`, ma `poll_live` li butta via) per anticipare di qualche
minuto un termine — l'esposizione difensiva — che dai gol non dipende. Entro il
giro pesante il voto diventa comunque la stima migliore possibile con i dati
disponibili, e va bene così.

## Il rischio da dichiarare

**Il voto live senza esposizione difensiva non è il voto finale.** Al primo
passaggio pesante i difensori si muovono, e in una direzione sistematica:
l'esposizione è quasi sempre un malus, quindi in live risulteranno un po'
generosi. Va bene finché è dichiarato — il badge "provvisorio" c'è già — ma è un
movimento che i manager vedranno, e conviene deciderlo prima, non scoprirlo in
campo. Se dà fastidio, l'alternativa è tenere il voto dei soli difensori sulla
cadenza pesante.

*(Aggiornato dopo la scrittura: il riporto della distribuzione — vedi in fondo —
riduce questo caso a chi non ha ancora un passaggio pesante alle spalle, cioè al
subentrato entrato da meno di otto minuti.)*

## Come si verifica

Con **`./vfoot-sim`**, non con `./vfoot-dev` più variabili a mano: è l'unico che
accende Redis (senza, la spinta WebSocket dopo un import muore nel processo del
cron e alla pagina non arriva, senza errori). Vedi AGENTS.md, sezione Dev Notes.

    ./vfoot-sim build napoli-inter
    ./vfoot-sim napoli-inter
    tail -f $TMPDIR/vfoot-sim/tick.log

Il conto delle richieste NON si legge dal log dell'egress: con
`VFOOT_EGRESS_SIMULATED` non esce niente in rete e nessuno lo scrive. Si conta
dove le richieste esistono davvero, cioè agli endpoint che l'import tocca —
`SofaScoreClient.get`, uno per endpoint, che a cache fredda è esattamente quello
che il fetch worker chiederebbe. È quello che fa
`realdata/tests_import_by_id.py`, che il conto lo fissa invece di guardarlo: un
numero misurato a mano decade in silenzio appena il codice si sposta.

Sul banco, un import di Napoli-Inter al 31/01/2027 21:15, partendo due volte
dalla stessa istantanea e a orologio bloccato:

| | prima | dopo |
|---|---|---|
| richieste per import | 65 | **26** |
| di cui calendario | 40 | **0** |
| giri di egress | 2 | **1** |
| righe di zona scritte | 2306 | 2306 |
| voti puri diversi | — | **0 su 22** |

## Quello che la verifica ha aggiunto

Le due cose che il passo 2 lasciava aperte sono state provate sui dati veri prima
di scrivere, e la risposta alla seconda ne ha tirata fuori una terza.

**Aura legge le righe degeneri?** Sì. `realdata_scoring` non filtrava niente:
inserita una riga tutta ammassata in una casella, la presenza del giocatore
passava da 3 zone a 4. E non era il solo lettore posizionale — anche
l'esposizione difensiva (`classic_rating._zone_presence`) la leggeva, e collassava
la presenza a `{(0,0): 1.0}`, cioè addebitava al giocatore il pericolo concesso in
una zona scelta a caso. Il filtro è quindi su **quattro** lettori, non su uno:
aura, l'esposizione, l'inferenza dei ruoli e l'impronta del giocatore.

**Il passaggio pesante le sovrascrive?** Sì: `_upsert_zone_features` cancella le
chiavi che smettono di arrivare, e dopo un giro completo di Z_NA non resta niente.

**La cosa non prevista.** Quella cancellazione vale nei DUE sensi. Un giro leggero
che scrivesse tutti come non collocati cancellerebbe le zone che il pesante aveva
appena misurato: l'esposizione difensiva sparirebbe e tornerebbe ogni k giri, e
il voto di ogni difensore oscillerebbe a dente di sega ogni due minuti — peggio
del rischio che questo documento dichiarava di accettare, che era uno spostamento
in una direzione sola.

Rimedio, ed è la ragione per cui il passo 2 è un po' più di quanto scritto sopra:
il giro leggero **riporta la distribuzione dell'ultimo giro pesante** invece di
buttarla. La zona degenere resta, ma per il caso che è davvero degenere — il
subentrato entrato dopo l'ultimo pesante, e il primo giro se il pesante era stato
bloccato. Il primo giro di ogni partita è pesante per costruzione
(`data_imported_at` è nullo), quindi in pratica quasi nessuno passa da lì.

Il rischio dichiarato più sopra resta vero, ma vale per meno gente di quanto
sembrasse: non "i difensori in live", ma "chi è entrato da meno di otto minuti".
