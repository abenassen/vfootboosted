// Real per-team lineup context (GET /leagues/<id>/lineup) and save payload.
export type PlayerRole = 'GK' | 'DEF' | 'MID' | 'ATT';
export type MinutesLabel = 'high' | 'medium' | 'low';

export interface TeamLineupPlayer {
  player_id: number;
  name: string;
  price: number;
  role: PlayerRole;
  avg_col: number;
  footprint: Record<string, number>;
  appearances: number;
  avg_minutes: number;
  minutes_label: MinutesLabel;
}

export interface TeamLineupContext {
  team: { team_id: number; name: string };
  matchdays: number[];
  matchday: number;
  zone_grid: { cols: number; rows: number; zone_keys: string[] };
  rules: { starters: number; gk_separate_slot: boolean };
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
  gk_player_id: number | null;
  starter_player_ids: number[];
  bench_player_ids: number[];
}
