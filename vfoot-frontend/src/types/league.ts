export interface LeagueSummary {
  league_id: number;
  name: string;
  role: 'admin' | 'manager';
  invite_code: string;
  market_open: boolean;
  team_name?: string | null;
  /** Opaque crest descriptor of the caller's team in THIS league (see
   *  utils/crest). One per team, unlike the avatar, which is one per account. */
  team_crest?: string | null;
  reference_season?: ReferenceSeason | null;
}

export interface LeagueMember {
  membership_id: number;
  user_id: number;
  username: string;
  role: 'admin' | 'manager';
}

export interface TeamRecord {
  played: number;
  wins: number;
  draws: number;
  losses: number;
  goals_for: number;
  goals_against: number;
}

export interface LeagueTeam {
  team_id: number;
  name: string;
  crest?: string | null;
  manager_user_id: number;
  manager_username: string;
  // W/D/L and goals aggregated across ALL competitions (no single table exists).
  record?: TeamRecord;
}

export interface ReferenceSeason {
  id: number;
  name: string;
  competition: string;
  season: string;
}

export interface RealSeasonItem extends ReferenceSeason {
  matchdays: number;
}

export interface LeagueDetail {
  league_id: number;
  name: string;
  mode: 'aura' | 'classic';
  market_open: boolean;
  max_substitutions: number;
  defense_bonus_enabled: boolean;
  defense_bonus_mode: 'add_own' | 'subtract_opponent';
  keeper_clean_sheet_enabled: boolean;
  enforce_lineup_deadline: boolean;
  invite_code: string;
  invite_link: string;
  reference_season: ReferenceSeason | null;
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
  // Real championship the league is played on: chosen ONCE at creation, then immutable.
  reference_season_id: number;
  /** Chosen ONCE at creation, like the reference season, and not editable after:
   *  it decides how points are made. Omitting it used to leave every league
   *  created from the UI on the server default, 'aura'. */
  mode?: 'classic' | 'aura';
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
  source_round: number | null;
  mode: 'table_range' | 'winner' | 'loser';
  rank_from: number | null;
  rank_to: number | null;
}

export interface CompetitionPrizeItem {
  prize_id: number;
  name: string;
  icon: string;
  condition_type: 'final_table_range' | 'stage_table_range' | 'stage_winner' | 'stage_loser';
  condition_label: string;
  source_stage_id: number | null;
  source_stage_name: string | null;
  rank_from: number | null;
  rank_to: number | null;
  winner_team_ids: number[];
  winner_team_names: string[];
}

export type ResultView = 'classifica' | 'tabellone' | 'risultati';

export interface CompetitionStructure {
  competition_id: number;
  name: string;
  result_view: ResultView;
  sections: CompetitionSection[];
}

export interface CompetitionSection {
  name: string;
  type: 'round_robin' | 'knockout';
  order: number;
  /** Positions that WIN something, from the competition's prize bands. */
  prize_ranks?: number[];
  /** Positions that merely carry on to a later stage. Never overlaps with
   *  prize_ranks: winning something is the stronger statement. */
  qualify_ranks?: number[];
  standings?: LeagueStandingRow[];
  rounds?: { round_no: number; label: string; fixtures: LeagueFixtureItem[] }[];
}

export type CompetitionFormat = 'league' | 'cup' | 'groups_knockout' | 'custom';

/** One round of a competition, named the way the user named its stage. */
export interface CompetitionRoundRow {
  round_no: number;
  stage_id: number | null;
  stage_name: string;
  stage_type: 'round_robin' | 'knockout';
  local_round: number;
  local_rounds: number;
  label: string;
  real_matchday: number | null;
}

export interface CompetitionDependency {
  kind: 'stage_rule' | 'qualification_rule';
  source_competition_id: number;
  source_competition_name: string;
  source_stage_name: string | null;
  source_round: number | null;
  real_matchday: number | null;
  target_stage_id: number | null;
}

export interface CompetitionItem {
  competition_id: number;
  name: string;
  competition_type: 'round_robin' | 'knockout';
  format: CompetitionFormat;
  result_view: ResultView;
  status: 'draft' | 'active' | 'done';
  structure_locked: boolean;
  rounds: CompetitionRoundRow[];
  round_calendar: Record<string, number>;
  dependencies: CompetitionDependency[];
  points: { win: number; draw: number; loss: number };
  starts_at: string | null;
  ends_at: string | null;
  start_matchday: number | null;
  end_matchday: number | null;
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
  source_round: number | null;
  rank_from: number | null;
  rank_to: number | null;
}

