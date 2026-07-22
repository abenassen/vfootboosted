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
  role: ClassicRole;
  lineup_role: ClassicLineupRole;
  minutes: number;
  role_known?: boolean; // false => role GUESSED (squad data incomplete for him)
  sv: boolean; // senza voto: didn't play / not rated
  // Why he is s.v. — 'dati_mancanti' is OUR gap, not a judgement on the player.
  sv_reason?: 'dati_mancanti' | 'impiego_insufficiente' | null;
  voto_puro: number | null;
  bonus: number; // goal +3, assist +1, pen save +3
  malus: number; // own goal -2, pen miss -3, card, GK -1/goal conceded
  fantavoto: number | null; // voto_puro + bonus - malus
  events: ClassicPlayerEvents;
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
}

export interface ClassicFixtureDetail {
  mode: 'classic';
  fixture_id: number;
  fantasy_round: number;
  real_matchday: number;
  stage?: string | null; // knockout stage label (e.g. "Quarti di finale"), null in a league
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
}
