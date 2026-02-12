export type TeamSide = 'home' | 'away';

export interface ZoneGrid {
  cols: number;
  rows: number;
  zone_ids: string[]; // length = cols*rows
  meta?: Record<string, unknown>;
}

export interface Provenance {
  source: string;
  as_of?: string;
  confidence?: number;
  notes?: string;
}

export interface ZoneMapNumber {
  values: number[]; // ordered like zone_ids
}

export interface MinutesExpectation {
  value: number; // 0..1
  label: 'low' | 'medium' | 'high';
}

export interface PlayerStatus {
  injury: string | null;
  suspension: boolean;
  minutes_expectation: MinutesExpectation;
}

export interface PlayerInfluenceEstimate {
  zone_map: ZoneMapNumber; // where the player tends to operate
  quality_map?: ZoneMapNumber; // zone influence weighted by value/quality
  provenance?: Provenance;
}

export interface RosterPlayer {
  player_id: string;
  name: string;
  real_team: string;
  price: number;
  status: PlayerStatus;
  estimated_influence: PlayerInfluenceEstimate;
}

export interface SavedLineup {
  lineup_id: string;
  gk_player_id?: string | null;
  starter_player_ids: string[];
  bench_player_ids: string[];
  starter_backups: Array<{ starter_player_id: string; backup_player_ids: string[] }>;
  ui_hints?: { last_saved_at?: string };
}

export interface CoveragePreview {
  team_zone_coverage: ZoneMapNumber;
  team_zone_quality: ZoneMapNumber;
  summary: {
    def_mid_att: { def: number; mid: number; att: number };
    critical_holes: string[];
  };
}

export interface LineupContextResponse {
  league: { id: string; name: string };
  matchday: { id: string; name: string; deadline: string };
  rules: {
    starters_count: number;
    bench_count: number;
    gk_separate_slot: boolean;
    allow_any_substitution: boolean;
  };
  zone_grid: ZoneGrid;
  squad: { team_id: string; name: string; colors?: { primary: string; secondary?: string } };
  roster: RosterPlayer[];
  saved_lineup: SavedLineup;
  coverage_preview: CoveragePreview;
  provenance?: Provenance;
}

export interface SaveLineupRequest {
  league_id: string;
  matchday_id: string;
  gk_player_id?: string | null;
  starter_player_ids: string[];
  bench_player_ids: string[];
  starter_backups: Array<{ starter_player_id: string; backup_player_ids: string[] }>;
}

export interface SaveLineupResponse {
  lineup_id: string;
  saved_at: string;
  coverage_preview: CoveragePreview;
  warnings?: Array<{ code: string; player_id?: string; message: string }>;
}

export interface MatchListItem {
  match_id: string;
  home: { team_id: string; name: string };
  away: { team_id: string; name: string };
  status: 'scheduled' | 'live' | 'finished';
  score?: { home_total: number; away_total: number };
}

export interface MatchDetailResponse {
  match: { match_id: string; league_id: string; matchday_id: string; status: 'finished' | 'live' | 'scheduled' };
  teams: {
    home: { team_id: string; name: string; colors?: { primary: string; secondary?: string } };
    away: { team_id: string; name: string; colors?: { primary: string; secondary?: string } };
  };
  zone_grid: ZoneGrid;
  score: {
    home_total: number;
    away_total: number;
    breakdown?: {
      zones_total?: { home: number; away: number };
      base_total?: { home: number; away: number };
    };
  };
  story: {
    takeaways: Array<{ text: string; zone_group?: string; macro?: string; swing: number }>;
    decisive_zones: string[];
  };
  zone_results: Array<{
    zone_id: string;
    winner: TeamSide | 'draw';
    points: { home: number; away: number; swing: number };
    margin: number;
    macro_scores: Record<string, { home: number; away: number; swing: number }>;
    key_factor: string;
    top_contributors: {
      home: Array<{ player_id: string; name: string; contrib: number }>;
      away: Array<{ player_id: string; name: string; contrib: number }>;
    };
    explain_stats?: Record<string, Array<{ label: string; home: number; away: number }>>;
  }>;
  zone_maps: {
    winner_map: { values: Array<TeamSide | 'draw'> };
    points_map: ZoneMapNumber;
    margin_map: ZoneMapNumber;
    key_factor_map: { values: string[] };
  };
  line_summaries: {
    by_flank: Record<string, { swing: number }>;
    by_height: Record<string, { swing: number }>;
  };
  provenance?: Provenance;
}
