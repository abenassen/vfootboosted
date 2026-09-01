// Real reference-championship (e.g. Serie A) calendar + results, as served by
// GET /leagues/<id>/real-fixtures. The clickable per-match detail reuses the
// ClassicFixtureDetail shape (see types/classic.ts).

/** DA CHE PARTE SI CHIEDE IL CAMPIONATO VERO. Calendario, pagelle e listone sono
 *  della stagione, non della lega: dentro una lega si chiedono per lega (che
 *  aggiunge i proprietari nel listone e i ruoli congelati nelle pagelle), e senza
 *  lega — chi si è appena iscritto — si chiedono per stagione. Stessa risposta,
 *  stesso codice dietro (v. league_views.real_fixtures_payload). */
export type RealScope = { league: number } | { season: number };

export type RealMatchStatus =
  | 'scheduled'
  | 'live'
  | 'finished'
  | 'postponed'
  | 'cancelled';

export interface RealFixtureItem {
  id: number;
  matchday: number | null;
  kickoff: string | null; // ISO 8601, or null if unknown
  kickoff_provisional: boolean;
  status: RealMatchStatus;
  home_team: string;
  away_team: string;
  home_short: string;
  away_short: string;
  home_goals: number | null;
  away_goals: number | null;
  has_detail: boolean; // finished + player data available -> clickable
}

export interface RealMatchdayGroup {
  matchday: number | null;
  fixtures: RealFixtureItem[];
}

export interface RealFixturesResponse {
  season: { id: number; name: string; competition: string } | null;
  current_matchday: number | null;
  matchdays: RealMatchdayGroup[];
}

// Championship player pool ("listone") — GET /leagues/<id>/championship-players
export interface ChampionshipPlayer {
  player_id: number;
  /** Short form, the one shown in the list ("L. Martinez"). */
  name: string;
  /** Unabbreviated, so a search for the first name can match. */
  full_name?: string;
  role: string; // POR | DIF | CEN | ATT | ''
  team: string | null; // real club
  owned: boolean; // owned by a fantasy team in this league
  /** His role is still an open question in this league, so he cannot be
   *  auctioned or added to a roster until the admin decides. */
  role_undecided?: boolean;
  owner: string | null; // owning fantasy team name, if any
  // Value = avg voto puro, blended: last season's average early on, progressively
  // replaced by current-season form. null when the player has no data anywhere.
  value: number | null;
  // Homogeneous figure for EVERY player: the measured voto when there is one, else a
  // voto estimated from the market value — this is what makes the listone a single
  // ranked list instead of a tail of unrated newcomers.
  estimated_value: number | null;
  value_basis: 'corrente' | 'precedente' | 'misto' | 'stimato' | null;
  appearances: number; // rated appearances THIS season
  prev_appearances: number; // rated appearances last season
  // External-source signal (Transfermarkt), in whole EUR. Secondary ordering hint
  // for players with no on-pitch history — never a substitute for a voto.
  market_value: number | null;
}

export interface ChampionshipPlayersResponse {
  value_season: string | null; // previous season used as the prior (if any)
  current_season: string;
  count: number;
  // Calibration of the market->voto estimate (r = fit quality), null if not fitted.
  value_fit: { intercept: number; slope: number; r: number; n: number } | null;
  players: ChampionshipPlayer[];
}

// --- probabili formazioni ---------------------------------------------------
// GET /real-matches/<id>/probable-lineups. TRE STRATI, e `sources` dice quale
// sta parlando: 'vfoot' è la nostra stima dalle presenze (c'è sempre, non sa
// nulla di notizie), 'sofascore' è la loro previsione (arriva ~80 ore prima e
// le notizie le sa). Una previsione con una sola fonte non è la stessa cosa di
// una con due, e la pagina lo deve dire.

export type ProbableStatus = 'starter' | 'bench' | 'doubt' | 'out';

export interface ProbablePlayer {
  player_id: number;
  name: string;
  /** POR | DIF | CEN | ATT | '' — il ruolo con cui la lista si ordina. */
  role: string;
  /** 0..100. Zero significa indisponibile, non "molto improbabile". */
  probability: number;
  /** Il valore del giro precedente, per la freccia. */
  previous: number | null;
  status: ProbableStatus;
  /** Perché è fuori, quando lo sappiamo: «squalificato (5a ammonizione)». */
  reason: string;
  sources: string[];
}

export interface ProbableSide {
  formation: string;
  players: ProbablePlayer[];
}

export interface ProbableLineups {
  match_id: number;
  kickoff: string | null;
  refreshed_at: string;
  sources: string[];
  official: boolean;
  home_team: string;
  away_team: string;
  home: ProbableSide;
  away: ProbableSide;
}
