import type { LineupLockMode } from './lineup';

export interface LeagueSummary {
  league_id: number;
  name: string;
  role: 'admin' | 'manager';
  invite_code: string;
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
  /** Giocatori sotto contratto adesso. Zero = rosa ancora da fare. */
  roster_count?: number;
}

/** Chi schiera una delle due squadre di un tabellino. Arriva col referto ma non
 *  è congelato dentro: il backend lo rilegge a ogni richiesta, così l'avatar sui
 *  tabellini vecchi è sempre la faccia di adesso. Opzionale ovunque, perché una
 *  partita simulata non ha allenatori veri dietro. */
export interface FixtureManager {
  user_id: number;
  username: string;
  /** Descrittore opaco (v. utils/avatar). Vuoto = faccia predefinita dal nome. */
  avatar: string;
  team_id: number;
}

export interface ReferenceSeason {
  id: number;
  name: string;
  competition: string;
  season: string;
}

export interface RealSeasonItem extends ReferenceSeason {
  matchdays: number;
  /** Si sta ancora giocando: c'è almeno una partita da giocare, oppure il
   *  calendario non è ancora uscito. Una lega si può legare solo a una di queste
   *  — vedi matchday_state.open_season_ids lato server. */
  open: boolean;
}

export interface LeagueDetail {
  league_id: number;
  name: string;
  mode: 'aura' | 'classic';
  max_substitutions: number;
  defense_bonus_enabled: boolean;
  defense_bonus_mode: 'add_own' | 'subtract_opponent';
  keeper_clean_sheet_enabled: boolean;
  home_advantage_bonus: number;
  enforce_lineup_deadline: boolean;
  lineup_lock_mode: LineupLockMode;
  invite_code: string;
  invite_link: string;
  reference_season: ReferenceSeason | null;
  members: LeagueMember[];
  teams: LeagueTeam[];
}