export interface CompetitionStageCreateRequest {
  name: string;
  stage_type: 'round_robin' | 'knockout';
  order_index?: number;
  legs?: number;
  team_ids?: number[];
  expected_participants?: number;
}

export interface CompetitionStageUpdateRequest {
  name?: string;
  stage_type?: 'round_robin' | 'knockout';
  order_index?: number;
  legs?: number;
  team_ids?: number[];
  expected_participants?: number;
}

export interface CompetitionStageRuleCreateRequest {
  source_stage_id: number;
  mode: 'table_range' | 'winners' | 'losers';
  source_round?: number | null;
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
  icon?: string;
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
  legs: number;
  round_offset: number;
  planned_rounds: number;
  expected_participants: number;
  first_matchday: number | null;
  last_matchday: number | null;
  participants: CompetitionParticipant[];
  rules_in: CompetitionStageRuleIn[];
  fixtures: { total: number; finished: number };
}

// ---- guided creation ----

export type WizardPrizeCondition = 'winner' | 'runner_up' | 'rank';

export interface WizardPrizeSpec {
  name: string;
  icon?: string;
  condition: WizardPrizeCondition;
  rank_from?: number;
  rank_to?: number;
}

export interface WizardQualificationSpec {
  source_stage_id: number;
  mode: 'table_range' | 'winners' | 'losers';
  source_round?: number | null;
  rank_from?: number;
  rank_to?: number;
}

export interface CompetitionWizardRequest {
  name: string;
  format: 'league' | 'cup' | 'groups_knockout';
  team_ids?: number[];
  qualification?: WizardQualificationSpec | null;
  legs?: number;
  groups?: number;
  advance_per_group?: number;
  points?: { win: number; draw: number; loss: number };
  start_matchday?: number | null;
  end_matchday?: number | null;
  prizes?: WizardPrizeSpec[];
}

export interface CompetitionWizardPlanStage {
  name: string;
  type: 'round_robin' | 'knockout';
  order_index: number;
  teams: number;
  rounds: number;
  matches: number;
}

export interface CompetitionWizardPlan {
  teams: number;
  stages: CompetitionWizardPlanStage[];
  total_rounds: number;
  min_start_matchday: number | null;
  constraint: string | null;
  season_real_matchdays: number[];
}

export interface CompetitionWizardResult {
  competition: CompetitionItem;
  stages: CompetitionStageItem[];
  schedule: CompetitionScheduleApplyResult;
  resolution: { stages_filled: number; stages_waiting: number };
}

export interface CompetitionUpdateRequest {
  name?: string;
  status?: 'draft' | 'active' | 'done';
  points_win?: number;
  points_draw?: number;
  points_loss?: number;
  starts_at?: string | null;
  ends_at?: string | null;
  start_matchday?: number | null;
  end_matchday?: number | null;
}

export interface CompetitionSchedulePreview {
  competition_id: number;
  competition_name: string;
  starts_at: string | null;
  ends_at: string | null;
  start_matchday: number | null;
  end_matchday: number | null;
  /** Earliest real matchday allowed by what this competition depends on. */
  min_start_matchday: number | null;
  constraints: string[];
  dependencies: CompetitionDependency[];
  rounds: number[];
  round_rows: Omit<CompetitionRoundRow, 'real_matchday'>[];
  available_real_matchdays: number[];
  season_real_matchdays: number[];
  real_competition_season_id: number | null;
  proposed_mapping: Record<string, number>;
  current_mapping: Record<string, number>;
  warnings: string[];
}

export interface CompetitionScheduleApplyResult {
  competition_id: number;
  scheduled_fixtures: number;
  rounds: number;
  real_matchdays: number[];
  mapped_rounds: Record<string, number>;
  min_start_matchday?: number | null;
  warnings?: string[];
}

export interface QualificationRuleCreateRequest {
  source_competition_id: number;
  source_stage: 'halfway' | 'final';
  source_round?: number | null;
  mode: 'table_range' | 'winner' | 'loser';
  rank_from?: number;
  rank_to?: number;
}

