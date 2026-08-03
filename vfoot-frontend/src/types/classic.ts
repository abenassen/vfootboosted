// Classic-mode fixture detail (league mode = 'classic'). Shape produced by the
// backend FantasyFixtureDetail.payload for classic leagues. Discriminated from the
// aura SimFixtureDetail by `mode: 'classic'`.

export type ClassicRole = 'POR' | 'DIF' | 'CEN' | 'ATT';
export type ClassicLineupRole = 'GK' | 'DEF' | 'MID' | 'ATT';

export interface ClassicPlayerRef {
  player_id: number;
  name: string;
}

export interface ClassicPlayerEvents {
  goals: number;
  assists: number;
  yellow: number;
  red: number;
  own_goals: number;
}

export interface ClassicPlayerLine {
  player_id: number;
  name: string;
  /** Null on a placeholder line: it is read off the PERFORMANCE, and a player with
   *  no performance has none. `lineup_role` is always there and carries the same
   *  fact in the lineup's own vocabulary — see `roleOf`. */
  role: ClassicRole | null;
  lineup_role: ClassicLineupRole;
  minutes: number;
  role_known?: boolean; // false => role GUESSED (squad data incomplete for him)
  sv: boolean; // senza voto: didn't play / not rated
  // Why he is s.v. — 'dati_mancanti' is OUR gap, not a judgement on the player.
  /** Why there is no vote. `non_entrato` is the whole bench on a normal weekend
   *  and says what we know; `dati_mancanti` is the rare case where a player has
   *  minutes and no performance behind them, i.e. OUR hole. Payloads frozen
   *  before the two were told apart carry `dati_mancanti` with zero minutes —
   *  see `svKind`, which reads them for what they are. */
  sv_reason?: 'non_entrato' | 'dati_mancanti' | 'impiego_insufficiente' | 'in_campo' | null;
  /** His club's match has not been played (a postponement). Reads as s.v. in the
   *  sum but is NOT one: the bench does not cover it, and the league settles it
   *  later — by the recovery, or by an office vote. */
  pending?: boolean;
  /** The vote was IMPOSED by the league for a match that was not played. */
  office?: boolean;
  /** His club's match is being played, or has ended and the provider has not
   *  settled the data. There IS a vote — it is simply going to move. */
  provisional?: boolean;
  voto_puro: number | null;
  bonus: number; // goal +3, assist +1, pen save +3
  malus: number; // own goal -2, pen miss -3, card, GK -1/goal conceded
  fantavoto: number | null; // voto_puro + bonus - malus
  /** Absent on a line that stands in for a player with no performance behind it:
   *  a senza voto, an imposed vote, a club whose match has not been played. There
   *  are no events to report, and the placeholder says so by omission — which the
   *  type has to admit, because a required field here made the renderer trust a
   *  value that has never been there. */
  events?: ClassicPlayerEvents;
  /** Why the voto puro came out where it did, in vote points against the average
   *  player in the same role. Absent for s.v. — explaining a vote that does not
   *  exist would mean inventing one. */
  explanation?: {
    /** The named slices, largest first, in vote points. */
    contributions: { label: string; points: number }[];
    base: number;            // where every vote starts: the role average (6)
    other_points: number;    // the long tail of small slices, folded into one
    other_count: number;
    subtotal: number;        // base + contributions + other, before rounding
    voto: number;            // the voto puro, subtotal rounded to the half
    minutes: number;
    low_minutes: boolean;
    note: string;
  };
  explanation_text?: string;
  entered: boolean; // bench player who came in
  entered_for: ClassicPlayerRef | null;
  replaced_by: ClassicPlayerRef | null; // starter who was substituted
}

export interface ClassicDefenseBonus {
  eligible: boolean;
  reason: string;
  avg: number | null;
  bonus: number;
  applied: number; // signed adjustment to this team's total
  mode: 'add_own' | 'subtract_opponent' | null;
}

export interface ClassicSubstitution {
  out: ClassicPlayerRef;
  in: ClassicPlayerRef;
}

export interface ClassicTeamDetail {
  starters: ClassicPlayerLine[];
  bench: ClassicPlayerLine[];
  substitutions: ClassicSubstitution[];
  base_total: number; // sum of effective fantavoti, before the defence modifier
  total: number; // base_total + applied defence modifier
  goals: number; // classic goals from the total
  defense: ClassicDefenseBonus;
  /** Ogni modificatore applicato alla squadra, difesa compresa. Il fattore campo
   *  (`home_advantage`) esiste solo qui: non ha una sezione sua perché è un
   *  modificatore come gli altri, con una condizione che riguarda la partita. */
  modifiers?: Array<{ key: string; eligible: boolean; value: number; scope: string; detail?: unknown }>;
  /** At least one line is still moving, so this total is too. */
  provisional?: boolean;
}

export interface ClassicFixtureDetail {
  mode: 'classic';
  fixture_id: number;
  fantasy_round: number;
  real_matchday: number;
  stage?: string | null; // knockout stage label (e.g. "Quarti di finale"), null in a league
  /** The competition this fixture belongs to. Absent on payloads frozen before it
   *  was recorded — the shell simply does not realign for those. */
  competition_id?: number | null;
  home_team: string;
  away_team: string;
  home_goals: number;
  away_goals: number;
  home_total: number;
  away_total: number;
  defense_bonus_mode: 'add_own' | 'subtract_opponent' | null;
  result: 'home' | 'away' | 'draw';
  home: ClassicTeamDetail;
  away: ClassicTeamDetail;
  /** Computed on the fly because the matchday is not concluded (nothing frozen). */
  live?: boolean;
  /** Some real match behind these votes has not settled: the score can still change. */
  provisional?: boolean;
}