export interface TeamRoster {
  team_id: number;
  team_name: string;
  players: Array<{
    slot_id: number;
    player_id: number;
    name: string;
    price: number;
    /** Ruolo congelato nel listone di lega. Null in aura, dove non esiste. */
    role: ClassicRole | null;
  }>;
  /** Portafoglio e caselle della squadra. Null in aura: non c'e' ne' asta ne' quota. */
  budget: {
    initial: number;
    spent: number;
    remaining: number;
    slots: Record<ClassicRole, AuctionSlotCount>;
    slots_remaining_total: number;
  } | null;
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

/** A position ('...table_range', 'stage_winner'/'stage_loser') or a record
 *  ('stat_top'/'stat_bottom' over one `PrizeStat`). */
export type PrizeConditionType =
  | 'final_table_range'
  | 'stage_table_range'
  | 'stage_winner'
  | 'stage_loser'
  | 'stat_top'
  | 'stat_bottom';

export type PrizeStat = 'avg_score' | 'goals_for' | 'goals_against' | 'best_round' | 'wins';

export interface CompetitionPrizeItem {
  prize_id: number;
  name: string;
  icon: string;
  condition_type: PrizeConditionType;
  condition_label: string;
  /** Only for the two `stat_*` conditions; '' otherwise. */
  stat: PrizeStat | '';
  source_stage_id: number | null;
  source_stage_name: string | null;
  rank_from: number | null;
  rank_to: number | null;
  winner_team_ids: number[];
  winner_team_names: string[];
}

/** One line of an albo d'oro: a prize, where it was won, and when. */
export interface HonourItem {
  prize_id: number;
  name: string;
  icon: string;
  condition_label: string;
  competition_id: number;
  competition_name: string;
  competition_format: string;
  league_id: number;
  league_name: string;
  team_id: number | null;
  team_name: string | null;
  crest: string;
  /** How many other teams tied for the same record. 0 for an outright win. */
  shared_with: number;
  at: string | null;
}

export interface ManagerHonours {
  user_id: number;
  username: string;
  awards: HonourItem[];
}

/** One league on a manager's public card, with the team he fields in it. */
export interface ManagerLeagueItem {
  league_id: number;
  name: string;
  mode: 'aura' | 'classic';
  role: 'admin' | 'manager';
  joined_at: string | null;
  /** Null until he has a team: joining a league comes first. */
  team_id: number | null;
  team_name: string | null;
  team_crest: string;
}

/** The public card of a fantallenatore: who he is and where he plays.
 *  Carries no contact details — anyone sharing a league can open it. */
export interface ManagerProfile {
  user_id: number;
  username: string;
  avatar: string;
  joined_at: string | null;
  is_self: boolean;
  /** Only the leagues the viewer shares with him (all of them, on one's own). */
  leagues: ManagerLeagueItem[];
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

/** Why a phase that is planned has not been drawn yet.
 *
 *  Only `da_giocare` is normal. The other three are ways a competition stops
 *  moving without anything looking broken, so they are named rather than left to
 *  be inferred from an empty round. */
export interface CompetitionBlocker {
  /** `senza_giornate` is the only one that is not a wait: the season has no
   *  fieldable matchday left, so the phase will never be drawn and the admin has to
   *  decide what to do with the competition. */
  kind: 'da_giocare' | 'da_conteggiare' | 'recupero' | 'sorgente_da_definire' | 'senza_giornate';
  detail: string;
  real_matchday: number | null;
  source_competition_id: number;
  source_round?: number | null;
}

/** One round of a competition, named the way the user named its stage.
 *
 *  These come from the PLAN, so a round with no fixtures is in the list too — that
 *  is the point. `pending` says its teams are not known yet and `rule_text` says
 *  what will decide them. */
export interface CompetitionRoundRow {
  round_no: number;
  stage_id: number | null;
  stage_name: string;
  stage_type: 'round_robin' | 'knockout';
  local_round: number;
  local_rounds: number;
  label: string;
  real_matchday: number | null;
  /** Fixtures this round actually has. Zero + `pending` = waiting on a rule. */
  fixtures?: number;
  pending?: boolean;
  rule_text?: string | null;
  blocker?: CompetitionBlocker | null;
  /** How many matches the round will hold once the draw is made. */
  expected_fixtures?: number;
}

/** A whole phase of the competition, with the rule that fills it. Read when
 *  naming every undrawn round would be N copies of one sentence. */
export interface CompetitionStagePlan {
  stage_id: number;
  name: string;
  stage_type: 'round_robin' | 'knockout';
  order_index: number;
  first_round: number;
  last_round: number;
  planned_rounds: number;
  first_matchday: number | null;
  last_matchday: number | null;
  fixtures: number;
  expected_participants: number;
  expected_fixtures_per_round: number;
  pending: boolean;
  rules: Array<{
    mode: 'table_range' | 'winners' | 'losers';
    text: string;
    source_stage_id: number;
    source_stage_name: string;
    source_competition_id: number;
    source_competition_name: string;
    source_round: number | null;
    ready: boolean;
    blocker: CompetitionBlocker | null;
  }>;
  rule_text: string;
  blocker: CompetitionBlocker | null;
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
  stage_plan?: CompetitionStagePlan[];
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
  condition_type: PrizeConditionType;
  stat?: PrizeStat;
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

export type WizardPrizeCondition = 'winner' | 'runner_up' | 'rank' | 'stat';

export interface WizardPrizeSpec {
  name: string;
  icon?: string;
  condition: WizardPrizeCondition;
  rank_from?: number;
  rank_to?: number;
  /** 'stat' only: which record, and from which end of it. */
  stat?: PrizeStat;
  direction?: 'top' | 'bottom';
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
  /** Turni a eliminazione: 1 = gara secca, 2 = andata e ritorno (due giornate).
   *  `final_legs` sovrascrive solo l'ultimo turno. */
  knockout_legs?: number;
  final_legs?: number;
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

/** Un rigore: chi l'ha tirato, quanto valeva, e com'è andata. */
export interface ShootoutKick {
  player_id: number;
  name: string;
  voto_puro: number;
  p: number;
  roll: number;
  scored: boolean;
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
  /** I PUNTEGGI delle due formazioni — la somma dei fantavoto — che non sono i
   *  gol: sono il primo spareggio di un turno secco, quindi il numero che decide
   *  chi passa quando una sfida finisce in parità. Assente finché non c'è un
   *  tabellino. */
  totals?: { home: number; away: number } | null;
  /** The score above is a PARTIAL one: the round has begun, nobody has counted it,
   *  and some real match behind it has not settled. Distinguishes "0-0 because it
   *  has not started" from "0-0 at the twentieth minute" — the same two numbers. */
  score_provisional?: boolean;
  /** Knockout sections only: who went through. Not always the higher score — a tie
   *  is settled by the aggregate score and then by home advantage (see the backend
   *  `knockout` service). */
  advanced_team_id?: number | null;
  /** Why, when the result alone does not say it ('punteggio', 'rigori',
   *  'fattore campo'). Null when they simply scored more. */
  advanced_reason?: string | null;
  /** La serie di rigori, quando c'è stata. Battuta una volta alla conclusione e
   *  salvata sulla partita: qui si legge, non si rigioca. */
  shootout?: {
    home_goals: number;
    away_goals: number;
    winner: 'home' | 'away' | null;
    home: ShootoutKick[];
    away: ShootoutKick[];
  } | null;
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
  /** A match of this round is on the pitch right now. Narrow on purpose: false on
   *  the Saturday night between two kick-offs, and false once the data has settled. */
  is_playing: boolean;
  /** The round has BEGUN — its first confirmed kickoff has passed — and stays true
   *  for the whole round, including the gaps between matches and the wait for the
   *  admin's conclusion. This is what "your match of this round is worth looking at"
   *  keys on; `is_playing` is only whether there is a ball rolling this minute. */
  has_kicked_off?: boolean;
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
  /** Phases of OTHER competitions whose field this matchday decides. Empty for
   *  almost every round; when it is not, closing (or parking) this one is not a
   *  bookkeeping detail — a cup is waiting on it. */
  decides?: MatchdayImpact[];
  concluded_at: string | null;
  concluded_by: string | null;
}

/** A phase that cannot be drawn until a given matchday is counted. */
export interface MatchdayImpact {
  competition_id: number;
  competition_name: string;
  stage_id: number;
  stage_name: string;
  rule_text: string;
  blocker_kind: CompetitionBlocker['kind'];
  /** The first matchday the waiting phase is itself planned for. */
  target_matchday: number | null;
  /** That matchday has already locked: the phase has missed its slot and will have
   *  to be moved forward when it is finally drawn. */
  at_risk: boolean;
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
  /** Questa riga conta una partita ancora da finire: i punti possono cambiare
   *  prima che la giornata venga conclusa. */
  provisional?: boolean;
}