export interface PlayerSearchItem {
  player_id: number;
  name: string;
  full_name: string;
}

export type ClassicRole = 'POR' | 'DIF' | 'CEN' | 'ATT';

export interface AuctionSlotCount {
  quota: number;
  filled: number;
  remaining: number;
}

export interface AuctionTeamBudget {
  team_id: number;
  team_name: string;
  manager_username: string;
  initial_budget: number;
  spent_budget: number;
  available_budget: number;
  slots: Record<ClassicRole, AuctionSlotCount>;
  slots_remaining_total: number;
  max_bid_any: number;
}

export interface AuctionBidState {
  bid_id: number;
  team_id: number | null;
  team_name: string | null;
  manager: string;
  amount: number;
}

export interface AuctionTeamOption {
  team_id: number;
  team_name: string;
  max_bid: number;
  eligible: boolean;
}

export interface AuctionOpenNomination {
  nomination_id: number;
  player_id: number;
  player_name: string;
  player_role: ClassicRole | null;
  call_mode: string;
  nominator: string;
  top_bid: number;
  top_bidder_team_id: number | null;
  top_bidder_team_name: string | null;
  min_next_bid: number;
  bids: AuctionBidState[];
  team_options: AuctionTeamOption[];
}

export interface AuctionNominationState {
  nomination_id: number;
  status: 'open' | 'closed' | 'cancelled';
  player_id: number;
  player_name: string;
  call_mode: string;
  nominator: string;
  winner_team_id: number | null;
  winner_team_name: string | null;
  winning_amount: number | null;
}

export interface AuctionEventItem {
  id: number;
  type: string;
  actor: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface AuctionState {
  auction_id: number;
  name: string;
  status: 'draft' | 'active' | 'closed';
  league_id: number;
  roster_slots: Record<ClassicRole, number>;
  initial_budget: number;
  pool_total: number;
  pool_remaining: number;
  remaining_by_role: Record<ClassicRole, number>;
  open_nomination: AuctionOpenNomination | null;
  recent_nominations: AuctionNominationState[];
  events: AuctionEventItem[];
  team_budgets: AuctionTeamBudget[];
}

export interface ActiveAuctionInfo {
  auction_id: number | null;
  status: string | null;
  is_admin: boolean;
  mode: 'aura' | 'classic';
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
  phase: 'concluded' | 'current' | 'awaiting' | 'future' | 'unscheduled';
  /** Its real matchday has kicked off: the lineup is frozen for good. Read from the
   *  real calendar, so it is true regardless of how far behind the admin is. */
  lineup_locked?: boolean;
  home_team: { team_id: number; name: string; crest?: string | null };
  away_team: { team_id: number; name: string; crest?: string | null };
  score: { home_total: number; away_total: number } | null;
  is_user_involved: boolean;
  /** Decided server-side: also depends on the roster, which the calendar does not
   *  load. False on an empty roster — there would be nothing to field. */
  can_set_lineup?: boolean;
  /** A fixture that has not been played has no rich detail, and opening it can
   *  only end on an error page. */
  has_detail?: boolean;
}

export interface LeagueMatchdayItem {
  fantasy_matchday_id: number;
  league_id: number;
  status: 'planned' | 'awaiting' | 'concluded';
  /** The LEDGER's view: what has been counted. Never a statement about what is
   *  being played — that is `is_playing` / `is_fieldable`, which come from the real
   *  calendar and do not wait for the admin. */
  phase: 'concluded' | 'current' | 'awaiting' | 'future';
  /** The earliest matchday whose lineups can still be set. */
  is_fieldable: boolean;
  /** A match of this round is on the pitch right now. */
  is_playing: boolean;
  lineup_lock_at: string | null;
  /** May be closed right now (enforces the order). */
  can_conclude: boolean;
  conclude_blocked_reason: string;
  /** The league owes this one: complete and unscored. Every arrear, not just the
   *  first — the count of what a forgotten conclusion has piled up. */
  awaits_conclusion: boolean;
  awaiting_since: string | null;
  awaiting_reason: string;
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

export interface LeagueStandingRow {
  rank: number;
  team_id: number;
  team: string;
  crest?: string | null;
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
