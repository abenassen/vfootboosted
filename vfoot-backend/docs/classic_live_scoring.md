# Fantavoto live nelle partite di lega (classic) — piano

Stato: **Fasi 1→4 fatte** (motore, snapshot, conclusione live, ricalcolo), più il locking (Fase 3c) nei due modelli. Documento di riferimento.

## Il problema

Due punteggi vanno tenuti distinti:

- **Partite di Serie A** → punteggio = **gol reali** (corretto, resta così).
- **Partite di lega (classic)** → i gol nascono dalla **somma dei fantavoti** (voto puro + bonus/malus, uno per giocatore, ognuno dalla *sua* partita reale) con conversione **66/+6** (66→1, 72→2, …).

Il motore classic completo **esiste già** (`services/classic_pagella`, `defense_bonus`, `lineup_substitution`, `scoring_engine`) e si vede funzionare nella **Lega Classic Demo**, che è interamente materializzata dal comando di seed.

**Il buco**: la conclusione live di una giornata (`LeagueMatchdayConcludeView.post`, `league_views.py:1933‑1934`) copia i **gol reali** di una singola partita reale collegata a caso al fixture (`source_real_match`, assegnato da un helper di simulazione beta `fantasy_simulation.py:118‑128`) invece di far girare il motore fantavoto. Quindi una lega giocata dal vivo produrrebbe risultati sbagliati.

## Parametri che influenzano il calcolo (decisi)

Configurabili per-lega:
- `max_substitutions` (default **5**): quanti titolari **s.v.** vengono rimpiazzati, scorrendo la panchina in ordine di priorità e tenendo la formazione legale; oltre il cap i restanti s.v. **non** entrano.
- `defense_bonus_enabled` + `defense_bonus_mode` (`add_own`/`subtract_opponent`): modificatore difesa (fasce e soglia ≥4 difensori **fisse**, standard).
- **`keeper_clean_sheet_enabled`** (default **off**, nuovo): **+1** se il portiere effettivo ha voto e **0 gol subiti**.

Regole fisse (standard fantacalcio, versionate nel codice, tag `rules_version`):
- Bonus/malus: gol +3, assist +1, rigore parato +3, autogol −2, rigore sbagliato −3, ammonizione −0.5, rosso/doppia gialla −1, portiere −1 per gol subìto.
- Conversione 66/72/78/84/90/96 = 1/2/3/4/5/6, poi +1 ogni 6.
- Formazione legale: 1 POR, 3‑5 DIF, 0‑5 CEN, 1‑3 ATT, 11 totali.
- Fasce modificatore difesa: media (top‑3 difensori + portiere, voto puro)/4 → **+1 ogni 0,25 sopra 6,00**, lineare e senza tetto ((6,00–6,25]:+1 · (6,25–6,50]:+2 · (6,50–6,75]:+3 · (6,75–7,00]:+4 · (7,00–7,25]:+5 · …); solo con ≥4 difensori titolari.

**Regola s.v. (DEC‑1)**: un s.v. **non è un valore** (né 0 né 6). Va sostituito; se non sostituibile, è **escluso** dal totale (la squadra somma < 11 voti).

**Estensibilità**: i modificatori vivono in un **registro** (`MODIFIERS` in `classic_scoring.py`); aggiungerne uno = appendere una funzione. Modificatori futuri possibili: portiere (fatto), centrocampo, attacco, fattore campo, bonus/malus personalizzati.

## Le tre invarianti (anti-disallineamento)

1. **Alla conclusione si congela TUTTO, in un'unica transazione**: `home_total/away_total` (risultato → classifica) + `FantasyFixtureDetail.payload` (tabellino completo: voti, fantavoti, sostituzioni, modificatori, fantatotale) + `FantasyMatchday.ruleset_snapshot` (le regole usate). La somma del payload **è** quel risultato.
2. **Riaprire una partita conclusa = lettura del congelato, zero ricalcolo**: il dettaglio H2H è servito da `FixtureDetailView` che restituisce `fixture.detail.payload` verbatim (`league_views.py:3085‑3088`). Risultato e voti frozen insieme → nessun disallineamento anche se le regole/la calibrazione cambiano dopo. La ricomputazione live resta **solo** per la pagella della partita reale di Serie A (`LeagueRealMatchDetailView`), che è un'altra pagina.
3. **Il ricalcolo riscrive risultato + payload + snapshot INSIEME** (mai un pezzo solo), sotto il regolamento scelto (attuale o snapshot).

