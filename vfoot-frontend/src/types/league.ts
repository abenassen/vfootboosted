export interface LeagueSummary {
  league_id: number;
  name: string;
  role: 'admin' | 'manager';
  invite_code: string;
  market_open: boolean;
  team_name?: string | null;
}

export interface LeagueMember {
  membership_id: number;
  user_id: number;
  username: string;
  role: 'admin' | 'manager';
}

export interface LeagueTeam {
  team_id: number;
  name: string;
  manager_user_id: number;
  manager_username: string;
}

export interface LeagueDetail {
  league_id: number;
  name: string;
  market_open: boolean;
  invite_code: string;
  invite_link: string;
  members: LeagueMember[];
  teams: LeagueTeam[];
}

export interface TeamRoster {
  team_id: number;
  team_name: string;
  players: Array<{ player_id: number; name: string; price: number }>;
}

export interface CreateLeagueRequest {
  name: string;
  team_name: string;
}

export interface JoinLeagueRequest {
  invite_code: string;
  team_name: string;
}

export interface CompetitionTemplateRequest {
  name: string;
  competition_type: 'round_robin' | 'knockout';
  team_ids?: number[];
  starts_at?: string | null;
  ends_at?: string | null;
  container_only?: boolean;
}

export interface CompetitionParticipant {
  team_id: number;
  team_name: string;
  source: 'manual' | 'rule';
  manager_username: string;
  seed: number | null;
}

export interface CompetitionRule {
  rule_id: number;
  source_competition_id: number;
  source_competition_name: string;
  source_stage: 'halfway' | 'final';
  mode: 'table_range' | 'winner' | 'loser';
  rank_from: number | null;
  rank_to: number | null;
}

export interface CompetitionPrizeItem {
  prize_id: number;
  name: string;
  condition_type: 'final_table_range' | 'stage_table_range' | 'stage_winner' | 'stage_loser';
  source_stage_id: number | null;
  source_stage_name: string | null;
  rank_from: number | null;
  rank_to: number | null;
}

export interface CompetitionItem {
  competition_id: number;
  name: string;
  competition_type: 'round_robin' | 'knockout';
  status: 'draft' | 'active' | 'done';
  points: { win: number; draw: number; loss: number };
  starts_at: string | null;
  ends_at: string | null;
  participants: CompetitionParticipant[];
  qualification_rules: CompetitionRule[];
  prizes: CompetitionPrizeItem[];
  fixtures: { total: number; finished: number };
}

export interface CompetitionStageRuleIn {
  rule_id: number;
  source_stage_id: number;
  source_stage_name: string;
  source_competition_id?: number;
  source_competition_name?: string;
  mode: 'table_range' | 'winners' | 'losers';
  rank_from: number | null;
  rank_to: number | null;
}

export interface CompetitionStageCreateRequest {
  name: string;
  stage_type: 'round_robin' | 'knockout';
  order_index?: number;
  team_ids?: number[];
}

export interface CompetitionStageUpdateRequest {
  name?: string;
  stage_type?: 'round_robin' | 'knockout';
  order_index?: number;
  team_ids?: number[];
}

export interface CompetitionStageRuleCreateRequest {
  source_stage_id: number;
  mode: 'table_range' | 'winners' | 'losers';
  rank_from?: number;
  rank_to?: number;
}

export interface CompetitionStageRuleCreateResult {
  rule_id: number;
  target_stage_id: number;
  source_stage_id: number;
  mode: 'table_range' | 'winners' | 'losers';
  rank_from?: number | null;
  rank_to?: number | null;
  resolve?: {
    stage_id: number;
    resolved_rule_participants: number;
    unresolved_rules: number;
    fixtures_created: number;
  };
}

export interface CompetitionPrizeCreateRequest {
  name: string;
  condition_type: 'final_table_range' | 'stage_table_range' | 'stage_winner' | 'stage_loser';
  source_stage_id?: number;
  rank_from?: number;
  rank_to?: number;
}

export interface CompetitionStageItem {
  stage_id: number;
  competition_id: number;
  name: string;
  stage_type: 'round_robin' | 'knockout';
  status: 'draft' | 'active' | 'done';
  order_index: number;
  participants: CompetitionParticipant[];
  rules_in: CompetitionStageRuleIn[];
  fixtures: { total: number; finished: number };
}

export interface CompetitionUpdateRequest {
  name?: string;
  status?: 'draft' | 'active' | 'done';
  points_win?: number;
  points_draw?: number;
  points_loss?: number;
  starts_at?: string | null;
  ends_at?: string | null;
}

export interface CompetitionSchedulePreview {
  competition_id: number;
  competition_name: string;
  starts_at: string | null;
  ends_at: string | null;
  rounds: number[];
  available_real_matchdays: number[];
  real_competition_season_id: number | null;
  proposed_mapping: Record<string, number>;
  current_mapping: Record<string, number>;
}

export interface CompetitionScheduleApplyResult {
  competition_id: number;
  scheduled_fixtures: number;
  rounds: number;
  real_matchdays: number[];
  mapped_rounds: Record<string, number>;
}

export interface QualificationRuleCreateRequest {
  source_competition_id: number;
  source_stage: 'halfway' | 'final';
  mode: 'table_range' | 'winner' | 'loser';
  rank_from?: number;
  rank_to?: number;
}

export interface PlayerSearchItem {
  player_id: number;
  name: string;
  full_name: string;
}

export interface AuctionTeamBudget {
  team_id: number;
  team_name: string;
  manager_username: string;
  initial_budget: number;
  spent_budget: number;
  available_budget: number;
}

export interface AuctionNominationState {
  nomination_id: number;
  status: 'open' | 'closed';
  player_id: number;
  player_name: string;
  nominator: string;
  top_bid: number;
  winner_team_id: number | null;
  winner_team_name: string | null;
}

export interface AuctionState {
  auction_id: number;
  name: string;
  status: 'draft' | 'active' | 'closed';
  nomination_index: number;
  nomination_total: number;
  next_player: { player_id: number; name: string } | null;
  open_nomination: { nomination_id: number; player_id: number; player_name: string; nominator: string } | null;
  recent_nominations: AuctionNominationState[];
  team_budgets: AuctionTeamBudget[];
}

export interface LeagueFixtureItem {
  fixture_id: number;
  competition_id: number;
  competition_name: string;
  stage_id?: number | null;
  stage_name?: string | null;
  round_label?: string | null;
  fantasy_matchday_id?: number | null;
  real_matchday?: number | null;
  round_no: number;
  leg_no: number;
  kickoff: string | null;
  status: 'scheduled' | 'live' | 'finished';
  home_team: { team_id: number; name: string };
  away_team: { team_id: number; name: string };
  score: { home_total: number; away_total: number } | null;
  is_user_involved: boolean;
}

export interface LeagueMatchdayItem {
  fantasy_matchday_id: number;
  league_id: number;
  status: 'planned' | 'concluded';
  real_competition_season: {
    id: number;
    name: string;
    competition: string;
    season: string;
  };
  real_matchday: number;
  real_completion: {
    total: number;
    completed: number;
    is_completed: boolean;
  };
  fixtures: {
    total: number;
    finished: number;
  };
  concluded_at: string | null;
  concluded_by: string | null;
}
