# Voti live durante la giornata — piano di lavoro

Stato: **da fare**, punti 1→6. Deciso in una sessione del 2026-08-02; questo
documento e' autosufficiente, non serve aver visto quella conversazione.

## Il buco che chiude

Una partita reale in corso oggi porta in banca dati **solo stato e punteggio**:
`live_ingest.poll_live` aggiorna il ciclo di vita e i gol, i dati per giocatore
arrivano soltanto alla finalizzazione (+15 min dal fischio finale). Di conseguenza
il dettaglio di una partita di lega non esiste finche' l'admin non conclude la
giornata: `FixtureDetailView` serve `fixture.detail.payload` **verbatim** e
risponde 404 `"No rich detail for this fixture."` prima di allora.

Verificato: le tre partite di g22 di una squadra (campionato, coppa, mundial)
rispondono tutte 404 mentre la giornata e' in corso, e nella home non compaiono in
nessuna sezione (vedi punto 6).

Obiettivo: **seguire la propria giornata mentre si gioca**, con i voti che si
aggiornano e con l'indicazione di quali sono ancora provvisori.

## Decisioni gia' prese (non ridiscuterle senza motivo)

* **`data_ready` E' il marcatore di instabilita'.** Significa gia' "il provider ha
  smesso di cambiare questa partita", non "e' finita". Un voto e' instabile se la
  partita reale da cui viene ha `data_ready=False`. **Non aggiungere un secondo
  flag** da tenere in sincronia.
* **WebSocket, non polling.** Il polling regge oggi solo perche' lo scraping gira
  ogni 2 minuti — proprieta' temporanea. Con un provider vero cade, e il costo del
  polling cresce con utenti x frequenza mentre quello del socket cresce con i soli
  cambiamenti reali.
* **Il canale dell'asta e' riusabile.** `AuctionConsumer` e' gia' *read-only* e
  manda una spinta leggera `{"type":"update"}`, non i dati: il client poi rilegge
  via REST. E' il pattern giusto anche qui. Di specifico dell'asta ci sono solo il
  nome del gruppo e il predicato di autorizzazione. Aste e giornate live non
  coesistono mai, quindi il layer non porta i due carichi insieme.
* **Il push resta, per il momento opposto.** Serve a raggiungere chi lo ha
  autorizzato **ad app chiusa**; non e' il canale per pilotare una pagina aperta
  (payload di pochi kB, nessuna garanzia di latenza o ordine, permesso di sistema).
  Eventi concordati: **gol di un tuo giocatore, espulsione, conclusione della
  giornata**. Lista estendibile in futuro.
* **Il punteggio reale non e' l'informazione che interessa** all'utente: conta il
  voto. Il poll leggero `/event/{id}` resta comunque, ma la sua ragione e' un'altra
  — e' cio' che fa vedere allo scheduler il passaggio scheduled → live → finished,
  da cui partono le finestre di finalizzazione.

## Contesto sui dati, per non rifare i conti

