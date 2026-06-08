// Types for the read-only historical Vfoot league dry-run simulation.
// Mirrors the backend artifact served at /api/v1/simulations/historical-vfoot/latest.

export type SimResult = 'home' | 'draw' | 'away';

export interface SimConfig {
  teams: number;
  squad_size: number;
  starters: number;
  bench_size: number;
  budget: number;
  matchdays: number;
  seed: number;
  scoring_mode: string;
  score_base: number;
  score_scale: number;
  fantasy_home_advantage: number;
  fantasy_margin_boost: number;
  temporal_substitutions: boolean;
  vector_calibration: string;
}

export interface SimTopPlayer {
  name: string;
  player_id: number;
  price: number;
  value: number;
}

export interface SimTeam {
  id: number;
  name: string;
  remaining_budget: number;
  roster_size: number;
  spent: number;
  top_players: SimTopPlayer[];
}

export interface SimStanding {
  rank: number;
  team: string;
  played: number;
  wins: number;
  draws: number;
  losses: number;
  goals_for: number;
  goals_against: number;
  goal_diff: number;
  points: number;
  avg_score_for: number;
}

export interface SimScoreRange {
  min: number;
  avg: number;
  max: number;
}

export interface SimDistributions {
  results: { home_wins: number; draws: number; away_wins: number };
  top_scorelines: { scoreline: string; count: number }[];
  score_range: SimScoreRange | null;
  total_fixtures: number;
}

export interface SimOverview {
  version: string;
  player_pool_size: number;
  config: SimConfig;
  teams: SimTeam[];
  standings: SimStanding[];
  notes: string[];
  distributions: SimDistributions;
  rounds: number[];
}

export interface SimFixtureSummary {
  fixture_id: number;
  fantasy_round: number;
  real_matchday: number;
  home_team: string;
  away_team: string;
  home_score: number;
  away_score: number;
  home_goals: number;
  away_goals: number;
  result: SimResult;
}

export interface SimPlayerLine {
  name: string;
  player_id: number;
  event_score: number;
}

export interface SimSubstitution {
  starter: string;
  starter_id: number;
  covered: boolean;
  gap: [number, number];
  // Present only when the gap was actually covered by a bench player.
  bench?: string;
  bench_id?: number;
  covered_seconds?: number;
  gap_seconds?: number;
  // Present on uncovered gaps caused by a red / second-yellow card.
  reason?: string;
}

export interface SimSubstitutionReport {
  mode: string;
  covered_gap_seconds: number;
  uncovered_gap_seconds: number;
  disciplinary_gap_seconds: number;
  used_bench_count: number;
  substitutions: SimSubstitution[];
}

export interface SimLineup {
  score: number;
  vector_margin: number;
  avg_event_score: number;
  raw_event_sum: number;
  available_players: number;
  starter_count: number;
  bench_count: number;
  starters: SimPlayerLine[];
  bench: SimPlayerLine[];
  substitution_report: SimSubstitutionReport;
}

export interface SimZoneFeature {
  feature: string;
  home: number;
  away: number;
  swing: number;
}

export interface SimZone {
  zone_key: string;
  winner: SimResult;
  margin: number;
  features: SimZoneFeature[];
}

export interface SimPlayerTotal {
  player_id: number;
  name: string;
  total: number;
  zones: Record<string, number>;
}

export interface SimScoreBuild {
  base: number;
  score_scale: number;
  fantasy_margin_boost: number;
  fantasy_home_advantage: number;
  zone_count: number;
}

export interface SimVectorReport {
  total_margin: number;
  boosted_margin: number;
  score_build: SimScoreBuild;
  zones: SimZone[];
  home_player_totals: SimPlayerTotal[];
  away_player_totals: SimPlayerTotal[];
}

export interface SimFixtureDetail extends SimFixtureSummary {
  home_lineup: SimLineup;
  away_lineup: SimLineup;
  vector_report: SimVectorReport;
}
