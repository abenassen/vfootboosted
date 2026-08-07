# Ingestione live: un orologio solo, e un passaggio pesante ogni k

Stato: **da fare**. Piano concordato il 07/08/2026, scritto per essere eseguito da
contesto pulito. Tutti i fatti qui sotto sono stati verificati sul codice; i
riferimenti sono `file:riga` alla revisione `e327d53`.

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
`config/settings.py:218,226`, `vfoot-sim:238` (che oggi esporta
`VFOOT_LIVE_IMPORT_MINUTES=2`).

*Test da aggiornare*: `realdata/tests_calendar_scheduler.py` (13 riferimenti,
inclusi quattro `@override_settings(VFOOT_LIVE_IMPORT_MINUTES=10)` alle righe
308-326) e `realdata/tests_live_pipeline.py` (2).

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

## Come si verifica

Con **`./vfoot-sim`**, non con `./vfoot-dev` più variabili a mano: è l'unico che
accende Redis (senza, la spinta WebSocket dopo un import muore nel processo del
cron e alla pagina non arriva, senza errori) e che mette la cadenza del banco di
prova. Vedi AGENTS.md, sezione Dev Notes.

    ./vfoot-sim build napoli-inter
    ./vfoot-sim napoli-inter
    tail -f $TMPDIR/vfoot-sim/tick.log

Il conto delle richieste per giro si legge dal log dell'egress: è il numero che
questo lavoro deve far scendere da ~30 a ~4 sul passaggio leggero.
