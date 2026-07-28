# Fantavoto live nelle partite di lega (classic) — piano

Stato: **Fase 1 fatta** (motore + test verdi). Documento di riferimento, aggiornato man mano.

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

**Regola s.v. (DEC‑1)**: un s.v. **non è un valore** (né 0 né 6). Va sostituito; se non sostituibile, è **escluso** dal totale (la squadra somma < 11 voti).

**Estensibilità**: i modificatori vivono in un **registro** (`MODIFIERS` in `classic_scoring.py`); aggiungerne uno = appendere una funzione. Modificatori futuri possibili: portiere (fatto), centrocampo, attacco, fattore campo, bonus/malus personalizzati.

## Le tre invarianti (anti-disallineamento)

1. **Alla conclusione si congela TUTTO, in un'unica transazione**: `home_total/away_total` (risultato → classifica) + `FantasyFixtureDetail.payload` (tabellino completo: voti, fantavoti, sostituzioni, modificatori, fantatotale) + `FantasyMatchday.ruleset_snapshot` (le regole usate). La somma del payload **è** quel risultato.
2. **Riaprire una partita conclusa = lettura del congelato, zero ricalcolo**: il dettaglio H2H è servito da `FixtureDetailView` che restituisce `fixture.detail.payload` verbatim (`league_views.py:3085‑3088`). Risultato e voti frozen insieme → nessun disallineamento anche se le regole/la calibrazione cambiano dopo. La ricomputazione live resta **solo** per la pagella della partita reale di Serie A (`LeagueRealMatchDetailView`), che è un'altra pagina.
3. **Il ricalcolo riscrive risultato + payload + snapshot INSIEME** (mai un pezzo solo), sotto il regolamento scelto (attuale o snapshot).

## Fasi

- **Fase 1 — motore condiviso** ✅ `services/classic_scoring.py` + `tests_classic_scoring.py` (8 test verdi). `Ruleset` (from_league/to_snapshot/from_snapshot), registro `MODIFIERS`, `score_team`, `resolve_fixture`.
- **Fase 2 — modello**: campo `keeper_clean_sheet_enabled` su `FantasyLeague`; `ruleset_snapshot` (JSON) su `FantasyMatchday`; migrazioni; esporre il flag nelle impostazioni lega (API + UI).
- **Fase 3 — il fix vero** (conclusione): costruire l'**indice fantavoto** della giornata reale con `pagella_for_match` su tutte le partite; leggere le formazioni salvate (`SavedLineupSnapshot`); `score_team`/`resolve_fixture`; persistere `home_total/away_total` + `FantasyFixtureDetail.payload` + `ruleset_snapshot`. Sostituisce `league_views.py:1933‑1934`.
- **Fase 1b (pulizia, opzionale)**: rifattorizzare il seed perché usi questo motore (un solo scorer per Demo e leghe vere). Attenzione: la nuova regola s.v. cambierà i numeri della Demo (va ri-seedata).
- **Fase 4 — ricalcolo**: endpoint `POST /leagues/<id>/matchdays/<fmd_id>/recompute` + bottone in Gestione lega (regole attuali vs snapshot).

## Decisione ancora aperta

**Squadra senza formazione impostata alla conclusione (Fase 3)**:
- (a) formazione automatica di default (migliori per ruolo dalla rosa) — *consigliata*;
- (b) forfait / tutti s.v.;
- (c) blocco la conclusione finché tutti hanno schierato (o l'admin forza — esiste già `force`).
