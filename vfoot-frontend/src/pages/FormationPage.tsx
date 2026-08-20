import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import { getLeagueMatchdays, getTeamLineup, saveTeamLineup } from '../api';
import Jersey, { kitFromCrest, type Kit } from '../components/Jersey';
import { useLeagueContext } from '../league/LeagueContext';
import { useCompetitionContext } from '../league/CompetitionContext';
import type {
  ClassicConstraints,
  PlayerRole,
  TeamLineupContext,
  TeamLineupPlayer,
} from '../types/lineup';

const XI = 11; // starters incl. exactly one goalkeeper

const ROLE_LABEL: Record<PlayerRole, string> = { GK: 'POR', DEF: 'DIF', MID: 'CEN', ATT: 'ATT' };
// Spelled out for the empty places: "Manca un DIF" reads like a code, "manca un
// difensore" reads like a sentence.
const ROLE_WORD: Record<PlayerRole, string> = {
  GK: 'portiere',
  DEF: 'difensore',
  MID: 'centrocampista',
  ATT: 'attaccante',
};
const ROLE_WORD_PLURAL: Record<PlayerRole, string> = {
  GK: 'portieri',
  DEF: 'difensori',
  MID: 'centrocampisti',
  ATT: 'attaccanti',
};
const ROLE_LABEL_SHORT = ROLE_LABEL;
const ROLE_CHIP: Record<PlayerRole, string> = {
  GK: 'bg-warn',
  DEF: 'bg-blue-500',
  MID: 'bg-good',
  ATT: 'bg-orange-500',
};
const ROLE_ORDER: Record<PlayerRole, number> = { GK: 0, DEF: 1, MID: 2, ATT: 3 }; // P, D, C, A
const ROLES: PlayerRole[] = ['GK', 'DEF', 'MID', 'ATT'];

/** TUTTI I MODULI LEGALI, che sono otto e non un numero a caso: sono esattamente
 *  le terne che rispettano i vincoli classic (difesa 3–5, centrocampo 0–5,
 *  attacco 1–3, dieci di movimento). Con la rosa 3-8-8-6 sono sempre tutti
 *  raggiungibili, quindi nessuno di questi bottoni è mai una porta chiusa per
 *  colpa della rosa — solo, eventualmente, per colpa dei congelati. */
const MODULES: Array<[number, number, number]> = [
  [3, 4, 3], [3, 5, 2], [4, 3, 3], [4, 4, 2], [4, 5, 1], [5, 2, 3], [5, 3, 2], [5, 4, 1],
];
const moduleName = (m: [number, number, number]) => m.join('-');

// Mirror of vfoot/services/formation_rules.validate_classic_lineup — the server
// validates identically; this is the live UI guide. Returns Italian violations.
function validateClassic(roles: PlayerRole[], c: ClassicConstraints): string[] {
  const errs: string[] = [];
  if (roles.length !== c.starters) errs.push(`Servono esattamente ${c.starters} titolari (ne hai ${roles.length}).`);
  const cnt: Record<PlayerRole, number> = { GK: 0, DEF: 0, MID: 0, ATT: 0 };
  roles.forEach((r) => (cnt[r] += 1));
  if (cnt.GK !== 1) errs.push(cnt.GK === 0 ? 'Manca il portiere.' : 'Un solo portiere fra i titolari.');
  if (cnt.DEF < c.per_role.DEF.min) errs.push(`Almeno ${c.per_role.DEF.min} difensori (ne hai ${cnt.DEF}).`);
  if (cnt.ATT < c.per_role.ATT.min) errs.push(`Almeno ${c.per_role.ATT.min} attaccante (ne hai ${cnt.ATT}).`);
  if (cnt.ATT > c.per_role.ATT.max) errs.push(`Al massimo ${c.per_role.ATT.max} attaccanti (ne hai ${cnt.ATT}).`);
  (['DEF', 'MID'] as PlayerRole[]).forEach((role) => {
    if (cnt[role] > c.per_role[role].max)
      errs.push(`Meno di 6 ${ROLE_LABEL[role]} (${c.per_role[role].max} max, ne hai ${cnt[role]}).`);
  });
  return errs;
}

// Why a bench player cannot go on the pitch RIGHT NOW, or null if he can.
//
// These are the same rules validateClassic checks, only asked one player AHEAD:
// telling a manager that his XI is illegal once he has built it means he has to
// undo his own work to find out what was wrong. Asked here, the illegal lineup is
// never built and the reason arrives on the row he is clicking.
function promotionBlock(
  p: TeamLineupPlayer,
  starters: TeamLineupPlayer[],
  benchPool: TeamLineupPlayer[],
  c: ClassicConstraints | null,
): string | null {
  if (starters.length >= XI) return 'Undici completo: manda prima un titolare in panchina.';
  const cnt: Record<PlayerRole, number> = { GK: 0, DEF: 0, MID: 0, ATT: 0 };
  starters.forEach((s) => (cnt[s.role] += 1));
  // One goalkeeper, in both modes.
  if (p.role === 'GK' && cnt.GK >= 1) return 'C’è già un portiere fra i titolari: mandalo in panchina prima.';
  if (!c) return null; // aura: any shape is legal
  const max = c.per_role[p.role].max;
  if (cnt[p.role] >= max) return `Hai già ${max} ${ROLE_WORD_PLURAL[p.role]}: è il massimo.`;
  // A minimum is never broken by the pick itself, but by the PLACE it takes up:
  // with a defender still to come and one place left, a third attacker is already
  // an illegal eleven — it just does not look like one yet.
  cnt[p.role] += 1;
  const free = XI - (starters.length + 1);
  const missing: string[] = [];
  let needed = 0;
  (ROLES).forEach((r) => {
    // Only count what the bench can actually supply: a squad genuinely short of
    // defenders must still be allowed to field eleven players.
    const spare = benchPool.filter((b) => b.role === r && b.player_id !== p.player_id).length;
    const n = Math.min(Math.max(0, c.per_role[r].min - cnt[r]), spare);
    if (n > 0) {
      needed += n;
      missing.push(`${n} ${n === 1 ? ROLE_WORD[r] : ROLE_WORD_PLURAL[r]}`);
    }
  });
  if (needed > free) {
    const left =
      free === 0 ? 'Non resterebbe nessun posto' : free === 1 ? 'Resterebbe un solo posto' : `Resterebbero ${free} posti`;
    return `${left} e ${needed === 1 ? 'ti serve' : 'ti servono'} ancora ${missing.join(' e ')}.`;
  }
  return null;
}

// Bench player_ids in priority order: honour `seed` first (saved/explicit order),
// then append any remaining non-starter roster player (role order P/D/C/A, best form
// first) so nobody is ever dropped from the payload.
function orderBench(roster: TeamLineupPlayer[], starterIds: number[], seed: number[]): number[] {
  const starterSet = new Set(starterIds);
  const cand = new Map(roster.filter((p) => !starterSet.has(p.player_id)).map((p) => [p.player_id, p]));
  const out: number[] = [];
  for (const id of seed) {
    if (cand.has(id) && !out.includes(id)) out.push(id);
  }
  const rest = [...cand.values()]
    .filter((p) => !out.includes(p.player_id))
    .sort((a, b) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role] || b.form - a.form);
  return [...out, ...rest.map((p) => p.player_id)];
}

/** Put the frozen players back on their own bench numbers.
 *
 *  Under the per-player deadline a bench slot BELONGS to the player whose match has
 *  started: the third place stays his, at that number, because how many players sit
 *  ahead of him is what decides whether he comes on. So every edit is normalised
 *  through here — the free players fill the remaining slots in their own order, and
 *  the frozen ones are put back where they were. Without this a promotion two rows
 *  above would silently slide a frozen man down a place, and the save would refuse
 *  an edit the manager had no way of seeing was illegal. */
function pinFrozen(order: number[], slots: Map<number, number>): number[] {
  if (!slots.size) return order;
  const frozen = new Set(slots.values());
  const free = order.filter((id) => !frozen.has(id));
  const total = free.length + slots.size;
  const out: number[] = [];
  let f = 0;
  for (let i = 0; i < total; i++) {
    const pinned = slots.get(i);
    if (pinned != null) out.push(pinned);
    else if (f < free.length) out.push(free[f++]);
  }
  // A frozen slot past the end of a shortened bench would be dropped by the loop;
  // append rather than lose the player, and let the save speak if it matters.
  for (const id of frozen) if (!out.includes(id)) out.push(id);
  return out;
}

