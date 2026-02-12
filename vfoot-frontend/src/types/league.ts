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
