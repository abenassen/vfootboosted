// Real per-team lineup context (GET /leagues/<id>/lineup) and save payload.
export type PlayerRole = 'GK' | 'DEF' | 'MID' | 'ATT';
export type MinutesLabel = 'high' | 'medium' | 'low' | 'unknown';
export type LeagueMode = 'aura' | 'classic';
/** Which deadline the league plays under: the whole XI at the round's first kickoff,
 *  or each player at his own club's. */
/** Fin quando si schiera: alla prima partita della giornata (`matchday`), alla
 *  prima partita di uno dei PROPRI venticinque (`own`, il default), o sempre, coi
 *  giocatori gia' scesi in campo congelati uno a uno (`player`). */
export type LineupLockMode = 'matchday' | 'own' | 'player';

export interface ClassicConstraints {
  starters: number;
  per_role: Record<PlayerRole, { min: number; max: number }>;
}

export interface TeamLineupPlayer {
  player_id: number;
  name: string;
  price: number;
  role: PlayerRole;
  avg_col: number;
  footprint: Record<string, number>;
  appearances: number;   // convocazioni (panchine incluse), non partite giocate
  starts: number;        // presenze da titolare
  avg_minutes: number;
  minutes_label: MinutesLabel;
  /** Le ultime giornate, che sono la base di `minutes_label`: quante volte è
   *  sceso in campo su `recent_window` giornate, e quanti minuti in media.
   *  L'etichetta si spiega mostrando questi, non ripetendo una regola. */
  recent_appearances: number;
  recent_avg_minutes: number;
  recent_window: number;
  real_team?: string | null;  // il club reale del giocatore
  form: number; // expected per-match contribution from recent form
  // Season the playing-time stats describe (the previous one before kick-off).
  stats_season?: string | null;
  // The REAL championship fixture this player's club plays on this matchday.
  value?: number | null;       // media voto (misurata o stimata) — leggibile
  value_basis?: string | null;
  next_match?: {
    team: string;              // il club del giocatore
    opponent: string;
    home: boolean;
    kickoff: string | null;
    kickoff_provisional: boolean;
    status: string;
  } | null;
  /** Quanto è probabile che parta titolare in QUESTA giornata reale.
   *  Assente finché non c'è niente da dire: né la nostra stima né SofaScore.
   *  `sources` dice chi sta parlando, e conta — v. ProbableLineups.tsx. */
  starting?: {
    probability: number;       // 0..100; zero = indisponibile, non "improbabile"
    previous: number | null;
    status: 'starter' | 'bench' | 'doubt' | 'out';
    reason: string;            // «squalificato (5a ammonizione)»
    sources: string[];
    /** Quando abbiamo letto la fonte esterna. Un numero che viene da fuori è
     *  vecchio quanto l'ultima lettura, e chi lo guarda deve poterlo sapere.
     *  Null quando parla solo la nostra stima, che è sempre corrente. */
    as_of: string | null;
  } | null;
  // Frozen where he stands: his club is already playing, and the league locks
  // player by player. Always false under the matchday-wide deadline.
  locked?: boolean;
}

