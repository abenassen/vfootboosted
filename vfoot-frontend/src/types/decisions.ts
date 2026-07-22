/** Decisions a league has to take before (or during) a season.
 *
 * Generic on purpose: the first kind settles the role of players our data cannot
 * classify, but the same shape carries voti d'ufficio, rule changes and disputed
 * rectifications later on. */

export interface DecisionOption {
  value: string;
  label: string;
  /** How often players in the same provider position turned out to be this role,
   *  among the ones we could actually measure. Absent when we have no comparable
   *  cases at all. */
  share?: number;
  /** How many such players. "75%" out of four and out of forty are different
   *  statements, and only one is worth acting on. */
  sample?: number;
}

export interface LeagueDecision {
  id: number;
  kind: 'player_role' | 'other';
  title: string;
  question: string;
  options: DecisionOption[];
  /** What the system suggests. Never applied on its own for a blocking decision. */
  proposed: string;
  /** Why we could not decide — shown to the user, because a queue that says
   *  "decide this" without saying why is just an obstacle. */
  rationale: string;
  blocks_market: boolean;
  consultation_open: boolean;
  status: 'open' | 'resolved' | 'cancelled';
  outcome: string;
  player_id: number | null;
  player_name: string | null;
  my_vote: string | null;
  /** option value -> number of votes. Advisory: the admin decides. */
  tally: Record<string, number>;
  votes_total: number;
}

export interface LeagueDecisionsResponse {
  is_admin: boolean;
  /** Non-null while the market must stay shut, and says what is missing. */
  blocked_reason: string | null;
  blocking_open: number;
  /** Open consultations this user has not answered — the notification badge. */
  attention: number;
  decisions: LeagueDecision[];
}
