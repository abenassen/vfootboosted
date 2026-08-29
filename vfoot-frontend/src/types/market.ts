// Repair market (offer-based sessions on free agents, classic mode).

export type MarketRecoveryMode = 'fixed' | 'frac30' | 'frac50' | 'frac75';
export type MarketSessionStatus = 'open' | 'suspended' | 'closed';
/** Come la si legge a schermo. `scheduled` non e' uno stato del server: e' una
 *  sessione `open` la cui ora di apertura deve ancora arrivare (vedi
 *  `sessionPhase` in utils/market). */
export type MarketSessionPhase = MarketSessionStatus | 'scheduled';
export type MarketOfferStatus =
  | 'leading'
  | 'outbid'
  | 'accepted'
  | 'settled'
  | 'rejected'
  | 'cancelled';

export interface MarketSessionInfo {
  id: number;
  name: string;
  status: MarketSessionStatus;
  /** Quando il mercato APRE (programmabile in anticipo). Nel futuro = annunciato
   *  ma non ancora cominciato: si guarda, non si offre. */
  opens_at: string | null;
  /** Quando ha aperto DAVVERO. Null finche' l'ora non e' scattata. */
  opened_at: string | null;
  closes_at: string | null;
  credit_recovery_mode: MarketRecoveryMode;
  fixed_recovery_amount: number;
}

export interface MarketLeading {
  offer_id: number;
  amount: number;
  team_id: number;
  team_name: string | null;
  deadline_at: string | null;
  mine: boolean;
  /** Chi il primo della fila promette di svincolare: un'offerta e' uno scambio
   *  pari ruolo, e senza questa meta' non si sa cosa sta davvero mettendo sul
   *  piatto. */
  release_player_id: number;
  release_name: string | null;
}

/** Chi si e' gia' aggiudicato lo svincolato e aspetta la validazione dell'admin.
 *  Stessa sostanza di `MarketLeading`, ma la corsa e' finita: niente scadenza,
 *  e la decisione non e' piu' della lega. */
export interface MarketPending {
  amount: number;
  team_id: number;
  team_name: string | null;
  release_player_id: number;
  release_name: string | null;
  mine: boolean;
}

export interface MarketFreeAgent {
  player_id: number;
  /** Short form, the one shown in the list ("L. Martínez"). */
  name: string | null;
  /** Unabbreviated, so a search for the first name can match. */
  full_name?: string | null;
  /** Il club VERO (Serie A), non la squadra fantacalcio: si cerca anche per
   *  quello, e in una lista di centinaia di svincolati e' meta' di cio' che
   *  serve per riconoscere un nome. */
  real_team?: string | null;
  role: string | null;
  locked: boolean;
  leading: MarketLeading | null;
  /** Valorizzato quando `locked` viene da un'offerta vinta e ancora in coda. */
  pending?: MarketPending | null;
}

export interface MarketRosterPlayer {
  player_id: number;
  name: string | null;
  full_name?: string | null;
  role: string | null;
  price: number;
  recovery: number;
}

export interface MarketBudget {
  remaining: number;
  reserved: number;
  available: number;
}

export interface MarketOfferRow {
  offer_id: number;
  team_id: number;
  team_name?: string | null;
  target_player_id: number;
  target_name: string | null;
  release_player_id: number;
  release_name: string | null;
  amount: number;
  recovery: number;
  role: string;
  status: MarketOfferStatus;
  deadline_at: string | null;
  created_at: string;
  /** Solo nella coda admin: da quale sessione arriva l'offerta, e se quella
   *  sessione e' gia' chiusa (la coda le sopravvive). */
  session_name?: string;
  session_closed?: boolean;
}

export interface MarketActive {
  session: MarketSessionInfo | null;
  is_admin: boolean;
  mode: string;
  my_team_id: number | null;
  my_budget?: MarketBudget | null;
  free_agents?: MarketFreeAgent[];
  my_roster?: MarketRosterPlayer[];
  my_offers?: MarketOfferRow[];
  admin_queue?: MarketOfferRow[];
  /** Il campionato vero e' in campo: applicare un'offerta muove due rose, e il
   *  server lo rifiuta finche' la giornata non e' finita. Arriva anche senza
   *  sessione viva, perche' la coda di validazione le sopravvive. */
  matchday_in_progress?: boolean;
  /** Quale giornata, per poterla nominare. */
  playing_matchday?: number | null;
}

export interface MarketSessionHistory extends MarketSessionInfo {
  closed_at: string | null;
  offers: MarketOfferRow[];
}

/** Cosa comporta togliere di mezzo un'offerta (annullarla o rifiutarla).
 *
 *  Il server lo racconta PRIMA che l'admin decida, perche' un'offerta che era un
 *  rilancio ne copre un'altra, e quella non torna in testa da sola: senza dirlo,
 *  l'admin libera il giocatore credendo di aver annullato una cosa sola. */
export interface MarketDiscardPreview {
  offer_id: number;
  action: 'cancel' | 'reject';
  status: MarketOfferStatus;
  target_name: string | null;
  team_name: string | null;
  amount: number;
  is_rebid: boolean;
  previous: MarketPreviousOffer | null;
}

export interface MarketPreviousOffer {
  offer_id: number;
  team_id: number;
  team_name: string | null;
  amount: number;
  release_player_id: number;
  release_name: string | null;
  created_at: string;
  deadline_at: string | null;
  /** Se no, `blocker` dice cosa e' cambiato da quando fu fatta. */
  restorable: boolean;
  blocker: string;
  /** Il suo tempo era gia' finito mentre il rilancio la teneva coperta. */
  expired: boolean;
  /** Ripristinata, va dritta in validazione invece di tornare in testa. */
  would_queue: boolean;
}
