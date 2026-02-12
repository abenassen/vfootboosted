export interface LeagueSummary {
  league_id: number;
  name: string;
  role: 'admin' | 'manager';
  invite_code: string;
  market_open: boolean;
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

export interface CompetitionItem {
  competition_id: number;
  name: string;
  competition_type: 'round_robin' | 'knockout';
  status: 'draft' | 'active' | 'done';
  points: { win: number; draw: number; loss: number };
  participants: CompetitionParticipant[];
  qualification_rules: CompetitionRule[];
  fixtures: { total: number; finished: number };
}

export interface CompetitionUpdateRequest {
  name?: string;
  status?: 'draft' | 'active' | 'done';
  points_win?: number;
  points_draw?: number;
  points_loss?: number;
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
  round_no: number;
  leg_no: number;
  kickoff: string | null;
  status: 'scheduled' | 'live' | 'finished';
  home_team: { team_id: number; name: string };
  away_team: { team_id: number; name: string };
  score: { home_total: number; away_total: number } | null;
  is_user_involved: boolean;
}
