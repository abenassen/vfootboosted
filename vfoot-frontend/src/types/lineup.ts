// Real per-team lineup context (GET /leagues/<id>/lineup) and save payload.
export type PlayerRole = 'GK' | 'DEF' | 'MID' | 'ATT';
export type MinutesLabel = 'high' | 'medium' | 'low' | 'unknown';
export type LeagueMode = 'aura' | 'classic';

export interface ClassicConstraints {
  starters: number;
  per_role: Record<PlayerRole, { min: number; max: number }>;
}

export interface TeamLineupPlayer {
  player_id: number;
  name: string;
  price: number;
  role: PlayerRole;
  avg_col: number;
  footprint: Record<string, number>;
  appearances: number;   // convocazioni (panchine incluse), non partite giocate
  starts: number;        // presenze da titolare
  avg_minutes: number;
  minutes_label: MinutesLabel;
  real_team?: string | null;  // il club reale del giocatore
  form: number; // expected per-match contribution from recent form
  // Season the playing-time stats describe (the previous one before kick-off).
  stats_season?: string | null;
  // The REAL championship fixture this player's club plays on this matchday.
  value?: number | null;       // media voto (misurata o stimata) — leggibile
  value_basis?: string | null;
  next_match?: {
    team: string;              // il club del giocatore
    opponent: string;
    home: boolean;
    kickoff: string | null;
    kickoff_provisional: boolean;
    status: string;
  } | null;
}

export interface TeamLineupContext {
  team: { team_id: number; name: string };
  competitions: { competition_id: number; name: string }[];
  competition: number | null; // the competition this lineup refers to
  budget?: { initial: number; spent: number; remaining: number; by_role: Record<string, number> };
  stats_season?: string | null;      // stagione da cui vengono presenze/minuti/etichetta
  stats_is_reference?: boolean;      // true = campionato in corso; false = stagione precedente
  matchdays: number[];
  matchday: number;
  as_of_matchday: number | null; // data cutoff (only matches before it count)
  prior_matches: number;
  zone_grid: { cols: number; rows: number; zone_keys: string[] };
  rules: {
    starters: number;
    gk_separate_slot: boolean;
    mode: LeagueMode;
    classic_constraints: ClassicConstraints | null;
  };
  mode: LeagueMode;
  roster: TeamLineupPlayer[];
  saved_lineup: {
    gk_player_id: number | null;
    starter_player_ids: number[];
    bench_player_ids: number[];
    starter_backups: unknown[];
  } | null;
}

export interface SaveTeamLineupRequest {
  matchday: number;
  competition?: number | null;
  all_competitions?: boolean;
  gk_player_id: number | null;
  starter_player_ids: number[];
  bench_player_ids: number[];
}