export interface TeamLineupContext {
  team: {
    team_id: number;
    name: string;
    manager?: string;
    manager_user_id?: number;
    crest?: string | null;
  };
  is_own?: boolean;
  competitions: { competition_id: number; name: string }[];
  competition: number | null; // the competition this lineup refers to
  budget?: {
    initial: number;
    /** Crediti dati (o tolti) dall'admin fuori da asta e mercato. */
    granted: number;
    /** Conguagli di scambio incassati o pagati. */
    trade_cash: number;
    spent: number;
    /** Crediti bruciati dai contratti chiusi: pagato meno incassato. Il residuo
     *  non e' initial - spent, e questo e' il pezzo che manca all'appello. */
    sunk: number;
    remaining: number;
    /** Gia' impegnati in offerte di mercato aperte. */
    reserved: number;
    /** Quanto si puo' ancora offrire: residuo meno impegnato. E' il numero che
     *  la pagina Mercato chiama «disponibili». */
    available: number;
    by_role: Record<string, number>;
  };
  stats_season?: string | null;      // stagione da cui vengono presenze/minuti/etichetta
  stats_is_reference?: boolean;      // true = campionato in corso; false = stagione precedente
  matchdays: number[];
  matchday: number;
  as_of_matchday: number | null; // data cutoff (only matches before it count)
  prior_matches: number;
  zone_grid: { cols: number; rows: number; zone_keys: string[] };
  rules: {
    starters: number;
    gk_separate_slot: boolean;
    mode: LeagueMode;
    classic_constraints: ClassicConstraints | null;
  };
  mode: LeagueMode;
  roster: TeamLineupPlayer[];
  /** Quale rosa e' quella qui sopra: quella POSSEDUTA adesso («now», la pagina
   *  Rose) o quella schierabile in questa giornata («matchday», la formazione).
   *  Divergono solo a turno cominciato. */
  roster_scope?: 'now' | 'matchday';
  /** In cosa differiscono le due, coi nomi. Null quando coincidono. */
  roster_freeze?: {
    matchday: number;
    frozen_at: string | null;
    /** Ceduti a turno iniziato: fuori rosa, ma schierabili in questa giornata. */
    leaving: { player_id: number; name: string | null }[];
    /** Arrivati a turno iniziato: in rosa, ma schierabili dalla prossima. */
    arriving: { player_id: number; name: string | null }[];
  } | null;
  saved_lineup: {
    gk_player_id: number | null;
    starter_player_ids: number[];
    bench_player_ids: number[];
    starter_backups: unknown[];
  } | null;
  /** Da dove viene quello che `saved_lineup` contiene: la formazione salvata per
   *  questa giornata, quella EREDITATA dalla precedente (chi non ha ancora
   *  schierato riparte da li', non da zero), o niente. `vacant_roles` sono i posti
   *  rimasti scoperti perché quei giocatori non sono più in rosa. */
  lineup_source?: {
    /** `baseline`: written by the server when the roster completed — the
     *  suggested XI, a lineup in every respect until the manager overwrites it. */
    kind: 'saved' | 'previous' | 'baseline' | 'none';
    from_matchday: number | null;
    vacant_roles: PlayerRole[];
  };
  /** The server's suggested XI for this roster and matchday — the one suggester,
   *  frozen players honoured. What «Suggerisci XI» applies, and what the page
   *  starts from when nothing is saved. */
  suggested_lineup?: { gk_player_id: number | null; starter_player_ids: number[] } | null;
  // The deadline as it applies to THIS matchday. `closes_at` is the moment there is
  // nothing left to decide: the first kickoff under the matchday-wide lock, the
  // first kickoff of one of THIS team's players under `own`, the last one under
  // the per-player lock.
  lineup_lock?: {
    mode: LineupLockMode;
    enforced: boolean;
    closes_at: string | null;
    /** Under `own`: the match that sets the deadline, so the page can say
     *  «fino alle 15:00 di sabato, con Milan-Como» instead of a bare date. */
    closes_with?: { home: string; away: string } | null;
    closed: boolean;
    locked_player_ids: number[];
    /** Dal primo calcio d'inizio, in una lega col modificatore difesa, il NUMERO
     *  di difensori schierati non cambia piu': ne' inviando, ne' per sostituzione.
     *  `defence_count` è quello fissato, dalla formazione che fa da base. */
    defence_locked?: boolean;
    // Da quando la rosa di questa giornata e' quella che e' (R4). Null finche'
    // il turno non e' cominciato, cioe' quasi sempre.
    roster_frozen_at?: string | null;
    defence_count?: number | null;
  };
}

export interface SaveTeamLineupRequest {
  matchday: number;
  competition?: number | null;
  all_competitions?: boolean;
  gk_player_id: number | null;
  starter_player_ids: number[];
  bench_player_ids: number[];
}
