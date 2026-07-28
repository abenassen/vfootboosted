# #10 — Mercato di riparazione a offerte (svincolati) — piano

Stato: **da implementare**. Documento di partenza per una sessione dedicata. Basato sulla
descrizione dell'utente in `commenti_28-07.txt` (punti su "apri/chiudi mercato" e offerte).

## Obiettivo

Oggi il "mercato" è solo un flag booleano `FantasyLeague.market_open` (aperto/chiuso manuale)
e non permette di fare nulla. Serve un vero **mercato di riparazione a offerte** sugli
**svincolati**, con **svincolo simultaneo** di un proprio giocatore, in **sessioni** gestite
dall'admin.

## Concetti

- **Sessione di mercato**: finestra in cui si accettano offerte. Aperta dall'admin con
  **data/ora inizio–fine** oppure **a tempo indefinito** (apre/chiude manualmente). **Una
  sola sessione aperta per lega** alla volta.
- **Offerta**: un utente offre *N crediti* per uno **svincolato**, dichiarando **quale
  giocatore della propria rosa svincola** se l'offerta va a buon fine.
- **Recupero crediti** (scelto dall'admin per sessione): quando svincoli un giocatore
  recuperi crediti secondo una modalità:
  - **credito fisso** (es. 1), oppure
  - **frazione del prezzo d'acquisto**: 30% / 50% / 75%, **arrotondata per eccesso** (`ceil`).
- **Validità offerta** (classic): il giocatore **svincolato e quello acquistato hanno lo
  stesso ruolo**, e i crediti bastano — nei disponibili si conta **anche** il credito
  ottenuto dallo svincolo simultaneo.
  - *Esempio*: Mario ha 26 crediti; ha pagato Lautaro 135; recupero 50% → tetto offerta per
    Vlahovic svincolando Lautaro = `26 + ceil(135/2) = 26 + 68 = 94`.
- **Meccanica 24h**: un'offerta valida, se **non riceve rilanci per 24h**, è **accettata**
  (la validazione finale con aggiornamento rose spetta comunque agli admin). Un **rilancio**
  (altra offerta valida per lo stesso giocatore a cifra più alta) **resetta il contatore 24h**.
- **Controlli admin**: **sospendere** la sessione (non si accettano offerte) o **chiuderla**
  (anche prima della scadenza). Non può creare una nuova sessione se ce n'è una aperta.
- **Storico**: a sessione conclusa, lo **storico delle offerte** (accettate e non) resta
  **visibile agli utenti**, in una **lista delle sessioni** di mercato.

## Modello dati (proposta)

- `MarketSession(league FK, status[open|suspended|closed], opens_at, closes_at nullable,
  credit_recovery_mode[fixed|frac30|frac50|frac75], fixed_recovery_amount, created_by,
  created_at, closed_at)`. Vincolo: al più una `open|suspended` per lega.
- `MarketOffer(session FK, team FK (offerente), target_player FK (svincolato),
  release_player FK (da svincolare), amount, status[leading|outbid|accepted|rejected|
  cancelled], created_at, deadline_at (now+24h, aggiornata sui rilanci del target))`.
- Opzionale `MarketEvent` append-only per il feed/audit (come `AuctionEvent`).
- Alla conclusione/accettazione, l'aggiornamento rose usa `FantasyRosterSlot` (release =
  set `released_at`; acquisto = nuovo slot con `purchase_price = amount`).

## Riuso di infrastruttura esistente

- Crediti/ruoli/legalità: `vfoot/services/auction_engine.py` — `team_budgets`, `check_purchase`,
  `player_role`, `league_role_map`, `ROLES`. La validità offerta è molto simile alla
  legalità d'asta, con l'aggiunta del **recupero da svincolo** nel budget disponibile e del
  **vincolo di pari ruolo** tra rilasciato e acquistato.
- Realtime: l'asta usa **Channels/WebSocket** (`services/auction_realtime.py`, pagina Sala
  Asta). Il mercato a offerte può notificare rilanci/scadenze allo stesso modo, oppure
  partire **solo con polling** (più semplice) e aggiungere il realtime dopo.
