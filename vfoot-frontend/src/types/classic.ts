// Classic-mode fixture detail (league mode = 'classic'). Shape produced by the
// backend FantasyFixtureDetail.payload for classic leagues. Discriminated from the
// aura SimFixtureDetail by `mode: 'classic'`.

import type { FixtureManager } from './league';

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
  /** The vote was IMPOSED by the league: either a ruling on a match that was not
   *  played, or — with `sv_filled` — the league's standing voto d'ufficio filling
   *  a hole the bench could not cover. No bonus/malus either way. */
  office?: boolean;
  /** Era un buco: senza voto e senza rimpiazzo, coperto dal voto d'ufficio di lega. */
  sv_filled?: boolean;
  /** His club's match is being played, or has ended and the provider has not
   *  settled the data. There IS a vote — it is simply going to move. */
  provisional?: boolean;
  /** Il sottoinsieme stretto: la sua partita è SUL CAMPO adesso. Vale un'ora in
   *  meno di `provisional` (il fornitore conferma a +1h dal fischio) ed è l'unico
   *  che autorizza a scrivere «in corso». Fin qui non era un buco: la panchina non
   *  lo copre e il voto d'ufficio non lo riempie. */
  in_progress?: boolean;
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

/** Le voci che il riassunto NON mostra, una per una: cosa c'è sotto la riga
 *  «altre N voci». Non viaggia nel tabellino — ventidue giocatori per trenta righe,
 *  ricaricati a ogni spinta live — ma si chiede quando qualcuno apre quella riga.
 *
 *  `terms` + `tiny` fanno esattamente `other_points`: la riga che si è aperta. */
export interface VoteLedger {
  player_id: number;
  name: string;
  match_id: number;
  minutes: number;
  /** Il voto RICALCOLATO ora. Un referto congelato può portarne un altro, se è
   *  stato scritto con una taratura precedente del modello: allora questo elenco
   *  non spiega quel numero, e il pannello lo dice invece di far finta di sì. */
  voto: number;
  subtotal: number;
  other_points: number;
  other_count: number;
  terms: VoteLedgerTerm[];
  /** Le stesse voci raccolte per SENSO, col subtotale di ogni famiglia. Trenta
   *  righe da 0,01 sono un elenco, non una spiegazione: sei gruppi con un totale
   *  ciascuno si leggono, e chi vuole scende di un livello. ``terms`` resta come
   *  dettaglio dentro il gruppo. */
  groups?: VoteLedgerGroup[];
  /** I tiri, uno per uno. Arriva solo qui e non nel tabellino: costa una
   *  valutazione per tiro, e il tabellino si rifà a ogni spinta del punteggio in
   *  diretta per ventidue giocatori. */
  shots?: ShotDetail[];
  /** Le voci sotto il centesimo, contate e sommate insieme (e con loro gli
   *  arrotondamenti di tutte le altre): trenta righe di «+0,00» non si leggono. */
  tiny: { count: number; points: number };
}

export interface VoteLedgerGroup {
  key: string;
  title: string;
  points: number;
  terms: VoteLedgerTerm[];
}

export interface ShotDetail {
  minute: number | null;
  /** gol / parato / legno / murato / fuori */
  outcome: string;
  /** da dove veniva: su assist, in contropiede, su corner… vuoto se non si sa. */
  situation: string;
  xg: number;
  xgot: number;
  /** xGOT − xG: quanto la conclusione ha aggiunto alla palla che aveva. È la
   *  grandezza su cui il modello giudica il tiro, quindi si mostra invece di
   *  lasciarla ricavare. */
  added: number;
  /** Quanto vale QUESTO tiro, in punti di voto: il voto con lui meno il voto
   *  senza. Non è una quota di una somma — la compressione non è additiva. */
  points: number;
}

export interface VoteLedgerTerm {
  key: string;
  label: string;
  points: number;
  /** Quante volte l'ha fatto, come lo conta il tabellino — solo dove è un numero
   *  di cose: un indice normalizzato o un valore atteso, messo lì nudo, non
   *  spiegherebbe niente. */
  value?: number;
  /** La riga è la somma di più voci sovrapposte (le conclusioni, i dribbling). */
  family?: string;
  family_size?: number;
}

export type DefenseBonusGate = 'starters' | 'effective';