## L'indice di giornata sta in cache (e perché non è un'eccezione all'invariante 2)

`build_matchday_index` è **il conto più caro che l'applicazione faccia in risposta a un
clic**: le dieci pagelle del turno reale — voto puro, esposizione difensiva e
spiegazione per ~460 giocatori. Misurato: **1,0–1,5 s**.

Lo pagavano due pagine, ogni volta:

* il **calendario** (`_live_totals`, che alimenta "Si gioca", "La tua prossima
  partita" e "Ultimi risultati" della home lega), per stampare **due numeri per
  partita** — 1.527 ms a ogni apertura della home, e di nuovo a ogni colpo del
  socket live;
* il **tabellino live** (`FixtureDetailView`), 2.091 ms.

Adesso l'indice è in cache, e i due call site scendono a **~115 ms** e **~58 ms**.

**Non intacca l'invariante 2**, perché non è la partita conclusa a essere messa in
cache: quella resta lettura verbatim di `FantasyFixtureDetail.payload` e non passa
di qui. In cache va l'INPUT del calcolo live, cioè le pagelle delle partite reali —
la stessa cosa che il punto 2 chiama già "ricomputazione live".

**La chiave è tutto** (`_index_cache_key`). Si muove su tre fronti, e servono tutti:

1. **i dati del turno** (`classic_pagella.matchday_data_version`) — stato,
   punteggio, `data_ready` e i due timbri di ogni partita, più quattro somme sulle
   presenze. Il tick timbra **dopo** aver importato, quindi una lettura che
   capitasse in mezzo salverebbe i dati nuovi sotto la chiave vecchia e il timbro
   che segue la manderebbe subito in soffitta — mai il contrario. Due minuti di
   partita e la chiave è un'altra: è la cadenza del giro live, cioè la freschezza
   che si vuole;
2. **i ruoli congelati della lega**, che l'import di Transfermarkt può aggiungere a
   lega in corso;
3. **`scoring_fingerprint()`**, perché ritoccare i pesi cambia ogni voto senza
   toccare una riga di database. Senza, il listone ha già servito per settimane
   voti calcolati prima di una ritaratura.

Perciò **non c'è niente da invalidare a mano**: chi importa continua a non sapere
che questa cache esista.

**Una voce viva per (lega, giornata).** La cache su file tiene 500 voci e ogni
indice pesa ~200 KB; un turno in diretta ne genererebbe una nuova ogni due minuti.
Arrivato al tetto, il culling di Django non butta le più vecchie — ne butta un
terzo a caso, e fra quelle la taratura del voto, che costa molto più di quel che
queste avevano risparmiato. Quindi scrivendo la nuova si cancella la precedente
(`_index_pointer_key`), che è spazzatura dall'istante in cui i dati si sono mossi.

Test: `tests_matchday_index_cache.py`.

## Fasi

- **Fase 1 — motore condiviso** ✅ `services/classic_scoring.py` + `tests_classic_scoring.py` (8 test verdi). `Ruleset` (from_league/to_snapshot/from_snapshot), registro `MODIFIERS`, `score_team`, `resolve_fixture`.
- **Fase 2 — modello**: campo `keeper_clean_sheet_enabled` su `FantasyLeague`; `ruleset_snapshot` (JSON) su `FantasyMatchday`; migrazioni; esporre il flag nelle impostazioni lega (API + UI).
- **Fase 3 — il fix vero** (conclusione): costruire l'**indice fantavoto** della giornata reale con `pagella_for_match` su tutte le partite; leggere le formazioni salvate (`SavedLineupSnapshot`); `score_team`/`resolve_fixture`; persistere `home_total/away_total` + `FantasyFixtureDetail.payload` + `ruleset_snapshot`. Sostituisce `league_views.py:1933‑1934`.
- **Fase 1b (pulizia, opzionale)**: rifattorizzare il seed perché usi questo motore (un solo scorer per Demo e leghe vere). Attenzione: la nuova regola s.v. cambierà i numeri della Demo (va ri-seedata).
- **Fase 4 — ricalcolo**: endpoint `POST /leagues/<id>/matchdays/<fmd_id>/recompute` + bottone in Gestione lega (regole attuali vs snapshot).

## Formazione: termine, re-editing, assenza (decisi)

**Squadra senza formazione impostata alla conclusione** — decisione dell'**admin caso per caso** (evento raro), tra:
- **forfait** (fantatotale 0), oppure
- **rischierare la formazione della giornata precedente** (se esiste; altrimenti forfait).

NO auto-formazione ottimale: darebbe vantaggio a chi non schiera (otterrebbe l'XI migliore a posteriori).

**"Previous" quando la rosa è cambiata** (mercato aperto nel frattempo): si riusa l'ultima formazione salvata **filtrata sui giocatori ancora in rosa**. I ceduti/svincolati → slot vuoti = **s.v.** → sostituzione automatica dai panchinari superstiti; slot scoperti = esclusi (nulla). I **nuovi acquisti non entrano automaticamente**. Il pre-check espone `previous_lineup_stale: N` (giocatori non più in rosa) così l'admin sceglie informato tra `previous` e `forfait`.

**Termine ultimo per schierare + re-editing** — due modelli, **entrambi implementati** e scelti dall'admin in Gestione lega (`FantasyLeague.lineup_lock_mode`, default `matchday`):
- **Modello 1** (`matchday`, default): la formazione si blocca all'inizio della **prima partita reale** della giornata; dopo non è più modificabile.
- **Modello 2b** (`player`): si può continuare a editare, ma ogni giocatore **la cui partita è iniziata** è **congelato dov'è** (portiere/titolare/panchina/fuori — il "fuori" conta: non lo si può nemmeno far entrare); si muovono solo i giocatori la cui partita non e' ancora iniziata, e la giornata si chiude all'**ultimo** calcio d'inizio. Fra due panchinari con la partita iniziata non si cambia nemmeno l'ordine di priorità: sarebbe scegliere chi entra a risultati visti. *Caveat confermato sul campo*: con panchina = tutta la rosa, la domenica sera 18 giocatori su 25 sono già congelati — il modello è significativo solo con panchina ridotta.
- Modello 2a (editabile finché nessuno schierato entra in campo) **scartato**.

**L'ordine dei titolari è DERIVATO, non del manager.** La pagina raggruppa l'XI per ruolo e non offre modo di riordinarlo, quindi quel che finiva salvato era un residuo dei click (un panchinaro promosso si accodava in fondo pur comparendo fra i suoi a schermo) — e quell'ordine viene letto sul serio: `apply_classic_substitutions` scorre i titolari spendendo il budget di cambi e verificando la legalità man mano. Perciò il salvataggio lo normalizza: **P-D-C-A**, con ogni congelato al suo posto **dentro il proprio reparto** (`lineup_deadline.normalise_xi`). Una richiesta forgiata non può riordinarlo: viene ricanonicalizzata, non rifiutata. La posizione assoluta di un congelato può ancora muoversi quando cambia il modulo — togliere un difensore alza di uno tutti i centrocampisti — ed è il prezzo di un XI che si legge sempre P-D-C-A; costa un vero cambio di modulo, non è un modo di ridecidere a risultati visti. L'ordine della **panchina** invece resta del manager, ed è lì che l'indice si difende.

Dove vive la regola: `services/matchday_state` (chi è bloccato e quando chiude la giornata), `services/lineup_deadline` (che cosa conta come "spostare" un giocatore congelato, e la normalizzazione dell'XI), l'endpoint di salvataggio formazione e `services/lineup_repair` (R1 diventa per-giocatore: un assestamento di mercato non tira fuori dalla formazione chi ha la partita iniziata).

**Separazione importante**: il termine/locking è **enforcement sull'endpoint di salvataggio formazione**, ORTOGONALE al motore di scoring. La conclusione (Fase 3) usa comunque la **formazione finale salvata**; il locking è un task a parte (**Fase 3c**).

## Contratto conclusione (Fase 3b) — da validare

La conclusione diventa "consapevole delle formazioni mancanti":
1. pre-check: individua le squadre della giornata **senza formazione**;
2. se ce ne sono e l'admin non ha ancora deciso → risposta `400` con l'elenco `teams_without_lineup: [{team_id, name, has_previous_lineup}]` (come già fa per `missing_source`/`missing_goals`);
3. l'admin richiama la conclusione con `lineup_resolutions: {team_id: "forfait" | "previous"}`;
4. si scoraggia/congela tutto.