// Kick-off of the real fixture; the provider ships a placeholder time until the
// slot is actually assigned, so we say so rather than showing a made-up hour.
/** The deadline, as a manager reads a date: "domenica 8 feb, 20:45". */
function fmtDeadline(iso: string | null | undefined): string {
  if (!iso) return 'orario da definire';
  return new Date(iso).toLocaleString('it-IT', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function fmtKickoff(nm: { kickoff: string | null; kickoff_provisional: boolean }): string {
  if (!nm.kickoff || nm.kickoff_provisional) return 'orario da definire';
  return new Date(nm.kickoff).toLocaleString('it-IT', {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// "Inter - Monza": the real fixture in home-away order, so the player's own club is
// visible too, not just the opponent.
function fixtureLabel(nm: { team: string; opponent: string; home: boolean }): string {
  return nm.home ? `${nm.team} - ${nm.opponent}` : `${nm.opponent} - ${nm.team}`;
}

/** What to call a frozen player, which is a statement about his MATCH and not
 *  about him. He is frozen because his club has kicked off — he may be on the
 *  pitch, may have finished, and may never have come on at all, so "in campo" is
 *  true for only some of them and "ha giocato" for none of them for certain. */
function frozenLabel(nm?: { status: string } | null): string {
  if (nm?.status === 'live') return 'in campo';
  if (nm?.status === 'finished') return 'finita';
  return 'iniziata';
}

/** The same thing said in full, for the tooltip — there is room there. */
function frozenTitle(nm?: { status: string } | null): string {
  const what =
    nm?.status === 'live'
      ? 'La sua partita è in corso'
      : nm?.status === 'finished'
        ? 'La sua partita è finita'
        : 'La sua partita è iniziata';
  return `${what}: resta dov'è.`;
}

function PlayerDetails({ p }: { p: TeamLineupPlayer }) {
  const nm = p.next_match;
  return (
    <span className="mt-1 block rounded-lg bg-surface-2 px-2 py-1 text-[11px] text-ink-soft">
      {nm ? (
        <span className="block">
          {nm.home ? (
            <>
              <b className="text-ink">{nm.team}</b> - {nm.opponent}
            </>
          ) : (
            <>
              {nm.opponent} - <b className="text-ink">{nm.team}</b>
            </>
          )}
          <span className="text-ink-faint"> · {fmtKickoff(nm)}</span>
        </span>
      ) : null}
      {p.minutes_label === 'unknown' ? (
        <span className="block text-ink-faint">nessuno storico di impiego</span>
      ) : (
        <span className="block">
          {p.appearances} pres · {p.avg_minutes}′ medi
          {p.minutes_label === 'low' ? <Badge tone="amber"> poco impiegato</Badge> : null}
          {p.minutes_label === 'high' ? <Badge tone="green"> titolare abituale</Badge> : null}
        </span>
      )}
      {p.stats_season ? <span className="block text-ink-faint">dati: {p.stats_season}</span> : null}
    </span>
  );
}

export default function FormationPage() {
  const { selectedLeagueId } = useLeagueContext();
  const { selectedCompetitionId, setSelectedCompetitionId, competitions } = useCompetitionContext();
  const [searchParams, setSearchParams] = useSearchParams();
  const competition = searchParams.get('competition') ? Number(searchParams.get('competition')) : null;
  const matchday = searchParams.get('matchday') ? Number(searchParams.get('matchday')) : null;

  /** LA PAGINA E IL MENU IN ALTO PARLANO DELLA STESSA COMPETIZIONE.
   *
   *  Dalla home si clicca «Formazione · champ» e si arriva qui sulla formazione
   *  di champ — ma il selettore in cima continuava a mostrare quella di prima, e
   *  da lì in poi il menu di sinistra («Partite», «Classifica») portava a
   *  un'altra competizione ancora. Il contesto non era sbagliato: nessuno gliela
   *  diceva.
   *
   *  Nei due versi, perché il disallineamento nasceva da entrambi:
   *  · c'è un `?competition=` nell'indirizzo (si è arrivati da una scorciatoia,
   *    o si è usato il menu a tendina qui dentro) → è quella la competizione, e
   *    il selettore in alto la adotta;
   *  · non c'è (si è aperta la pagina dal menu) → si parte da quella scelta in
   *    alto, invece di lasciar decidere al server. */
  useEffect(() => {
    if (competition == null) return;
    if (!competitions.some((c) => c.competition_id === competition)) return;
    if (competition !== selectedCompetitionId) setSelectedCompetitionId(competition);
  }, [competition, competitions, selectedCompetitionId, setSelectedCompetitionId]);

  const [ctx, setCtx] = useState<TeamLineupContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [starterIds, setStarterIds] = useState<number[]>([]);
  // Explicit, ordered bench = substitution priority. Always stored (even in Aura,
  // where the substitute is the best available and order only breaks ties).
  const [benchOrder, setBenchOrder] = useState<number[]>([]);

  const [dragId, setDragId] = useState<number | null>(null);
  // L'ordine COME SI VEDRÀ, mentre il dito è ancora giù: senza, si trascina al
  // buio e si scopre dove è finito solo lasciando la presa.
  const [dragPreview, setDragPreview] = useState<number[] | null>(null);
  const benchRowEls = useRef(new Map<number, HTMLElement>());
  const pressTimer = useRef<number | null>(null);
  const pressFrom = useRef<{ x: number; y: number; id: number } | null>(null);
  const blockScroll = useRef((e: TouchEvent) => e.preventDefault()).current;

  // Places left open by a demoted starter, in the order they were vacated. They
  // are what keeps the pitch at eleven while the module is still being decided.
  const [vacancies, setVacancies] = useState<PlayerRole[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  // Il posto vuoto che è stato toccato: apre l'elenco di chi può occuparlo.
  const [picking, setPicking] = useState<PlayerRole | null>(null);
  // Perché un cambio di modulo è stato rifiutato. Non passa da `refused`, che è
  // ancorato a una riga: questo riguarda la squadra intera.
  const [moduleNote, setModuleNote] = useState<string | null>(null);
  // Why the last attempted promotion was refused, pinned to the row that was
  // clicked — the explanation belongs where the finger is, not in the header.
  const [refused, setRefused] = useState<{ player_id: number; reason: string } | null>(null);
  // Which bench numbers belong to a player whose match has started. Taken from the
  // SAVED lineup, because that is what the server compares a submission against.
  // The XI has no equivalent: its order is derived server-side (P-D-C-A, frozen
  // players kept inside their own role), so the page has nothing to preserve there.
  const [frozenSlots, setFrozenSlots] = useState<Map<number, number>>(new Map());
  const [allComps, setAllComps] = useState(false);
  /** LA GIORNATA DA SCHIERARE, quando nessuno ne ha chiesta una.
   *
   *  Finché a questa pagina si arrivava solo da una scorciatoia — «Schiera la
   *  formazione» sulla home, il link sul calendario — l'indirizzo portava sempre
   *  la giornata giusta, e i due default che restavano sotto non li vedeva
   *  nessuno: il server risponde `matchdays[0]`, la prima della stagione, e qui
   *  si sceglieva quella di mezzo. Erano default da esplorazione, ottimi per
   *  guardarsi una giornata qualunque a stagione ferma.
   *
   *  Adesso «Formazione» è una voce di menu, e una voce di menu si apre per fare
   *  il lavoro di questa settimana: aprirla sulla diciannovesima, chiusa da mesi,
   *  la rende una porta su un vicolo. `is_fieldable` è la stessa domanda che si
   *  fa la home per dire «prossima da schierare», e la risposta è una sola per
   *  tutta la lega. */
  const [fieldableMd, setFieldableMd] = useState<number | null>(null);
  // «Chiesto e ottenuto risposta», che non è «ne ho trovata una»: a stagione
  // finita la risposta legittima è «nessuna», e va distinta dal non aver ancora
  // chiesto — altrimenti la fetch qui sotto parte per prima, sceglie il default
  // di ripiego, e quando la risposta arriva la giornata è ormai nell'indirizzo e
  // non la corregge più nessuno.
  const [fieldableAsked, setFieldableAsked] = useState(false);
  useEffect(() => {
    if (!selectedLeagueId) return;
    let alive = true;
    void getLeagueMatchdays(selectedLeagueId)
      .then((mds) => {
        if (!alive) return;
        const md = mds.find((m) => m.is_fieldable) ?? null;
        setFieldableMd(md ? md.real_matchday : null);
      })
      .catch(() => {})
      .finally(() => {
        if (alive) setFieldableAsked(true);
      });
    return () => {
      alive = false;
    };
  }, [selectedLeagueId]);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const setParams = (next: { competition?: number; matchday?: number }) => {
    const p = new URLSearchParams(searchParams);
    if (next.competition != null) p.set('competition', String(next.competition));
    if (next.matchday != null) p.set('matchday', String(next.matchday));
    setSearchParams(p, { replace: true });
  };

  // Suggestion / default: a balanced 4-4-2 by inferred role, each slot the best
  // available by recent form (falls back across roles if a line is short).
  //
  // `frozen` is the per-player deadline reaching in here: those players are where
  // they are and the save will refuse to move them, so the suggestion must start
  // FROM them (`frozen.pinned`, kept in the XI) and never reach for the others
  // (`frozen.locked`, already playing and not currently fielded). Proposing a
  // lineup the save would then reject is the same mistake the role ceilings above
  // were added to avoid, arriving by a different road.
  const suggest = (
    roster: TeamLineupPlayer[],
    c: ClassicConstraints | null,
    frozen?: { pinned: number[]; locked: Set<number> },
  ): number[] => {
    const pinned = frozen?.pinned ?? [];
    const unavailable = frozen?.locked ?? new Set<number>();
    const pool = roster.filter(
      (p) => pinned.includes(p.player_id) || !unavailable.has(p.player_id),
    );
    const byForm = (a: TeamLineupPlayer, b: TeamLineupPlayer) => b.form - a.form;
    const pinnedGk = pinned.map((id) => pool.find((p) => p.player_id === id)).find((p) => p?.role === 'GK');
    const gk = pinnedGk ?? [...pool].filter((p) => p.role === 'GK').sort(byForm)[0];
    const chosen = new Set<number>();
    const cnt: Record<PlayerRole, number> = { GK: 0, DEF: 0, MID: 0, ATT: 0 };
    if (gk) {
      chosen.add(gk.player_id);
      cnt.GK = 1;
    }
    const targets: [PlayerRole, number][] = [['DEF', 4], ['MID', 4], ['ATT', 2]];
    const out: number[] = [];
    // The frozen outfielders take their places first: they are not a preference,
    // they are a fact.
    for (const id of pinned) {
      const p = pool.find((x) => x.player_id === id);
      if (!p || chosen.has(id) || p.role === 'GK') continue;
      chosen.add(id);
      cnt[p.role] += 1;
      out.push(id);
    }
    for (const [role, n] of targets) {
      pool
        .filter((p) => p.role === role && !chosen.has(p.player_id))
        .sort(byForm)
        .slice(0, Math.max(0, n - cnt[role]))
        .forEach((p) => {
          chosen.add(p.player_id);
          cnt[role] += 1;
          out.push(p.player_id);
        });
    }
    // Top up to 10 outfielders from whoever is left, by form — but never past a
    // role's ceiling: a short line used to be filled with a sixth midfielder, so
    // the suggestion itself proposed a lineup the save would then refuse.
    pool
      .filter((p) => p.role !== 'GK' && !chosen.has(p.player_id))
      .sort(byForm)
      .forEach((p) => {
        if (out.length < XI - 1 && (!c || cnt[p.role] < c.per_role[p.role].max)) {
          chosen.add(p.player_id);
          cnt[p.role] += 1;
          out.push(p.player_id);
        }
      });
    return gk ? [gk.player_id, ...out] : out;
  };

  useEffect(() => {
    if (!selectedLeagueId) return;
    // Senza giornata nell'indirizzo la si sta per SCEGLIERE, e la si sceglie
    // sapendo qual è quella da schierare.
    if (matchday == null && !fieldableAsked) return;
    setLoading(true);
    setError(null);
    void getTeamLineup(selectedLeagueId, matchday, competition)
      .then((d) => {
        setCtx(d);
        // First visit: pick the competition + a mid-season matchday, which
        // re-fetches as-of (no-leakage) profiles for that competition.
        if (competition == null || matchday == null) {
          setParams({
            // La competizione del menu in alto vince su quella che il server
            // sceglierebbe da sé: è ciò che l'utente sta guardando.
            competition: competition ?? selectedCompetitionId ?? d.competition ?? undefined,
            // La schierabile per prima; a stagione finita non ce n'è una, e
            // allora si ricade sul vecchio default di metà stagione.
            matchday:
              matchday ??
              (fieldableMd != null && d.matchdays.includes(fieldableMd) ? fieldableMd : undefined) ??
              d.matchdays[Math.floor(d.matchdays.length / 2)] ??
              d.matchday,
          });
          return;
        }
        const saved = d.saved_lineup;
        let starters: number[];
        if (saved && (saved.gk_player_id || saved.starter_player_ids.length)) {
          starters = [...(saved.gk_player_id ? [saved.gk_player_id] : []), ...saved.starter_player_ids].slice(0, XI);
        } else {
          // Nothing was ever submitted for this round. If it has already begun,
          // whoever is on the pitch is out of reach: proposing him would build an
          // XI the save can only refuse.
          starters = suggest(d.roster, d.mode === 'classic' ? d.rules.classic_constraints : null, {
            pinned: [],
            locked: new Set(d.lineup_lock?.locked_player_ids ?? []),
          });
        }
        const frozen = new Set(d.lineup_lock?.locked_player_ids ?? []);
        const slots = new Map<number, number>();
        (saved?.bench_player_ids ?? []).forEach((id, i) => {
          if (frozen.has(id)) slots.set(i, id);
        });
        setFrozenSlots(slots);
        setStarterIds(starters);
        setBenchOrder(pinFrozen(orderBench(d.roster, starters, saved?.bench_player_ids ?? []), slots));
        // A freshly loaded lineup has no vacated places: whatever it is short of
        // was never chosen, so there is no role to attribute the gap to.
        setVacancies([]);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [selectedLeagueId, competition, matchday, fieldableMd, fieldableAsked]);

  const byId = useMemo(() => new Map((ctx?.roster ?? []).map((p) => [p.player_id, p])), [ctx]);
  const gkStarters = useMemo(
    () => starterIds.filter((id) => byId.get(id)?.role === 'GK'),
    [starterIds, byId],
  );
  const gkId = gkStarters[0] ?? null;

  if (!selectedLeagueId) return <div className="text-sm text-ink-faint">Seleziona una lega per impostare la formazione.</div>;
  if (loading && !ctx) return <div className="text-sm text-ink-faint">Caricamento formazione…</div>;
  if (error || !ctx) return <div className="text-sm text-bad">Errore: {error ?? '…'}</div>;

  const isClassic = ctx.mode === 'classic';
  const constraints = ctx.rules.classic_constraints;

  // The deadline. Under the per-player lock a lineup is half decided and half not,
  // so the page cannot simply be open or shut: it has to say WHICH players are gone
  // and let the rest be edited. `closed` is the end of the argument — nothing left
  // to decide either way.
  const lock = ctx.lineup_lock;
  const lockedIds = new Set(lock?.locked_player_ids ?? []);
  const closed = !!lock?.closed;
  const lockedReason = 'La sua partita è già iniziata.';
  const closedReason = 'Giornata chiusa: la formazione non è più modificabile.';
  /** Why this row cannot be moved at all — null when it can. */
  const immutableReason = (id: number) =>
    closed ? closedReason : lockedIds.has(id) ? lockedReason : null;

  // Copying one lineup onto every competition is a convenience that stops being
  // safe the moment anybody is frozen. Each competition keeps its OWN lineup, so
  // the frozen players sit in DIFFERENT places in each: the eleven that is legal
  // for the championship can move a man who is already playing in the cup, and
  // since the save is all-or-nothing the whole thing would be refused. The
  // condition is "somebody of MINE has started", not "the round has started" — a
  // manager whose players all play on Monday can still copy on Sunday.
  //
  // "Somebody of mine" is the WHOLE roster and not just the eleven, because in
  // classic the bench is everyone else: 11 + 14 = 25, so every player owns a
  // numbered place in every competition's lineup and any frozen one can sit 3rd
  // here and 9th there.
  const multiSendBlocked = closed || lockedIds.size > 0;
  // With a single competition the offer means "send this to itself": noise, and
  // noise that reads as if there were somewhere else it could go.
  const manyCompetitions = ctx.competitions.length > 1;
  const sendAll = allComps && manyCompetitions && !multiSendBlocked;

  const chosen = starterIds.map((id) => byId.get(id)).filter((p): p is TeamLineupPlayer => !!p);
  const notChosen = ctx.roster.filter((p) => !starterIds.includes(p.player_id));
  const blockReasonFor = (p: TeamLineupPlayer) =>
    closed
      ? 'Giornata chiusa: la formazione non è più modificabile.'
      : lockedIds.has(p.player_id)
        ? lockedReason
        : promotionBlock(p, chosen, notChosen, isClassic ? constraints : null);

  // Toggling a player keeps the ordered bench in sync: a demoted starter joins the
  // bench at the LOWEST priority (end); a promoted bench player leaves it.
  //
  // It also keeps the ELEVEN visible. The module is not fixed up front, it is read
  // off the choices — so dropping a starter used to shrink his line and re-centre
  // the pitch, leaving nine or ten dots and no sign of what was missing. Instead
  // the vacated place stays, tagged with the role it came from.
  const toggleStarter = (id: number) => {
    const player = byId.get(id);
    const role = player?.role;
    // Frozen players are refused in BOTH directions. Demotion is the one that
    // matters: promotion already goes through blockReasonFor, but a striker who is
    // playing right now must not be benchable either.
    if (closed || lockedIds.has(id)) {
      setRefused({
        player_id: id,
        reason: closed ? 'Giornata chiusa: la formazione non è più modificabile.' : lockedReason,
      });
      return;
    }
    if (starterIds.includes(id)) {
      setStarterIds((s) => s.filter((x) => x !== id));
      setBenchOrder((b) => pinFrozen(b.includes(id) ? b : [...b, id], frozenSlots));
      if (role) setVacancies((v) => [...v, role]);
      setRefused(null);
    } else {
      // Refuse the move rather than accept it and condemn the lineup: the same
      // rules the save enforces, applied to this one player, with the reason.
      const reason = player ? blockReasonFor(player) : null;
      if (reason) {
        setRefused({ player_id: id, reason });
        return;
      }
      setRefused(null);
      setStarterIds((s) => [...s, id]);
      setBenchOrder((b) => pinFrozen(b.filter((x) => x !== id), frozenSlots));
      setVacancies((v) => {
        // Same role => he takes the place that was left open and the module is
        // unchanged. A different role => that place becomes his, which IS a change
        // of module: the oldest vacancy is the one that gives way.
        const same = role ? v.indexOf(role) : -1;
        const drop = same >= 0 ? same : 0;
        return v.length ? [...v.slice(0, drop), ...v.slice(drop + 1)] : v;
      });
    }
  };

  // -- trascinare la panchina ---------------------------------------------
  //
  // Il pollice al posto dei due pulsantini: su un telefono «terzo, no quarto,
  // no sesto» sono cinque tocchi su bersagli da sedici pixel, mentre l'ordine
  // della panchina è una cosa che si pensa guardandola tutta insieme.
  //
  // Pointer events e non l'HTML5 drag-and-drop, che sul touch semplicemente non
  // esiste: `dragstart` non parte da un dito. Questi eventi sono gli stessi per
  // mouse, dito e pennino, quindi il comportamento è uno solo e non due scritti
  // due volte.

  /** Sposta `id` alla riga `visibleIndex`, LASCIANDO FERMI I CONGELATI.
   *
   *  Il posto di chi ha la partita in corso è suo e non si tocca: non scende di
   *  una perché qualcuno gli è passato davanti, e nessuno lo scavalca. Quindi il
   *  riordino avviene fra i soli liberi, che poi riempiono le caselle rimaste
   *  libere nell'ordine nuovo.
   *
   *  Le posizioni dei congelati si rileggono DALL'ORDINE CORRENTE e non da
   *  `frozenSlots`, che è la memoria di una formazione già inviata: chi apre la
   *  pagina a giornata cominciata e non aveva ancora schierato ha una panchina
   *  piena di posti fissati e quella mappa vuota. Fidandosi di lei, il riordino
   *  perdeva per strada tutti i congelati — quindici righe diventavano due. */
  const reorderBench = (order: number[], id: number, visibleIndex: number): number[] => {
    const free = order.filter((x) => !lockedIds.has(x));
    const from = free.indexOf(id);
    if (from < 0) return order;
    // L'indice VISIBILE conta anche i congelati; quello che serve è quanti liberi
    // stanno sopra la riga puntata.
    const freeAbove = order.slice(0, Math.max(0, visibleIndex)).filter((x) => !lockedIds.has(x)).length;
    const to = Math.max(0, Math.min(free.length - 1, freeAbove > from ? freeAbove - 1 : freeAbove));
    if (to === from) return order;
    const moved = [...free];
    moved.splice(from, 1);
    moved.splice(to, 0, id);
    let f = 0;
    return order.map((x) => (lockedIds.has(x) ? x : moved[f++]));
  };

  const dragMoveTo = (clientY: number) => {
    if (dragId == null) return;
    const current = dragPreview ?? benchIds;
    // La riga sotto il dito: si confronta col CENTRO di ognuna, che è il punto in
    // cui l'occhio decide che il giocatore sta «lì».
    let target = current.length - 1;
    for (let i = 0; i < current.length; i++) {
      const el = benchRowEls.current.get(current[i]);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (clientY < r.top + r.height / 2) {
        target = i;
        break;
      }
    }
    const next = reorderBench(current, dragId, target);
    if (next !== current) setDragPreview(next);
  };

  /** LA PRESSIONE LUNGA AL POSTO DELLE FRECCETTE.
   *
   *  Le due freccette erano bersagli da 21×11 pixel: sotto qualunque soglia
   *  ragionevole, ed e' il motivo per cui gli utenti scrivono che l'ordine della
   *  panchina «non si puo' cambiare». La maniglia da 20×16 accanto non stava
   *  meglio. Ora la presa e' la RIGA INTERA, dopo un quarto di secondo di dito
   *  fermo — il gesto che qualunque telefono usa per riordinare una lista.
   *
   *  Il tempo distingue le due cose che un dito puo' voler fare partendo dalla
   *  stessa riga: se si muove prima della soglia sta scorrendo la pagina e il
   *  gesto si annulla; se resta fermo vuole quella riga. Otto pixel di tolleranza
   *  perche' un dito fermo non e' mai fermo davvero.
   *
   *  Lo scorrimento durante il trascinamento lo blocca un listener su `touchmove`
   *  non passivo, e non `touch-action`: quest'ultimo va deciso PRIMA che il gesto
   *  cominci, e qui al momento del `pointerdown` non sappiamo ancora se sara' un
   *  trascinamento o una scorsa. */
  const cancelPress = () => {
    if (pressTimer.current != null) {
      clearTimeout(pressTimer.current);
      pressTimer.current = null;
    }
    pressFrom.current = null;
  };

  const rowPointerDown = (id: number) => (e: React.PointerEvent) => {
    // I comandi dentro la riga restano comandi: un tocco sul segmentato non deve
    // diventare ne' una selezione ne' l'inizio di un trascinamento.
    if ((e.target as HTMLElement).closest('button')) return;
    if (immutableReason(id)) return; // il suo posto e' fissato: niente presa
    // Senza questo il dito (o il mouse) tenuto fermo su una riga avvia la
    // SELEZIONE DEL TESTO: il nome si evidenzia, il browser prende in mano il
    // gesto per conto suo e i pointermove che dovrebbero riordinare la lista
    // vanno a muovere un'ancora di selezione.
    e.preventDefault();
    const el = e.currentTarget as HTMLElement;
    const pointerId = e.pointerId;
    pressFrom.current = { x: e.clientX, y: e.clientY, id };
    pressTimer.current = window.setTimeout(() => {
      pressTimer.current = null;
      try {
        el.setPointerCapture(pointerId);
      } catch {
        /* il puntatore puo' essere gia' sparito: il trascinamento parte lo stesso */
      }
      document.addEventListener('touchmove', blockScroll, { passive: false });
      setDragId(id);
      setDragPreview(benchIds);
    }, 250);
  };

  const rowPointerMove = (e: React.PointerEvent) => {
    if (dragId != null) {
      dragMoveTo(e.clientY);
      return;
    }
    const from = pressFrom.current;
    if (!from) return;
    if (Math.abs(e.clientY - from.y) > 8 || Math.abs(e.clientX - from.x) > 8) cancelPress();
  };

  const rowPointerUp = (id: number) => (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest('button')) return;
    // Dito alzato prima della soglia e senza esserci mosso: era un tocco, e un
    // tocco su un panchinaro apre la sua scheda.
    const wasPress = pressTimer.current != null && pressFrom.current?.id === id;
    cancelPress();
    if (dragId != null) {
      dragEnd();
      return;
    }
    if (wasPress) {
      setPicking(null);
      setSelected((sel) => (sel === id ? null : id));
    }
  };

  const dragEnd = () => {
    document.removeEventListener('touchmove', blockScroll);
    cancelPress();
    if (dragPreview) setBenchOrder(dragPreview);
    setDragId(null);
    setDragPreview(null);
  };

  /** «Fai entrare per primo»: il gesto che copre il caso vero. L'ordine fine si
   *  trascina, ma nove volte su dieci quello che si vuole è che UNO entri prima
   *  degli altri, e per quello un tocco basta. Passa da `reorderBench`, quindi i
   *  posti fissati restano fissati: chi ha la partita in corso non si sposta e
   *  non viene scavalcato. */
  const benchToTop = (id: number) => {
    const why = immutableReason(id);
    if (why) {
      setRefused({ player_id: id, reason: closed ? closedReason : "Il suo posto in panchina è fissato: la sua partita è iniziata." });
      return;
    }
    setRefused(null);
    setBenchOrder((b) => reorderBench(pinFrozen(orderBench(ctx.roster, starterIds, b), frozenSlots), id, 0));
  };

  const starterRoles = starterIds.map((id) => byId.get(id)?.role).filter((r): r is PlayerRole => !!r);
  const classicErrors = isClassic && constraints ? validateClassic(starterRoles, constraints) : [];
  const gkOk = gkStarters.length === 1;
  const canSave = starterIds.length === XI && gkOk && classicErrors.length === 0 && !closed;
  const saveBlock = canSave
    ? null
    : closed
      ? 'La giornata è chiusa: la formazione non è più modificabile.'
      : classicErrors[0] ??
      (starterIds.length !== XI
        ? `Servono ${XI} titolari (ne hai ${starterIds.length}).`
        : gkStarters.length === 0
          ? 'Manca il portiere.'
          : 'Un solo portiere fra i titolari.');

  /** IL MODULO COME SI LEGGE ADESSO — dagli undici in campo, buchi compresi.
   *
   *  Non c'è nessun modulo memorizzato da nessuna parte, ed è deliberato: se
   *  esistesse un'intenzione salvata potrebbe divergere dai fatti, e allora
   *  l'etichetta mentirebbe. Le pastiglie qui sotto non sono una modalità, sono
   *  un'AZIONE — «portami a 4-4-2» — e un attimo dopo il modulo torna a essere
   *  soltanto quello che si vede in campo. */
  const lineCount = (role: PlayerRole) =>
    starterIds.filter((id) => byId.get(id)?.role === role).length
    + vacancies.filter((v) => v === role).length;
  const currentModule: [number, number, number] = [lineCount('DEF'), lineCount('MID'), lineCount('ATT')];

  /** Portare la squadra a un modulo, in modo conservativo: si TOGLIE l'eccedenza
   *  e si aprono i posti mancanti, non si aggiunge nessuno da sé. Chi esce è
   *  l'ultimo della linea — che essendo ordinata per forma è il peggiore — e chi
   *  ha la partita in corso non esce affatto.
   *
   *  Tutto o niente: se i congelati di un reparto sono più di quanti il modulo ne
   *  preveda, il cambio non si fa a metà, si rifiuta e dice perché. Restare fra
   *  due moduli sarebbe peggio di non essersi mossi. */
  const applyModule = (m: [number, number, number]) => {
    const target: Record<PlayerRole, number> = { GK: 1, DEF: m[0], MID: m[1], ATT: m[2] };
    const keep: number[] = [];
    const dropped: number[] = [];
    const holes: PlayerRole[] = [];
    for (const role of ROLES) {
      const line = starterIds
        .map((id) => byId.get(id))
        .filter((p): p is TeamLineupPlayer => !!p && p.role === role)
        .sort((a, b) => b.form - a.form); // il migliore per primo, l'ultimo è quello che esce
      const frozen = line.filter((p) => lockedIds.has(p.player_id));
      const free = line.filter((p) => !lockedIds.has(p.player_id));
      const want = target[role];
      if (frozen.length > want) {
        setModuleNote(
          `Non puoi passare a ${moduleName(m)}: hai ${frozen.length} ${ROLE_WORD_PLURAL[role]} `
          + 'con la partita già iniziata, e restano dove sono.',
        );
        return;
      }
      const room = Math.max(0, want - frozen.length);
      keep.push(...frozen.map((p) => p.player_id), ...free.slice(0, room).map((p) => p.player_id));
      dropped.push(...free.slice(room).map((p) => p.player_id));
      for (let k = frozen.length + Math.min(room, free.length); k < want; k++) holes.push(role);
    }
    setModuleNote(null);
    setRefused(null);
    setStarterIds(keep);
    // I retrocessi in coda alla panchina, non sparsi per ruolo: chi esce dal
    // campo è l'ultimo che si vuol far rientrare.
    setBenchOrder((b) => pinFrozen(orderBench(ctx.roster, keep, [...b, ...dropped]), frozenSlots));
    setVacancies(holes);
  };

  // Estratto perché lo chiamano due bottoni: quello in cima su desktop e quello
  // nella barra in fondo sul telefono.
  const onSuggest = () => {
    setStarterIds(
      suggest(ctx.roster, isClassic ? constraints : null, {
        pinned: starterIds.filter((id) => lockedIds.has(id)),
        locked: lockedIds,
      }),
    );
    setVacancies([]);
    setRefused(null);
  };

  const onSave = async () => {
    if (!canSave || !selectedLeagueId || matchday == null) return;
    setSaving(true);
    try {
      // Send the bench in PRIORITY order (substitution order); append any roster
      // player not yet placed so nobody is dropped from the payload.
      const benchIds = pinFrozen(orderBench(ctx.roster, starterIds, benchOrder), frozenSlots);
      const res = await saveTeamLineup(selectedLeagueId, {
        matchday,
        competition: sendAll ? null : competition,
        all_competitions: sendAll,
        gk_player_id: gkId,
        // Sent in the order the page shows them; the server derives the stored one
        // anyway (P-D-C-A, frozen players kept inside their role), so this is about
        // the payload reading like the screen, not about deciding anything.
        starter_player_ids: starters.map((p) => p.player_id).filter((id) => id !== gkId),
        bench_player_ids: benchIds,
      });
      setToast(sendAll ? `Formazione salvata su ${res.saved_competitions} competizioni ✓` : 'Formazione salvata ✓');
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Errore nel salvataggio');
    } finally {
      setSaving(false);
      setTimeout(() => setToast(null), 2800);
    }
  };

  const byRole = (a: TeamLineupPlayer, b: TeamLineupPlayer) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role] || b.form - a.form;
  const starters = ctx.roster.filter((p) => starterIds.includes(p.player_id)).sort(byRole);
  const benchIds = pinFrozen(orderBench(ctx.roster, starterIds, benchOrder), frozenSlots);
  const bench = benchIds.map((id) => byId.get(id)).filter((p): p is TeamLineupPlayer => !!p);
  // Mentre il dito è giù si mostra l'anteprima, non l'ordine salvato: è il senso
  // stesso del trascinare, vedere dove sta andando prima di lasciare.
  const shownBench = (dragPreview ?? benchIds)
    .map((id) => byId.get(id))
    .filter((p): p is TeamLineupPlayer => !!p);
  const compName = ctx.competitions.find((c) => c.competition_id === competition)?.name;
  const selectedPlayer = selected != null ? byId.get(selected) ?? null : null;
  const kits = kitFromCrest(ctx.team.crest, ctx.team.name);

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <SectionTitle>Formazione · {ctx.team.name}</SectionTitle>
              <Badge tone={isClassic ? 'blue' : 'green'}>{isClassic ? 'Classic' : 'Aura'}</Badge>
            </div>
            <div className="mt-1 text-sm text-ink-soft">
              {compName ? <>Competizione <b>{compName}</b></> : null}
              {/* Il contatore sul telefono sta nella barra in fondo, accanto al
                  Salva che dipende da lui: qui sarebbe la stessa cifra due volte. */}
              <span className="hidden lg:inline">{compName ? ' · ' : null}titolari {starterIds.length}/{XI}</span>
              {!isClassic && gkStarters.length !== 1 ? (
                <span className="ml-2 font-semibold text-bad">
                  {gkStarters.length === 0 ? '· manca il portiere' : '· un solo portiere consentito'}
                </span>
              ) : null}
            </div>
            {isClassic ? (
              <div className="mt-1 hidden text-[11px] text-ink-faint lg:block">
                Vincoli: 1 portiere · almeno 3 difensori · 1–3 attaccanti · meno di 6 per reparto · 11 totali.
              </div>
            ) : null}
            {isClassic && classicErrors.length ? (
              <ul className="mt-1 list-disc pl-4 text-[11px] font-semibold text-bad">
                {classicErrors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            ) : null}
            {lock?.enforced ? (
              <div
                className={`mt-1 text-[11px] ${closed ? 'font-semibold text-bad' : 'text-ink-faint'}`}
              >
                {closed
                  ? 'Giornata chiusa: la formazione non è più modificabile.'
                  : lock.mode === 'player'
                    ? lockedIds.size
                      ? `${lockedIds.size} giocatori hanno la partita iniziata e restano dove sono; sugli altri puoi decidere fino a ${fmtDeadline(lock.closes_at)}.`
                      : `Ogni giocatore si blocca all'inizio della sua partita. Ultimo calcio d'inizio: ${fmtDeadline(lock.closes_at)}.`
                    : `La formazione si blocca al primo calcio d'inizio della giornata: ${fmtDeadline(lock.closes_at)}.`}
              </div>
            ) : null}
            {/* Which round the numbers on this page describe. It used to add "nessuna
                informazione futura" in warning amber — a note to ourselves from when
                the season was a replay and the worry was leakage. To a manager it
                answers a question nobody asked, in the colour of a problem. */}
            {ctx.as_of_matchday != null && ctx.as_of_matchday > 1 ? (
              <div className="mt-1 text-[11px] text-ink-faint">
                Medie e statistiche aggiornate alla giornata {ctx.as_of_matchday - 1}.
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {ctx.competitions.length > 1 ? (
              <select
                value={competition ?? ''}
                onChange={(e) => setParams({ competition: Number(e.target.value) })}
                className="rounded-lg border border-line px-2 py-1 text-sm"
              >
                {ctx.competitions.map((c) => (
                  <option key={c.competition_id} value={c.competition_id}>
                    {c.name}
                  </option>
                ))}
              </select>
            ) : null}
            <label className="text-xs text-ink-faint">Giornata</label>
            <select
              value={matchday ?? ''}
              onChange={(e) => setParams({ matchday: Number(e.target.value) })}
              className="rounded-lg border border-line px-2 py-1 text-sm"
            >
              {ctx.matchdays.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            {/* Su desktop i due comandi stanno qui, in cima, accanto ai selettori:
                la pagina è a due colonne e il pollice non c'entra. Sul telefono
                stanno nella barra in fondo (v. in coda al file) — qui erano fino a
                2500px sopra il punto in cui si lavora. */}
            <div className="hidden items-center gap-2 lg:flex">
              <Button
                variant="secondary"
                onClick={onSuggest}
              >
                Suggerisci XI
              </Button>
              {/* A grey Salva that does not say why is a dead end: the tooltip carries
                  the first thing standing in the way. */}
              <Button onClick={onSave} disabled={!canSave || saving} title={canSave ? undefined : saveBlock ?? undefined}>
                {saving ? 'Salvataggio…' : 'Salva'}
              </Button>
            </div>
          </div>
        </div>
        {/* LE PASTIGLIE DEL MODULO.
         *
         *  Molti impostano il modulo PRIMA, e non hanno il riflesso che panchinare
         *  un attaccante liberi il posto per un centrocampista: il modulo qui si è
         *  sempre letto dalle scelte, mai scelto, e chi arriva dal fantacalcio
         *  classico cercava «4-4-2» senza trovarlo nemmeno scritto.
         *
         *  Restano tutte e due le strade: questa non toglie niente a chi ragiona
         *  per giocatori, perché non memorizza nessuna intenzione — tocchi, la
         *  squadra si dispone, e da lì in poi il modulo torna a essere solo quello
         *  che si vede in campo. */}
        {isClassic ? (
          <div className="mt-3 border-t border-line pt-2">
            <div className="flex items-baseline gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">Modulo</span>
              <span className="text-sm font-bold tabular-nums">{moduleName(currentModule)}</span>
            </div>
            <div className="-mx-1 mt-1 flex gap-1.5 overflow-x-auto px-1 pb-1" style={{ scrollbarWidth: 'none' }}>
              {MODULES.map((m) => {
                const active = moduleName(m) === moduleName(currentModule);
                return (
                  <button
                    key={moduleName(m)}
                    type="button"
                    onClick={() => applyModule(m)}
                    aria-pressed={active}
                    disabled={closed}
                    className={clsx(
                      'shrink-0 rounded-full border px-3 py-1.5 text-xs font-bold tabular-nums transition',
                      active
                        ? 'border-brand bg-brand text-on-brand'
                        : 'border-line bg-surface text-ink-soft hover:bg-surface-2',
                      closed && 'cursor-not-allowed opacity-50',
                    )}
                  >
                    {moduleName(m)}
                  </button>
                );
              })}
            </div>
            {moduleNote ? (
              <div className="mt-1 text-[11px] font-semibold text-bad">{moduleNote}</div>
            ) : null}
          </div>
        ) : null}
        {manyCompetitions ? (
          <>
        <label
          className={`mt-2 flex items-center gap-2 text-xs ${
            multiSendBlocked ? 'cursor-not-allowed text-ink-faint' : 'text-ink-soft'}`}
          title={multiSendBlocked ? 'Ogni competizione ha la sua formazione, e i giocatori già bloccati vi occupano posti diversi.' : undefined}
        >
          <input
            type="checkbox"
            checked={sendAll}
            disabled={multiSendBlocked}
            onChange={(e) => setAllComps(e.target.checked)}
          />
          Invia questa formazione a tutte le competizioni della lega (stessa giornata)
        </label>
        {multiSendBlocked && !closed ? (
          <div className="mt-1 text-[11px] text-ink-faint">
            Non più disponibile: ogni competizione ha la sua formazione, e chi è già bloccato vi
            occupa posti diversi. Vanno modificate una per una.
          </div>
        ) : null}
          </>
        ) : null}
        {/* Sul telefono l'esito compare nella barra in fondo, accanto al pulsante
            che l'ha prodotto: qui sarebbe fuori schermo nel momento esatto in cui
            serve leggerlo. */}
        {toast ? <div className="mt-2 hidden text-sm font-semibold text-good lg:block">{toast}</div> : null}
      </Card>

      <div className="grid items-start gap-4 lg:grid-cols-[1fr_360px]">
        <Card className="self-start p-4 lg:sticky lg:top-4">
          <SectionTitle>La squadra in campo</SectionTitle>
          <div className="mt-1 text-[11px] text-ink-faint">
            {isClassic ? 'Schieramento per ruolo.' : 'Posizione attesa di ogni titolare (dai dati storici).'} Il
            portiere veste la muta invertita. Tocca un giocatore per vederne le zone d'influenza e i dati;
            tocca un posto vuoto per scegliere chi lo occupa.
          </div>
          <PitchLineup
            starterIds={starterIds}
            vacancies={vacancies}
            byId={byId}
            gkId={gkId}
            selectedId={selected}
            onSelect={(id) => {
              setPicking(null);
              setSelected((s) => (s === id ? null : id));
            }}
            onPickRole={(role) => {
              setSelected(null);
              setPicking(role);
            }}
            kits={kits}
            lockedIds={lockedIds}
            regular={isClassic}
          />
        </Card>

        <Card className="p-4">
          {/* SUL TELEFONO LA LISTA DEI TITOLARI NON SI DISEGNA.
           *
           *  Su desktop le due colonne stanno affiancate e la ripetizione è un
           *  pannello di comando: si guarda il campo a sinistra e si tocca a
           *  destra. Impilate su un telefono diventa la stessa cosa detta due
           *  volte, 653 pixel di pagina che non aggiungono niente a quello che il
           *  campo mostra già — e che l'utente scorre credendo di doverli usare.
           *  Qui sotto resta la panchina, che invece il campo non mostra. */}
          <div className="hidden lg:block">
            <SectionTitle>Rosa · titolari e panchina (un solo portiere fra i titolari)</SectionTitle>
            <div className="mt-1 text-[11px] text-ink-faint">Clicca il nome per vederne le zone sulla mappa.</div>

            <div className="mt-3 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
              Titolari {starterIds.length}/{XI}
            </div>
            <div className="divide-y">
            {starters.map((p) => (
              <RosterRow
                key={p.player_id}
                p={p}
                isStarter
                selected={selected === p.player_id}
                onSelect={() => setSelected((s) => (s === p.player_id ? null : p.player_id))}
                onToggle={() => toggleStarter(p.player_id)}
                locked={lockedIds.has(p.player_id)}
                immutable={!!immutableReason(p.player_id)}
                immutableReason={immutableReason(p.player_id)}
                note={refused?.player_id === p.player_id ? refused.reason : null}
              />
            ))}
            {/* The same empty places, in the list: "9/11" is a number you have to
                read, a row that says "manca un difensore" is not. */}
            {Array.from({ length: Math.max(0, XI - starters.length) }, (_, i) => (
              <div key={`slot-${i}`} className="flex items-center gap-2 py-2.5 text-sm">
                <span className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-dashed border-line text-[10px] font-bold text-ink-faint">
                  +
                </span>
                <span className="italic text-ink-faint">
                  {vacancies[i] ? `Manca un ${ROLE_WORD[vacancies[i]]}` : 'Posto libero'}
                </span>
              </div>
            ))}
            {starters.length === 0 && !vacancies.length ? (
              <div className="py-2 text-sm text-ink-faint">Nessun titolare selezionato.</div>
            ) : null}
            </div>
          </div>

          <div className="mt-4 text-[11px] font-semibold uppercase tracking-wide text-ink-faint lg:mt-4">
            Panchina · ordine = priorità sostituzioni
          </div>
          <div className="mt-0.5 text-[11px] text-ink-faint">
            {isClassic
              ? 'Entra il primo panchinaro in lista che ha un voto e mantiene la formazione valida.'
              : 'In Aura il sostituto è il migliore disponibile; l’ordine conta solo a parità.'}
          </div>
          <div className="mt-1 text-[11px] text-ink-faint">
            Tieni premuto e trascina per cambiare l'ordine.
          </div>
          <div
            className="divide-y"
            // Il gesto si segue sul CONTENITORE, non sulla riga: mentre la lista si
            // riordina sotto il dito la riga di partenza cambia posto, e gli eventi
            // agganciati a lei arriverebbero a singhiozzo.
            onPointerMove={rowPointerMove}
            onPointerCancel={dragEnd}
          >
            {shownBench.map((p, i) => (
              <RosterRow
                key={p.player_id}
                p={p}
                isStarter={false}
                selected={selected === p.player_id}
                onSelect={() => setSelected((s) => (s === p.player_id ? null : p.player_id))}
                onToggle={() => toggleStarter(p.player_id)}
                blocked={blockReasonFor(p)}
                note={refused?.player_id === p.player_id ? refused.reason : null}
                locked={lockedIds.has(p.player_id)}
                immutable={!!immutableReason(p.player_id)}
                immutableReason={immutableReason(p.player_id)}
                order={i + 1}
                rowRef={(el) => {
                  if (el) benchRowEls.current.set(p.player_id, el);
                  else benchRowEls.current.delete(p.player_id);
                }}
                drag={{
                  dragging: dragId === p.player_id,
                  disabled: !!immutableReason(p.player_id),
                  onPointerDown: rowPointerDown(p.player_id),
                  onPointerUp: rowPointerUp(p.player_id),
                }}
              />
            ))}
            {bench.length === 0 ? <div className="py-2 text-sm text-ink-faint">Panchina vuota.</div> : null}
          </div>
        </Card>
      </div>

      {/* LA BARRA DEL SALVA, dove sta il pollice.
       *
       *  Il Salva stava in cima, ed è il posto in cui non si lavora mai: chi
       *  sistema la panchina ce l'ha a millecinquecento pixel di distanza, e per
       *  premerlo deve risalire tutta la pagina. Peggio, il motivo per cui è
       *  grigio viveva SOLO in un `title` su un pulsante `disabled` — un tooltip
       *  che il dito non fa comparire, su un elemento che il click non raggiunge:
       *  a schermo restava un bottone spento e nessuna spiegazione.
       *
       *  La riga sotto il contatore dice una cosa sola, la più urgente delle tre:
       *  l'esito appena arrivato, altrimenti l'ostacolo, altrimenti niente. Niente
       *  e non «tutto a posto», perché una barra che si congratula a ogni tocco
       *  smette di essere letta, e quando poi ha qualcosa da dire non la guarda
       *  più nessuno.
       *
       *  Sta sopra la tab bar leggendo `--vf-bar-block`, che AppShell pubblica: è
       *  lo stesso numero con cui la barra è disegnata, striscia delle competizioni
       *  compresa, e non una copia destinata a divergere. */}
      <div
        className="lg:hidden"
        aria-hidden
        style={{ height: 'calc(var(--vf-bar-block, 60px) + 4.5rem)' }}
      />
      <div
        className="fixed inset-x-0 z-40 lg:hidden"
        style={{ bottom: 'calc(var(--vf-safe-bottom) + var(--vf-bar-block, 60px))' }}
      >
        {/* LA SCHEDA STA NELLO STESSO BLOCCO FISSO DELLA BARRA, impilata sopra.
         *
         *  Non è un vezzo di struttura: se fossero due elementi fissi separati,
         *  ognuno col suo `bottom` calcolato a mano, si sovrapporrebbero il giorno
         *  in cui uno dei due cambia altezza — e la barra cambia altezza da sola,
         *  ogni volta che ha un motivo di blocco da scrivere. Impilati, la somma
         *  la fa il flusso e non c'è niente da tenere allineato.
         *
         *  Toccando un giocatore sul campo, prima, i dati si aprivano dentro la
         *  riga della lista: a 390px erano 289 pixel sotto la piega. Si accendeva
         *  il giallo sul campo e nient'altro, e il dato che avevi chiesto stava in
         *  un punto dello schermo che non stavi guardando. */}
        {picking ? (
          <RolePicker
            role={picking}
            candidates={notChosen
              .filter((p) => p.role === picking)
              .map((p) => ({ p, blocked: blockReasonFor(p) }))
              .sort((a, b) => {
                // Chi può entrare prima di chi non può, poi per media voto: è
                // l'ordine in cui si guarda un elenco di sostituti.
                if (!!a.blocked !== !!b.blocked) return a.blocked ? 1 : -1;
                return (b.p.value ?? 0) - (a.p.value ?? 0);
              })}
            onPick={(id) => {
              toggleStarter(id);
              setPicking(null);
            }}
            onClose={() => setPicking(null)}
          />
        ) : selectedPlayer ? (
          <PlayerSheet
            p={selectedPlayer}
            isStarter={starterIds.includes(selectedPlayer.player_id)}
            benchOrder={
              starterIds.includes(selectedPlayer.player_id)
                ? null
                : shownBench.findIndex((b) => b.player_id === selectedPlayer.player_id) + 1
            }
            locked={lockedIds.has(selectedPlayer.player_id)}
            immutableReason={immutableReason(selectedPlayer.player_id)}
            blocked={
              starterIds.includes(selectedPlayer.player_id) ? null : blockReasonFor(selectedPlayer)
            }
            refusedNote={
              refused?.player_id === selectedPlayer.player_id ? refused.reason : null
            }
            onToggle={() => toggleStarter(selectedPlayer.player_id)}
            onTop={() => benchToTop(selectedPlayer.player_id)}
            onClose={() => setSelected(null)}
          />
        ) : null}
        <div className="border-t border-line bg-surface px-3 py-2 shadow-[0_-4px_16px_rgba(0,0,0,0.06)]">
        <div className="mx-auto flex max-w-3xl items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-1.5">
              <span
                className={clsx(
                  'text-base font-bold tabular-nums',
                  canSave ? 'text-good' : 'text-bad',
                )}
              >
                {starterIds.length}/{XI}
              </span>
              <span className="text-[11px] uppercase tracking-wide text-ink-faint">titolari</span>
            </div>
            {toast ? (
              <div className="mt-0.5 text-[11px] font-semibold leading-snug text-good">{toast}</div>
            ) : saveBlock ? (
              <div className="mt-0.5 text-[11px] font-semibold leading-snug text-bad">{saveBlock}</div>
            ) : null}
          </div>
          <Button variant="secondary" size="sm" onClick={onSuggest} className="shrink-0">
            Suggerisci
          </Button>
          <Button onClick={onSave} disabled={!canSave || saving} className="shrink-0">
            {saving ? 'Salvo…' : 'Salva'}
          </Button>
        </div>
        </div>
      </div>
    </div>
  );
}

/** LA SCHEDA DI UN GIOCATORE, aperta toccandolo — sul campo o in panchina.
 *
 *  Contiene le tre cose per cui lo si tocca (che partita gioca e quando, quanto
 *  viene impiegato, quanto vale) e le due che si vogliono fare dopo averle lette
 *  (mandarlo dall'altra parte, o farlo entrare per primo). Prima erano separate:
 *  i dati in fondo alla pagina dentro la riga, le azioni in un segmentato largo
 *  sessanta pixel accanto al nome.
 *
 *  Un rifiuto qui si LEGGE, e si legge prima: il pulsante che non si può premere
 *  porta scritto sotto il motivo, invece di aspettare il tocco per dirlo. */
function PlayerSheet({
  p,
  isStarter,
  benchOrder,
  locked,
  immutableReason,
  blocked,
  refusedNote,
  onToggle,
  onTop,
  onClose,
}: {
  p: TeamLineupPlayer;
  isStarter: boolean;
  /** Il suo numero in panchina, o null se è un titolare. */
  benchOrder: number | null;
  locked?: boolean;
  immutableReason: string | null;
  blocked: string | null;
  refusedNote: string | null;
  onToggle: () => void;
  onTop: () => void;
  onClose: () => void;
}) {
  const nm = p.next_match;
  const why = immutableReason ?? blocked ?? refusedNote;
  return (
    <div className="border-t border-line bg-surface px-3 pb-3 pt-2 shadow-[0_-8px_24px_rgba(0,0,0,0.10)]">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-start gap-2">
          <span className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ${ROLE_CHIP[p.role]}`}>
            {ROLE_LABEL[p.role]}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-1.5">
              <span className="truncate text-sm font-bold">{p.name}</span>
              {benchOrder ? (
                <span className="shrink-0 text-[11px] tabular-nums text-ink-faint">
                  {benchOrder}° in panchina
                </span>
              ) : null}
              {locked ? (
                <span className="shrink-0 rounded bg-surface-2 px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide text-ink-soft">
                  {frozenLabel(nm)}
                </span>
              ) : null}
            </div>
            {nm ? (
              <div className="text-[11px] text-ink-soft">
                {fixtureLabel(nm)} <span className="text-ink-faint">· {fmtKickoff(nm)}</span>
              </div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Chiudi"
            className="-mr-1 -mt-1 shrink-0 rounded-lg px-2.5 py-1.5 text-lg leading-none text-ink-faint hover:bg-surface-2"
          >
            ×
          </button>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-soft">
          {typeof p.value === 'number' ? (
            <span>
              media voto <b className="text-ink">{p.value.toFixed(2)}</b>
              {p.value_basis === 'stimato' ? <span className="text-ink-faint"> (stimata)</span> : null}
            </span>
          ) : (
            <span className="text-ink-faint">nessuno storico</span>
          )}
          {p.minutes_label === 'unknown' ? (
            <span className="text-ink-faint">impiego sconosciuto</span>
          ) : (
            <span>
              {p.appearances} pres · {p.avg_minutes}′ medi
              {p.minutes_label === 'low' ? <Badge tone="amber"> poco impiegato</Badge> : null}
              {p.minutes_label === 'high' ? <Badge tone="green"> titolare abituale</Badge> : null}
            </span>
          )}
        </div>

        {why ? <div className="mt-2 text-[11px] font-semibold text-bad">{why}</div> : null}

        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={onToggle}
            aria-disabled={immutableReason || blocked ? true : undefined}
            className={clsx(
              'flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-xl px-3 text-sm font-semibold',
              immutableReason || blocked
                ? 'cursor-not-allowed bg-surface-2 text-ink-faint'
                : isStarter
                  ? 'bg-ink text-paper'
                  : 'bg-good text-white',
            )}
          >
            {isStarter ? (
              <>
                <BenchIcon /> In panchina
              </>
            ) : (
              <>
                <PitchIcon /> In campo
              </>
            )}
          </button>
          {!isStarter ? (
            <button
              type="button"
              onClick={onTop}
              aria-disabled={immutableReason ? true : undefined}
              className={clsx(
                'min-h-[44px] shrink-0 rounded-xl border border-line px-3 text-sm font-semibold',
                immutableReason ? 'cursor-not-allowed text-ink-faint' : 'text-ink-soft hover:bg-surface-2',
              )}
            >
              Entra per primo
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/** CHI PUÒ OCCUPARE QUESTO POSTO — l'elenco che si apre toccando un buco sul
 *  campo.
 *
 *  Solo il suo ruolo, e già ordinato per come si guarda: prima chi può entrare
 *  davvero, poi gli altri col motivo scritto accanto. Il motivo c'è anche per chi
 *  non può, invece di lasciarlo fuori dall'elenco: «non c'è» e «c'è ma non adesso,
 *  perché...» sono due risposte diverse, e la seconda è quella vera. */
function RolePicker({
  role,
  candidates,
  onPick,
  onClose,
}: {
  role: PlayerRole;
  candidates: Array<{ p: TeamLineupPlayer; blocked: string | null }>;
  onPick: (id: number) => void;
  onClose: () => void;
}) {
  return (
    <div className="border-t border-line bg-surface px-3 pb-3 pt-2 shadow-[0_-8px_24px_rgba(0,0,0,0.10)]">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-center gap-2">
          <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ${ROLE_CHIP[role]}`}>
            {ROLE_LABEL[role]}
          </span>
          <span className="min-w-0 flex-1 truncate text-sm font-bold">
            Chi entra al posto del {ROLE_WORD[role]}?
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Chiudi"
            className="-mr-1 shrink-0 rounded-lg px-2.5 py-1.5 text-lg leading-none text-ink-faint hover:bg-surface-2"
          >
            ×
          </button>
        </div>
        <div className="mt-1 max-h-[38vh] overflow-y-auto">
          {candidates.length === 0 ? (
            <div className="py-3 text-sm text-ink-faint">
              Nessun {ROLE_WORD[role]} in panchina.
            </div>
          ) : (
            <div className="divide-y divide-line">
              {candidates.map(({ p, blocked }) => (
                <button
                  key={p.player_id}
                  type="button"
                  onClick={() => (blocked ? undefined : onPick(p.player_id))}
                  aria-disabled={blocked ? true : undefined}
                  className={clsx(
                    'flex min-h-[48px] w-full items-center gap-2 px-1 text-left',
                    blocked ? 'cursor-not-allowed opacity-60' : 'hover:bg-surface-2',
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{p.name}</span>
                    {blocked ? (
                      <span className="block text-[11px] leading-snug text-bad">{blocked}</span>
                    ) : p.next_match ? (
                      <span className="block truncate text-[11px] text-ink-faint">
                        {fixtureLabel(p.next_match)} · {fmtKickoff(p.next_match)}
                      </span>
                    ) : null}
                  </span>
                  {typeof p.value === 'number' ? (
                    <span className="shrink-0 text-sm font-bold tabular-nums text-ink-soft">
                      {p.value.toFixed(2)}
                    </span>
                  ) : null}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** La panchina, disegnata: è l'icona che l'utente si aspetta di trovare addosso
 *  al giocatore selezionato per spedircelo. */
function BenchIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <path d="M2 8h16" />
      <path d="M2 11.5h16" />
      <path d="M4 11.5v5" />
      <path d="M16 11.5v5" />
      <path d="M4 8V5" />
      <path d="M16 8V5" />
    </svg>
  );
}

function PitchIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="2" y="4" width="16" height="12" rx="1.5" />
      <path d="M10 4v12" />
      <circle cx="10" cy="10" r="2.2" />
    </svg>
  );
}

/** UNA RIGA DELLA ROSA. Sul telefono e' la panchina e basta (i titolari li mostra
 *  il campo), quindi la riga porta solo quello che serve per decidere l'ORDINE:
 *  numero, ruolo, nome, e se e' congelato. Media voto, partita e minuti stavano
 *  qui e mandavano nove righe su quattordici a capo su tre righe: adesso sono a
 *  un tocco di distanza, nella scheda, dove ci si va apposta.
 *
 *  Su desktop la riga resta com'era — c'e' spazio, e li' non c'e' nessuna scheda
 *  a raccogliere quello che si toglie. */
function RosterRow({
  p,
  isStarter,
  selected,
  onSelect,
  onToggle,
  blocked,
  note,
  locked,
  immutable,
  immutableReason,
  order,
  drag,
  rowRef,
}: {
  p: TeamLineupPlayer;
  isStarter: boolean;
  selected: boolean;
  onSelect: () => void;
  onToggle: () => void;
  /** Why he cannot be promoted right now (null = he can). */
  blocked?: string | null;
  /** His match has kicked off: he stays where he is, wherever that is. */
  locked?: boolean;
  /** His placement cannot change at all — he is playing, or the round is over.
   *  Both buttons then READ as unavailable, which is the thing a refusal after the
   *  click cannot do: you should be able to see it before pressing. */
  immutable?: boolean;
  immutableReason?: string | null;
  /** The refusal, shown after an attempt: the tooltip alone is invisible on touch. */
  note?: string | null;
  order?: number;
  /** La riga si trascina: tutta lei, dopo un quarto di secondo di dito fermo.
   *  Assente = riga non trascinabile (un titolare). */
  drag?: {
    onPointerDown: (e: React.PointerEvent) => void;
    onPointerUp: (e: React.PointerEvent) => void;
    dragging: boolean;
    disabled: boolean;
  };
  rowRef?: (el: HTMLElement | null) => void;
}) {
  return (
    <div
      ref={rowRef}
      onPointerDown={drag?.onPointerDown}
      onPointerUp={drag?.onPointerUp}
      role={drag ? 'button' : undefined}
      tabIndex={drag ? 0 : undefined}
      onKeyDown={
        drag
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onSelect();
              }
            }
          : undefined
      }
      className={clsx(
        'flex min-h-[48px] items-center justify-between gap-2 py-2',
        // Sempre, non solo mentre si trascina: la selezione parte al primo
        // millisecondo di pressione, cioè molto prima che si sappia se è un
        // trascinamento.
        drag && 'select-none',
        selected && 'bg-surface-2',
        // La riga che sta sotto il dito: alzata dal foglio, così si vede che è in
        // mano e non semplicemente selezionata.
        drag?.dragging && 'rounded-lg bg-surface shadow-md ring-1 ring-line',
        // Deciso solo QUANDO la presa è partita: al `pointerdown` non si sa ancora
        // se sarà un trascinamento o una scorsa, e toglierlo in anticipo
        // bloccherebbe lo scorrimento della pagina su tutta la panchina.
        drag?.dragging && 'touch-none select-none',
      )}
    >
      {drag ? (
        <span
          aria-hidden
          className={clsx(
            'shrink-0 select-none px-1 text-base leading-none',
            drag.disabled ? 'text-ink-faint/40' : 'text-ink-faint',
          )}
        >
          ⠿
        </span>
      ) : null}
      <div className="flex min-w-0 flex-1 items-center gap-2 text-left">
        {order != null ? (
          <span className="w-4 shrink-0 text-right text-[11px] font-semibold tabular-nums text-ink-faint">{order}</span>
        ) : null}
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ${ROLE_CHIP[p.role]}`}>
          {ROLE_LABEL[p.role]}
        </span>
        <span className="min-w-0">
          {/* The chip sits OUTSIDE the truncating name: inside it, a long name ate
              it a letter at a time ("PARTITA FINI…"). The name gives way, the state
              does not. */}
          <span className="flex min-w-0 items-baseline gap-1.5">
            <span className={`truncate text-sm font-semibold ${selected ? 'text-ink underline' : 'text-ink'}`}>
              {p.name}
            </span>
            {locked ? (
              <span
                className="shrink-0 rounded bg-surface-2 px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide text-ink-soft"
                title={frozenTitle(p.next_match)}
              >
                {frozenLabel(p.next_match)}
              </span>
            ) : null}
          </span>
          {/* SOLO SU DESKTOP: sul telefono questa riga mandava a capo nove righe su
              quattordici, e le stesse tre cose sono nella scheda a un tocco. */}
          <span className="hidden text-[11px] text-ink-faint lg:block">
            {typeof p.value === 'number' ? (
              <>
                media voto <b className="text-ink-soft">{p.value.toFixed(2)}</b>
                {p.value_basis === 'stimato' ? <span className="text-ink-faint"> (stimata)</span> : null}
              </>
            ) : (
              <span className="text-ink-faint">nessuno storico</span>
            )}
            {p.next_match ? <span className="text-ink-faint"> · {fixtureLabel(p.next_match)}</span> : null}
          </span>
          {note ? <span className="mt-1 block text-[11px] font-semibold text-bad">{note}</span> : null}
          {/* In linea SOLO su desktop: sul telefono gli stessi dati stanno nella
              scheda in fondo, dove si vedono senza scorrere. */}
          {selected ? <span className="hidden lg:block"><PlayerDetails p={p} /></span> : null}
        </span>
      </div>
      {/* Il segmentato resta su desktop, dove è l'unico comando della riga. Sul
          telefono l'azione sta nella scheda, con l'icona della panchina e il
          motivo scritto quando non si può. */}
      <div className="hidden shrink-0 items-center gap-1 lg:flex">
        <div className="flex overflow-hidden rounded-lg border border-line text-[11px] font-semibold">
          {/* Deliberatamente non `disabled`: un pulsante disabilitato mangia il
              click E il proprio tooltip, quindi rifiuterebbe senza mai dire perché.
              Sembra non disponibile e, se premuto, si spiega sulla riga.
              E ognuno dei due fa la SUA direzione: premere «Titolare» su un
              titolare non deve panchinarlo — era un segmentato in cui il lato già
              acceso era l'azione distruttiva. */}
          <button
            onClick={() => (isStarter ? undefined : onToggle())}
            title={immutableReason ?? blocked ?? undefined}
            aria-pressed={isStarter}
            aria-disabled={immutable || blocked ? true : undefined}
            className={
              immutable
                ? isStarter
                  ? 'cursor-not-allowed bg-ink-faint/60 px-3 py-1 text-white'
                  : 'cursor-not-allowed bg-surface-2 px-3 py-1 text-ink-faint'
                : isStarter
                  ? 'bg-ink px-3 py-1 text-paper'
                  : blocked
                    ? 'cursor-not-allowed bg-surface-2 px-3 py-1 text-ink-faint'
                    : 'bg-surface px-3 py-1 text-ink-soft hover:bg-surface-2'
            }
          >
            Titolare
          </button>
          <button
            onClick={() => (isStarter ? onToggle() : undefined)}
            title={immutableReason ?? undefined}
            aria-pressed={!isStarter}
            aria-disabled={immutable ? true : undefined}
            className={
              immutable
                ? !isStarter
                  ? 'cursor-not-allowed bg-ink-faint/60 px-3 py-1 text-white'
                  : 'cursor-not-allowed bg-surface-2 px-3 py-1 text-ink-faint'
                : !isStarter
                  ? 'bg-ink-faint px-3 py-1 text-white'
                  : 'bg-surface px-3 py-1 text-ink-soft hover:bg-surface-2'
            }
          >
            Panca
          </button>
        </div>
      </div>
    </div>
  );
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// Expected position of a player = footprint centroid in (col,row) space.
function expectedPos(footprint: Record<string, number>): { col: number; row: number } {
  let scol = 0;
  let srow = 0;
  let tot = 0;
  for (const [z, s] of Object.entries(footprint)) {
    const m = /^Z_(\d+)_(\d+)$/.exec(z);
    if (m) {
      scol += Number(m[1]) * s;
      srow += Number(m[2]) * s;
      tot += s;
    }
  }
  return tot > 0 ? { col: scol / tot, row: srow / tot } : { col: 2, row: 1.5 };
}

// The XI placed on a pitch at each player's expected position. Defence on the
// left, attack on the right; goalkeeper ringed in amber.
function PitchLineup({
  starterIds,
  vacancies = [],
  byId,
  gkId,
  selectedId,
  onSelect,
  onPickRole,
  kits,
  lockedIds,
  regular = false,
}: {
  starterIds: number[];
  vacancies?: PlayerRole[];
  byId: Map<number, TeamLineupPlayer>;
  gkId: number | null;
  selectedId: number | null;
  onSelect: (id: number) => void;
  /** Un posto vuoto toccato: apre chi può occuparlo. */
  onPickRole: (role: PlayerRole) => void;
  kits: { outfield: Kit; keeper: Kit };
  lockedIds: Set<number>;
  regular?: boolean;
}) {
  // Lay the XI out as formation lines: depth (x) from each player's expected
  // column, width (y) spread within their role line so dots never pile up
  // (footprint centroids alone bunch everyone in the middle).
  // Base position from the player's REFERENCE zone: depth (x) by role band +
  // expected column, lateral (y) by the expected row (so wide players stay wide,
  // central players stay central — attackers are no longer flung to the flanks).
  const ROLE_X: Record<PlayerRole, number> = { GK: 8, DEF: 30, MID: 53, ATT: 76 };
  const TYPICAL_COL: Record<PlayerRole, number> = { GK: 0, DEF: 1, MID: 2, ATT: 3 };
  // CLASSIC: only the coarse role matters, so lay the XI out as a tidy formation —
  // one line per role, players spread evenly across it. The real spatial position is
  // an aura concern and only adds noise here.
  if (regular) {
    const lines: PlayerRole[] = ['GK', 'DEF', 'MID', 'ATT'];
    const byRole = new Map<PlayerRole, TeamLineupPlayer[]>(lines.map((r) => [r, []]));
    starterIds
      .map((id) => byId.get(id))
      .filter((p): p is TeamLineupPlayer => !!p)
      .forEach((p) => byRole.get(p.role)?.push(p));
    // Empty places count towards their line's width, so the players around them
    // do not slide over to close the gap: the hole is where the missing man goes.
    const holesByRole = new Map<PlayerRole, number>(
      lines.map((r) => [r, vacancies.filter((v) => v === r).length]),
    );
    const regularDots = lines.flatMap((role) => {
      const group = byRole.get(role) ?? [];
      const holes = holesByRole.get(role) ?? 0;
      const size = group.length + holes;
      const spread = (i: number) => 50 + (i - (size - 1) / 2) * Math.min(26, 76 / Math.max(size, 1));
      const filled = group.map((p, i) => ({
        p,
        left: ROLE_X[role],
        top: spread(i),
        isGk: p.player_id === gkId,
      }));
      const empty = Array.from({ length: holes }, (_, k) => ({
        empty: true as const,
        role,
        left: ROLE_X[role],
        top: spread(group.length + k),
      }));
      return [...filled, ...empty];
    });
    const selRegular = selectedId != null ? byId.get(selectedId) : null;
    return (
      <PitchCanvas
        dots={regularDots}
        selectedId={selectedId}
        onSelect={onSelect}
        onPickRole={onPickRole}
        kits={kits}
        lockedIds={lockedIds}
        showRole={false}
        footprint={selRegular?.footprint ?? null}
      />
    );
  }

  const dots = starterIds
    .map((id) => byId.get(id))
    .filter((p): p is TeamLineupPlayer => !!p)
    .map((p) => {
      const { col, row } = expectedPos(p.footprint);
      const nudge = Math.max(-8, Math.min(9, (col - TYPICAL_COL[p.role]) * 6));
      return {
        p,
        left: Math.max(6, Math.min(94, ROLE_X[p.role] + nudge)),
        top: Math.max(12, Math.min(88, 12 + (row / 3) * 76)),
        isGk: p.player_id === gkId,
      };
    });
  // Aesthetic de-overlap: gently push apart dots that are too close, keeping each
  // near its real zone. The user still decides the balance of the lineup.
  const MIN = 14;
  for (let iter = 0; iter < 60; iter++) {
    for (let i = 0; i < dots.length; i++) {
      for (let j = i + 1; j < dots.length; j++) {
        let dx = dots[i].left - dots[j].left;
        let dy = dots[i].top - dots[j].top;
        let d = Math.hypot(dx, dy);
        if (d < MIN) {
          if (d < 0.001) {
            dx = 0;
            dy = i % 2 === 0 ? 1 : -1;
            d = 1;
          }
          const push = (MIN - d) / 2;
          const ux = dx / d;
          const uy = dy / d;
          dots[i].left = Math.max(6, Math.min(94, dots[i].left + ux * push));
          dots[i].top = Math.max(12, Math.min(88, dots[i].top + uy * push));
          dots[j].left = Math.max(6, Math.min(94, dots[j].left - ux * push));
          dots[j].top = Math.max(12, Math.min(88, dots[j].top - uy * push));
        }
      }
    }
  }

  const sel = selectedId != null ? byId.get(selectedId) : null;
  return (
    <PitchCanvas
      dots={dots}
      selectedId={selectedId}
      onSelect={onSelect}
      onPickRole={onPickRole}
      kits={kits}
      lockedIds={lockedIds}
      // In Aura i giocatori stanno dove li mette la heatmap, non in linee di
      // reparto: il ruolo lo diceva solo il colore del pallino, che ora è quello
      // della squadra. Quindi lo si scrive sulla pastiglia del nome.
      showRole
      footprint={sel?.footprint ?? null}
    />
  );
}

/** Il campo si gira in verticale quando lo schermo è stretto.
 *
 *  Un campo orizzontale dentro un telefono è largo 360 pixel e alto 260: le linee
 *  si schiacciano, undici pallini col nome sotto si accavallano, e la profondità
 *  — che è l'asse che conta, dalla propria porta all'altra — è quello che rimane
 *  senza spazio. In verticale lo spazio va dove serve, ed è anche il verso in cui
 *  ogni fantacalcio disegna una formazione.
 *
 *  640px è la soglia `sm` di Tailwind, la stessa che il resto della pagina usa
 *  per decidere cosa è un telefono: due soglie diverse sarebbero due idee diverse
 *  di piccolo, e si vedrebbe nel punto in cui una cambia e l'altra no. */
function useVerticalPitch(): boolean {
  const query = '(max-width: 639px)';
  const [vertical, setVertical] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(query).matches,
  );
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia(query);
    const onChange = (e: MediaQueryListEvent) => setVertical(e.matches);
    setVertical(mq.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return vertical;
}

// The pitch itself: markings, the selected player's influence zones, and the dots.
// Shared by the spatial (aura) and the regular-formation (classic) layouts.
function PitchCanvas({
  dots,
  selectedId,
  onSelect,
  onPickRole,
  kits,
  lockedIds,
  showRole,
  footprint,
}: {
  dots: Array<
    | { p: TeamLineupPlayer; left: number; top: number; isGk: boolean }
    | { empty: true; role: PlayerRole; left: number; top: number }
  >;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onPickRole: (role: PlayerRole) => void;
  kits: { outfield: Kit; keeper: Kit };
  lockedIds: Set<number>;
  showRole: boolean;
  footprint: Record<string, number> | null;
}) {
  const selMax = footprint ? Math.max(0.0001, ...Object.values(footprint)) : 1;
  const vertical = useVerticalPitch();

  /** Una posizione del campo ORIZZONTALE, messa dove va.
   *
   *  Tutto il resto della pagina ragiona in orizzontale — `left` è la profondità
   *  dalla propria porta, `top` è l'ampiezza — e continua a farlo: le linee di
   *  reparto, lo scostamento per zona, la spinta che separa i pallini vicini sono
   *  già scritti e provati così. Girare il campo è una faccenda di DISEGNO, e
   *  vive tutta qui dentro: gli assi si scambiano, e la profondità si inverte
   *  perché in verticale la propria porta sta in basso, come su ogni schema di
   *  formazione mai stampato. */
  const place = (left: number, top: number) =>
    vertical ? { left: `${top}%`, top: `${100 - left}%` } : { left: `${left}%`, top: `${top}%` };

  return (
    <div
      className={clsx(
        'relative mt-3 w-full overflow-hidden rounded-xl border border-good/40 shadow-inner',
        vertical
          ? 'aspect-[5/7] bg-gradient-to-t from-green-600 to-green-500'
          : 'aspect-[7/5] bg-gradient-to-r from-green-600 to-green-500',
      )}
    >
      {/* pitch markings */}
      <div className="pointer-events-none absolute inset-2 rounded border border-white/40" />
      {/* La linea di metà campo taglia la LUNGHEZZA, quindi gira col campo. */}
      <div
        className={clsx(
          'pointer-events-none absolute bg-surface/40',
          vertical ? 'inset-x-2 top-1/2 h-px -translate-y-1/2' : 'inset-y-2 left-1/2 w-px -translate-x-1/2',
        )}
      />
      <div className="pointer-events-none absolute left-1/2 top-1/2 h-16 w-16 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/40" />
      {/* Le due aree stanno ai capi della lunghezza: ai lati da orizzontale, sopra
          e sotto da verticale. */}
      <div
        className={clsx(
          'pointer-events-none absolute border border-white/40',
          vertical ? 'bottom-2 left-1/2 h-12 w-24 -translate-x-1/2' : 'left-2 top-1/2 h-24 w-12 -translate-y-1/2',
        )}
      />
      <div
        className={clsx(
          'pointer-events-none absolute border border-white/40',
          vertical ? 'left-1/2 top-2 h-12 w-24 -translate-x-1/2' : 'right-2 top-1/2 h-24 w-12 -translate-y-1/2',
        )}
      />
      {/* predicted influence zones of the selected player */}
      {footprint
        ? Object.entries(footprint).map(([z, share]) => {
            const m = /^Z_(\d+)_(\d+)$/.exec(z);
            if (!m) return null;
            const c = Number(m[1]);
            const r = Number(m[2]);
            const intensity = share / selMax;
            // La cella occupa un quinto della lunghezza e un quarto della
            // larghezza: girando il campo si scambiano anche quelle, e la colonna
            // si conta dall'altro capo (`4 - c`) perché la profondità si inverte.
            const box = vertical
              ? { left: `${(r / 4) * 100}%`, top: `${((4 - c) / 5) * 100}%`, width: '25%', height: '20%' }
              : { left: `${(c / 5) * 100}%`, top: `${(r / 4) * 100}%`, width: '20%', height: '25%' };
            return (
              <div
                key={z}
                className="pointer-events-none absolute border border-yellow-100/30"
                style={{
                  ...box,
                  // high-contrast yellow on the green pitch (role colours like the
                  // midfielders' green would vanish into the turf)
                  backgroundColor: `rgba(250,204,21,${(0.25 + 0.6 * intensity).toFixed(3)})`,
                }}
              />
            );
          })
        : null}
      {dots.map((d) =>
        'empty' in d ? (
          /* IL POSTO VUOTO, E ADESSO SI TOCCA.
           *
           *  Era un `div` con un `title`: il punto che più di ogni altro sulla
           *  pagina dice «qui va messo qualcuno» era l'unico elemento inerte, e il
           *  suo testo di aiuto sul telefono non esisteva nemmeno. Adesso è un
           *  pulsante che apre chi PUÒ occuparlo — solo il suo ruolo, e solo quelli
           *  che le regole lascerebbero entrare.
           *
           *  E la sagoma è una maglia vuota, non un cerchio col più: una maglia
           *  tratteggiata si legge come un posto in squadra senza bisogno che
           *  nessuno lo scriva. */
          <button
            key={`hole-${d.role}-${d.top}`}
            type="button"
            onClick={() => onPickRole(d.role)}
            aria-label={`Manca un ${ROLE_WORD[d.role]}: scegli chi entra`}
            className="absolute flex min-h-[44px] min-w-[44px] -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center"
            style={place(d.left, d.top)}
          >
            <Jersey dashed size={30} />
            <span className="mt-0.5 rounded bg-black/45 px-1 text-[8px] font-semibold leading-tight text-white/90">
              {ROLE_LABEL_SHORT[d.role]}
            </span>
          </button>
        ) : (
          renderDot(d)
        ),
      )}
    </div>
  );

  function renderDot({ p, left, top, isGk }: { p: TeamLineupPlayer; left: number; top: number; isGk: boolean }) {
    const nm = p.next_match;
    const locked = lockedIds.has(p.player_id);
    const done = locked && nm?.status === 'finished';
    const live = locked && nm?.status === 'live';
    const sel = selectedId === p.player_id;
    return (
        <button
          key={p.player_id}
          onClick={() => onSelect(p.player_id)}
          className="absolute flex min-h-[44px] min-w-[44px] -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center"
          style={place(left, top)}
          title={p.name}
          aria-pressed={sel}
        >
          <span
            className={clsx(
              'relative flex items-center justify-center rounded-full',
              // La selezione è un alone attorno alla maglia: un anello quadrato
              // attorno a una sagoma non rettangolare si legge male.
              sel && 'shadow-[0_0_0_3px_rgba(255,255,255,0.9)] rounded-lg',
              // Chi ha finito è spento. Non nascosto: c'è ancora, e conta.
              done && 'opacity-55 saturate-50',
            )}
          >
            <Jersey kit={isGk ? kits.keeper : kits.outfield} label={initials(p.name)} size={30} />
            {live ? (
              <span
                className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 animate-pulse rounded-full bg-live ring-2 ring-white"
                aria-hidden
              />
            ) : locked && !done ? (
              <span
                className="absolute -right-1 -top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-black/70 text-[7px] leading-none text-white"
                aria-hidden
              >
                ⏱
              </span>
            ) : null}
          </span>
          <span className="mt-0.5 flex max-w-[70px] items-center gap-0.5 rounded bg-black/45 px-1 text-[8px] font-semibold leading-tight text-white">
            {showRole ? <span className="opacity-80">{ROLE_LABEL_SHORT[p.role]}</span> : null}
            <span className="truncate">{p.name.split(/\s+/).pop()}</span>
          </span>
        </button>
    );
  }
}