- Timer 24h: campo `deadline_at` sull'offerta in testa + un **job periodico** che promuove a
  `accepted` le offerte scadute e senza rilanci. La lega ha già infra di **polling sul Linode**
  (vedi memory `sofascore-blocks-datacenter-ip`, `live-finalization-pipeline`): agganciare un
  tick che processa le scadenze. In alternativa, promozione *lazy* alla lettura + un cron.

## API (proposta)

- `POST /leagues/<id>/market/sessions` — apri sessione (date o indefinita, modalità recupero). 400 se ne esiste una aperta.
- `POST /leagues/<id>/market/sessions/<sid>/suspend|resume|close` — controlli admin.
- `GET  /leagues/<id>/market/sessions` — lista sessioni + storico offerte (utenti).
- `GET  /leagues/<id>/market/active` — sessione attiva + offerte correnti.
- `POST /leagues/<id>/market/offers` — crea offerta {target_player, release_player, amount}; valida (ruolo + crediti incl. recupero); imposta deadline +24h; marca outbid le precedenti più basse.
- `POST /leagues/<id>/market/offers/<oid>/cancel` — ritira la propria offerta (regole da definire).
- (admin) `POST /leagues/<id>/market/offers/<oid>/accept|reject` — validazione finale + aggiornamento rose.

## Frontend

- **Pagina Mercato** (`/market`, oggi placeholder "in arrivo"): se c'è una sessione attiva →
  lista svincolati offribili, form offerta (scegli svincolato dalla propria rosa **stesso
  ruolo**, importo con tetto calcolato live = crediti + recupero), le mie offerte con countdown
  24h, e le offerte in testa per giocatore. Storico sessioni concluse.
- **Gestione lega**: creazione sessione (date/ora o indefinita, modalità recupero), sospendi/
  chiudi, coda offerte in attesa di validazione (accept/reject).
- Coerenza con l'asta: se un'**asta** è in corso, evidenziarla nella home (già fatto in
  `/league` e `/market`); il mercato a offerte è il canale di **riparazione** post-asta.

## Decisioni aperte (da validare a inizio sessione)

1. **Recupero crediti**: le frazioni sono 30/50/75 `ceil`. Confermare i valori e se il "fisso"
   è configurabile (importo) o sempre 1.
2. **Pari ruolo**: rilasciato e acquistato **stesso ruolo classic** (POR/DIF/CEN/ATT). Confermare
   che sia sempre 1:1 (no sblocco per numero-slot residuo?).
3. **Rilanci**: chi rilancia deve superare l'offerta in testa; l'offerta superata torna
   `outbid`. La deadline 24h è **per giocatore** (sul leading) o **per offerta**? (proposta: per
   giocatore — la testa fissa il countdown).
4. **Cancellazione**: un utente può ritirare un'offerta in testa? Entro quando?
5. **Concorrenza crediti**: un utente può avere più offerte aperte contemporaneamente su
   giocatori diversi impegnando gli stessi crediti? (proposta: i crediti/impegni vanno
   "riservati" per evitare doppie spese, come nell'asta).
6. **Validazione finale admin**: automatica alla scadenza + coda di conferma, o sempre manuale?
7. **Realtime ora o dopo**: partire con polling (semplice) e aggiungere WebSocket in seguito?
8. **Notifiche**: avvisare l'offerente quando viene superato / quando vince (email Brevo già
   configurata, vedi memory `email-brevo-dns-linode`).

## Suggerimento di fasi (per la sessione dedicata)

1. Modelli + migrazioni (`MarketSession`, `MarketOffer`, evento opzionale) + validità offerta
   (servizio, riuso `auction_engine`) + test.
2. API sessioni (apri/sospendi/chiudi, no-concorrenza) + API offerte (crea/rilancia/cancella).
3. Timer 24h (job sul tick Linode) + promozione ad accepted + coda validazione admin.
4. Frontend pagina Mercato (offerte + countdown + storico) e controlli admin in Gestione lega.
5. (Opzionale) realtime WebSocket + notifiche email.