* `PlayerZoneFeature` e' in **formato lungo**: una riga per (giocatore, zona,
  feature). ~155 righe a giocatore, ~4.800 a partita, ~14.000 per ciclo con 2-3
  partite in contemporanea (in Serie A e' raro averne 10).
* Il **voto puro somma via la zona**: `classic_rating._per_match_player_totals` fa
  `values(...).annotate(Sum("value"))` per feature. Le 155 righe collassano in ~27
  numeri. Le zone servono ai duelli della modalita' Aura e all'esposizione
  difensiva, non al fantavoto classico.
  → Se il costo di scrittura live diventasse un problema **vero**, e' qui che si
  guarda (una tabella di totali per giocatore/feature), molto prima di ottimizzare
  ulteriormente l'upsert.

---

## 1. Import live dei dati per giocatore

**File**: `realdata/services/live_ingest.py`, `realdata/services/match_scheduler.py`,
`realdata/management/commands/tick.py`, migrazione su `realdata`.

Oggi `poll_live` fa: `egress_client.warm_matches([id], "live")` → legge il
`/event/{id}` dalla cache → `_apply_status`. `finalize` fa: `warm_schedule(year)` →
`warm_matches([id], "final")` → `ingest_sofascore_season(scraper=client, year=year,
match_ids=[int(id)])`.

Aggiungere una terza azione, `live_import`, che e' `finalize` **senza** promozione:

```python
def import_live(match) -> bool:
    """Come finalize, ma la partita resta instabile: data_ready NON si alza."""
    # stesso corpo di finalize(), con only_finished=False
```

Attenzione: `ingest_sofascore_season` risolve la partita **dallo schedule** e salta
tutto cio' che lo schedule non chiama `finished`. Quindi serve
`only_finished=False`, e il file del turno in cache dev'essere aggiornato (per il
provider simulato lo fa gia' `egress_sim._refresh_round_entry`).

Cadenza propria, piu' lenta del poll leggero:

* nuova costante in settings: `VFOOT_LIVE_IMPORT_MINUTES` (default **10**). Un voto
  che si muove ogni dieci minuti e' il ritmo con cui cambia davvero una
  prestazione, e divide per cinque la scrittura rispetto ai 2 minuti.
* `match_scheduler`: nuovo bucket `live_import` in `TickPlan`, popolato dentro il
  ramo `_in_live_window`, con la propria condizione di cadenza.
* serve uno stampo separato: `data_checked_at` e' gia' usato dal poll leggero.
  **Migrazione**: `Match.data_imported_at = DateTimeField(null=True, blank=True)`.
* `tick.py`: nuovo passo fra `live_poll` e `final_check`, che su successo scrive
  `data_imported_at`.

`data_ready` **resta falso** per tutta la durata.

## 2. Upsert al posto di cancella-e-reinserisci

**File**: `realdata/services/sofascore_adapter.py`, funzione `_ingest_match`
(cerca `PlayerZoneFeature.objects.filter(match=match, provider=PROVIDER).delete()`).

Oggi cancella tutte le righe della partita e le reinserisce: con un import ogni
10 minuti rifa' anche gli indici, ogni volta. Sostituire con:

```python
PlayerZoneFeature.objects.bulk_create(
    player_rows, batch_size=1000,
    update_conflicts=True,
    update_fields=["value", "source_method"],
    unique_fields=["match", "player", "team_side", "zone_key", "feature_key", "provider"],
)
```

(Django 5.2 lo supporta; regge su SQLite e Postgres. I vincoli unici esistono gia'
come `unique_together` su entrambe le tabelle — per `TeamZoneFeature` senza
`player`.)

Poi **scartare le righe invariate prima di scrivere**: leggere i valori attuali in
un dict `{(player,side,zone,feature): value}` e mandare solo i differenti. Durante
una partita in corso i valori dell'undici in campo crescono di continuo, quindi il
guadagno vero e' su chi e' gia' uscito e sulle fasi morte — ma e' gratis.

**Righe sparite**: l'upsert non cancella cio' che non arriva piu'. Durante una
partita i valori solo crescono, quindi non succede; per sicurezza, dopo l'upsert
cancellare le sole righe della partita **non presenti** nell'insieme di chiavi
appena scritto.

**`MatchShot` no**: ha un `UniqueConstraint` *condizionato*
(`~Q(external_id="")`), che complica `update_conflicts`, ed e' ~25 righe a
partita. Lasciare cancella-e-reinserisci.

## 3. Dettaglio della partita di lega calcolato quando non e' conclusa

**File**: `vfoot/api/league_views.py`, `FixtureDetailView` (oggi restituisce
`fixture.detail.payload` verbatim e 404 se manca).

Quando la `FantasyMatchday` del fixture **non** e' `concluded`, calcolare al volo
con le stesse funzioni della conclusione, **senza persistere**:
`classic_matchday_scoring.build_matchday_index` →
`team_lines_for_conclusion` (per entrambe le squadre) → `score_composed_fixture`.

Non persistere e' importante: il payload congelato deve nascere solo alla
conclusione, altrimenti si perde la proprieta' per cui riaprire una partita chiusa
e' lettura pura (vedi `classic_live_scoring.md`).

Marcare l'instabilita':

* **per riga**, dove la partita reale del giocatore ha `data_ready=False`. Il giro
  giocatore → partita reale esiste gia' in `classic_matchday_scoring`
  (`pending_player_ids` fa la stessa risoluzione: stint → fixture della giornata).
* **sul totale di squadra**, se almeno una riga e' instabile — un totale composto
  in parte da voti provvisori e' esso stesso provvisorio.

Cambiare anche `has_detail` in `_serialize_fixture_row` (oggi vale `played`):
dev'essere vero anche per una giornata in corso, o il calendario non offre il link.

**Frontend**: `vfoot-frontend/src/components/match/ClassicMatchDetail.tsx` gia'
rende il payload; aggiungere il segno di instabilita' per riga e sul totale.

## 4. `LiveConsumer` accanto ad `AuctionConsumer`

**File**: `vfoot/consumers.py`, `vfoot/ws_routing.py`, nuovo
`vfoot/services/live_realtime.py` (specchio di `auction_realtime.py`).

Stesso pattern: spinta leggera `{"type":"update"}`, il client rilegge via REST;
token DRF in query string (i browser non possono mettere header sull'handshake);
connessione rifiutata se l'utente non e' membro della lega.

* rotta: `re_path(r"^ws/leagues/(?P<league_id>\d+)/live/$", LiveConsumer.as_asgi())`
* gruppo: per lega (`live_league_<id>`).
* chi manda la spinta: il passo `live_import` del tick, dopo un import che ha
  cambiato qualcosa. Le leghe interessate sono
  `FantasyLeague.objects.filter(reference_season_id=match.competition_season_id)`.

**Trappola da conoscere prima di provarlo.** In sviluppo `CHANNEL_LAYERS` usa
`InMemoryChannelLayer` (quando `REDIS_URL` e' vuoto), che **non fa fan-out fra
processi**. Il tick gira in un processo separato dal server web, quindi la spinta
non arrivera' mai. Per provare il live in locale serve Redis (`REDIS_URL` nel
`.env`), oppure si accetta che in sviluppo la pagina si aggiorni solo ricaricando.
Da dire nella documentazione, o si perde mezza giornata a cercare un bug che non
c'e'.

## 5. Push per gli eventi che meritano l'app chiusa

**File**: `vfoot/services/push_channel.py` (invio, gia' fatto),
`vfoot/services/league_notifications.py` (composizione), il passo `live_import`.

Eventi: **gol di un tuo giocatore, espulsione, conclusione della giornata** (la
terza probabilmente esiste gia' o e' vicina). Non un push per aggiornamento di
voto: sarebbe insopportabile.

Rilevarli richiede il **prima/dopo** dell'import, che oggi sovrascrive: catturare
`{player_id: (goals, red)}` prima di `ingest_sofascore_season` e confrontare dopo.

Destinatari: chi ha quel giocatore **schierato** in quella giornata
(`SavedLineupSnapshot`, chiave `team<id>` — vedi
`classic_matchday_scoring.read_saved_lineup`) e ha una `PushSubscription` viva.
`push_channel` cancella da solo le iscrizioni morte (404/410).

## 6. Home: le partite in corso, col link alla pagina live

**File**: `vfoot-frontend/src/components/LeagueHome.tsx`.

Oggi le partite della giornata in campo **spariscono**: `nextByCompetition` scarta
cio' che ha `lineup_locked` (giustamente: offrire "Formazione" su un turno gia'
cominciato porta a un 409) e `lastResults` prende solo `status === 'finished'`,
cioe' cio' che l'admin ha conteggiato. Un turno bloccato e non conteggiato non e'
ne' l'uno ne' l'altro.

Aggiungere una sezione con le partite della giornata **in campo**, che offre
l'accesso alla **visione live** (`/matches/<fixture_id>`), non la formazione.

* filtrare su `playingMd.real_matchday`, **non** su "bloccata e non finita": con un
  admin in ritardo anche gli arretrati sono bloccati e non conteggiati, ma quelli
  appartengono al riquadro della coda.
* **`playingMd` e' dichiarato piu' in basso** nel componente (`matchdays.find(m =>
  m.is_playing)`): un `useMemo` che lo usa va messo DOPO, o l'array di dipendenze
  lo legge nella zona morta temporale e la pagina esplode. (Gia' inciampato.)

---

## Come provarlo

La stagione simulata e la pipeline finta esistono gia':

```
./vfoot-sim                 # accende backend + frontend + cron, orologio al 31/01/2027 18:35
./vfoot-sim status
./vfoot-sim stop
```

Scenario `g22-live`: g22 a meta', una partita in corso. Vedi
`realdata/services/egress_sim.py` (il provider finto) e
`vfoot/management/commands/simulate_scenario.py`.

**Da estendere nel punto 1**: `egress_sim._matches` scrive il payload completo solo
se `kind == "final"` o la partita e' finita. Il nuovo import live dovra' chiedere
lo stesso `kind` (o se ne aggiunge uno), altrimenti il provider simulato servira'
solo l'evento leggero e l'import non trovera' nulla.

## Test da scrivere

* `live_import` non alza `data_ready`, e lo rialza `final_confirm`.
* due import a distanza di tempo su una partita in corso: i voti cambiano, e le
  righe scritte sono meno delle righe totali (l'upsert scarta le invariate).
* `FixtureDetailView` su giornata non conclusa: risponde 200, marca instabili le
  righe della partita ancora in corso, e **non** crea `FantasyFixtureDetail`.
* alla conclusione, il payload congelato e quello calcolato al volo coincidono.