export interface ClassicDefenseBonus {
  eligible: boolean;
  /** Perché non è scattato: `meno_di_4_difensori_titolari` /
   *  `meno_di_4_difensori_con_voto` (a seconda del cancello della lega),
   *  `portiere_senza_voto`, `meno_di_3_difensori_con_voto`, `disattivato`. */
  reason: string;
  avg: number | null;
  bonus: number;
  applied: number; // signed adjustment to this team's total
  mode: 'add_own' | 'subtract_opponent' | null;
  /** Quale formazione ha contato il cancello dei 4 difensori: quella schierata o
   *  quella acquisita. Assente sui referti congelati prima che fosse un'opzione. */
  gate?: DefenseBonusGate | null;
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
  /** Almeno una delle sue partite vere è ancora sul campo. */
  in_progress?: boolean;
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
  /** I due fantallenatori. Assenti sulle pagelle di una partita vera di Serie A
   *  (non c'è nessuno che la schiera) e su qualunque referto che non venga da una
   *  sfida di lega. */
  home_manager?: FixtureManager | null;
  away_manager?: FixtureManager | null;
  home_goals: number;
  away_goals: number;
  home_total: number;
  away_total: number;
  defense_bonus_mode: 'add_own' | 'subtract_opponent' | null;
  defense_bonus_gate?: DefenseBonusGate | null;
  /** Quanto vale, in questa lega, un buco che la panchina non ha coperto. 0/assente
   *  = niente, la regola classica. */
  sv_office_vote?: number | null;
  result: 'home' | 'away' | 'draw';
  home: ClassicTeamDetail;
  away: ClassicTeamDetail;
  /** Le formazioni di questo turno sono bloccate? Falso = la giornata non è
   *  ancora cominciata e questo è un'ANTEPRIMA: nessuno ha giocato, i totali sono
   *  zero per costruzione e chi non ha ancora schierato può farlo. Assente sui
   *  referti congelati, che esistono solo a giornata conclusa — quindi il valore
   *  di riserva è `true`. */
  lineups_locked?: boolean;
  /** Quando si bloccano: il primo calcio d'inizio confermato della giornata. */
  lock_at?: string | null;
  /** Quando si blocca CIASCUNA, secondo la modalità della lega: in `own` ogni
   *  squadra alla prima partita di un proprio giocatore (`home`/`away`, con la
   *  partita che la chiude); in `player` nessuna scadenza unica, ma un
   *  congelamento progressivo fino a `last_at`; in `matchday` vale `lock_at`.
   *  `mode` nullo = scadenza spenta. */
  lineup_lock?: {
    mode: 'matchday' | 'own' | 'player' | null;
    home: { at: string | null; with: string | null } | null;
    away: { at: string | null; with: string | null } | null;
    last_at: string | null;
  } | null;
  /** Da dove viene la formazione mostrata, per lato: `lineup` = inviata per questa
   *  giornata; `previous` = ripescata dal turno precedente perché non ne ha
   *  inviata una; `forfait` = non ce n'è nessuna. Prima del blocco solo la prima
   *  si può mostrare come sua — le altre due sarebbero un'attribuzione falsa. */
  lineup_source?: { home?: string | null; away?: string | null };
  /** Computed on the fly because the matchday is not concluded (nothing frozen).
   *  ATTENZIONE: su una sfida di lega vuol dire «calcolato adesso invece che
   *  congelato», ed è vero dal primo calcio d'inizio fino al clic dell'admin —
   *  anche il lunedì mattina. Non è «la palla sta rotolando»: quella è
   *  `in_progress`, ed è quella che la pastiglia deve leggere. */
  live?: boolean;
  /** Some real match behind these votes has not settled: the score can still change. */
  provisional?: boolean;
  /** Almeno una delle partite vere dietro questo tabellino è sul campo adesso. */
  in_progress?: boolean;
  /** C'è un buco in formazione che il voto d'ufficio tapperà, ma non ancora: la
   *  giornata vera non è finita e un panchinaro può ancora coprirlo. Senza dirlo,
   *  un posto scoperto al sabato sera si legge come «qui il voto d'ufficio non
   *  c'è». */
  office_deferred?: boolean;
  /** Questo tabellino risponde a «se la giornata finisse adesso?» invece che
   *  «quanto sto facendo?». Cambia una cosa sola: il titolare con zero minuti in
   *  una partita in corso viene trattato come un senza voto definitivo — la
   *  panchina entra, il voto d'ufficio tappa. Chi è IN CAMPO non si tocca
   *  nemmeno qui. Non è il punteggio della sfida e non va presentato come tale:
   *  si chiede con `?projection=1` e non viene salvato da nessuna parte. */
  projected?: boolean;
  /** Il punteggio VERO, quello che si legge con l'interruttore spento. Viaggia
   *  solo dentro un tabellino previsionale, e serve a UNA domanda: le due
   *  risposte coincidono? Quando sì, i numeri in pagina non si muovono e senza
   *  una parola il tasto sembra rotto invece che d'accordo.
   *
   *  NON per mostrare il confronto: da acceso cambia già tutto il tabellino —
   *  testata, totali di squadra, cambi — e ristampare qui «56,5 → 68,5» diceva
   *  una terza volta la stessa cosa, per giunta con un delta che si leggeva come
   *  una somma ancora da fare. */
  actual?: {
    home_total: number;
    away_total: number;
    home_goals: number;
    away_goals: number;
  } | null;
  /**
   * Minutes played by whoever has been on longest — the clock of a real match in
   * progress. Null once it is over. Only the real-match detail sends it: a fantasy
   * fixture spans ten real matches at ten different minutes, and there is no single
   * clock to show.
   */
  minute?: number | null;
}
