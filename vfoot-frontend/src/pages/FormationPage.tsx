import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
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

/** Cosa rende una formazione DIVERSA da un'altra, ai fini del salvataggio.
 *
 *  Gli undici come insieme e non in ordine: quello lo deriva il server (P-D-C-A),
 *  quindi non è una scelta di nessuno e non è una modifica. La panchina invece in
 *  ordine, perché lì l'ordine È la scelta — è la priorità delle sostituzioni.
 *  E la casella «manda a tutte le competizioni», che cambia dove va a finire. */
function lineupPrint(
  gk: number | null,
  starters: number[],
  bench: number[],
  sendAll: boolean,
): string {
  return JSON.stringify([gk, [...starters].sort((a, b) => a - b), bench, sendAll]);
}

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

/** TUTTI I MODULI LEGALI, che sono nove e non un numero a caso: sono esattamente
 *  le terne che rispettano i vincoli classic (difesa 3–5, centrocampo fino a 6,
 *  attacco 1–3, dieci di movimento). Il tetto dei sei vale in difesa e non a
 *  centrocampo, ed è tutta la differenza fra il 3-6-1, che c'è, e il 6-3-1, che
 *  non c'è; il 4-6-0 lo esclude il minimo di un attaccante. Con la rosa 3-8-8-6
 *  sono sempre tutti raggiungibili, quindi nessuno di questi bottoni è mai una
 *  porta chiusa per colpa della rosa — solo, eventualmente, dei congelati. */
const MODULES: Array<[number, number, number]> = [
  [3, 4, 3], [3, 5, 2], [3, 6, 1], [4, 3, 3], [4, 4, 2], [4, 5, 1], [5, 2, 3], [5, 3, 2], [5, 4, 1],
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
      errs.push(`Al massimo ${c.per_role[role].max} ${ROLE_LABEL[role]} (ne hai ${cnt[role]}).`);
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
  /** Un avviso momentaneo nella barra: il perché di un comando che non si può
   *  premere. Un pulsante `disabled` non ha modo di dirlo — mangia il tocco e il
   *  proprio tooltip — quindi qui si preme, non succede, e si legge perché. */
  const [notice, setNotice] = useState<string | null>(null);
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
  /** L'impronta della formazione COM'E' SUL SERVER per questa giornata, o null se
   *  il server non ne ha nessuna. Serve a sapere se c'è ancora qualcosa da
   *  salvare: un pulsante che dopo il salvataggio torna verde e pronto invita a
   *  premerlo di nuovo, e chi lo fa non sa se la prima volta sia andata. */
  const [savedPrint, setSavedPrint] = useState<string | null>(null);

  const setParams = (next: { competition?: number; matchday?: number }) => {
    const p = new URLSearchParams(searchParams);
    if (next.competition != null) p.set('competition', String(next.competition));
    if (next.matchday != null) p.set('matchday', String(next.matchday));
    setSearchParams(p, { replace: true });
  };

  // The suggested XI comes from the SERVER (`suggested_lineup`): one suggester,
  // shared with the baseline lineup it writes when a roster completes. The copy
  // that lived here is gone — two suggesters are two the day one is touched.
  const fromSuggestion = (sl: TeamLineupContext['suggested_lineup']): number[] =>
    sl ? [...(sl.gk_player_id != null ? [sl.gk_player_id] : []), ...sl.starter_player_ids] : [];

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
          // Nothing was ever submitted for this round and the server could not
          // write a baseline (round begun, or roster incomplete): start from its
          // proposal, which already keeps clear of whoever is on the pitch.
          starters = fromSuggestion(d.suggested_lineup).slice(0, XI);
        }
        const frozen = new Set(d.lineup_lock?.locked_player_ids ?? []);
        const slots = new Map<number, number>();
        (saved?.bench_player_ids ?? []).forEach((id, i) => {
          if (frozen.has(id)) slots.set(i, id);
        });
        setFrozenSlots(slots);
        setStarterIds(starters);
        setBenchOrder(pinFrozen(orderBench(d.roster, starters, saved?.bench_player_ids ?? []), slots));
        // Una formazione appena caricata non ha posti lasciati liberi da nessuno —
        // tranne uno: quella EREDITATA dalla giornata prima, a cui puo' mancare
        // qualcuno che nel frattempo e' stato venduto. Quel buco ha un ruolo, e il
        // ruolo va mostrato: e' l'unica cosa che dice all'allenatore che c'e'
        // qualcosa da sistemare, e dove.
        setVacancies(d.lineup_source?.vacant_roles ?? []);
        // Pulita SOLO se questa formazione è davvero quella salvata per questa
        // giornata. Una ereditata dalla giornata prima, o proposta dal
        // suggeritore, il server non ce l'ha: c'è ancora qualcosa da mandare.
        const bench0 = pinFrozen(orderBench(d.roster, starters, saved?.bench_player_ids ?? []), slots);
        setSavedPrint(
          d.lineup_source?.kind === 'saved'
            ? lineupPrint(saved?.gk_player_id ?? null, starters, bench0, false)
            : null,
        );
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

  // The bench as the page shows it and the save sends it: the manager's order,
  // everybody not in the XI appended, frozen players pinned to their numbers.
  const benchIds = pinFrozen(orderBench(ctx.roster, starterIds, benchOrder), frozenSlots);

  // NESSUNO SCAVALCA CHI HA GIÀ GIOCATO. The other half of the freeze, mirrored
  // from the save (lineup_deadline.overtakings): a free player stays on the same
  // side of every frozen one. The eleven count as one place AHEAD of the bench,
  // so a bench player behind a frozen man cannot come up — and a starter cannot
  // go down behind one. The reasons are said BEFORE the touch, not refused after.
  const frozenAhead = (order: number[], id: number): number | null => {
    const i = order.indexOf(id);
    if (i < 0) return null;
    return order.slice(0, i).find((x) => lockedIds.has(x)) ?? null;
  };
  const nameOf = (id: number) => byId.get(id)?.name ?? 'un compagno';
  /** Why this bench player cannot be brought ahead of the wall — null when he can. */
  const overtakeReason = (id: number): string | null => {
    const f = frozenAhead(benchIds, id);
    return f == null ? null : `Non può passare davanti a ${nameOf(f)}: la partita di ${nameOf(f)} è iniziata.`;
  };
  /** Where a benched starter lands: the last place of the first stretch, ahead of
   *  every frozen man — the bench length when nobody is frozen. */
  const benchCut = (order: number[]) => {
    const i = order.findIndex((x) => lockedIds.has(x));
    return i < 0 ? order.length : i;
  };
  const demotionReason = (): string | null =>
    benchIds.length && lockedIds.has(benchIds[0])
      ? `Non può andare in panchina: finirebbe dietro a ${nameOf(benchIds[0])}, la cui partita è iniziata.`
      : null;

  const blockReasonFor = (p: TeamLineupPlayer) =>
    closed
      ? 'Giornata chiusa: la formazione non è più modificabile.'
      : lockedIds.has(p.player_id)
        ? lockedReason
        : (overtakeReason(p.player_id) ?? promotionBlock(p, chosen, notChosen, isClassic ? constraints : null));

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
      const why = demotionReason();
      if (why) {
        setRefused({ player_id: id, reason: why });
        return;
      }
      setStarterIds((s) => s.filter((x) => x !== id));
      // Ahead of the wall: the last place of the first stretch, not the end of
      // the bench — behind a frozen man the save would refuse him.
      const cut = benchCut(benchIds);
      setBenchOrder(() =>
        pinFrozen([...benchIds.slice(0, cut), id, ...benchIds.slice(cut).filter((x) => x !== id)], frozenSlots),
      );
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
    let to = Math.max(0, Math.min(free.length - 1, freeAbove > from ? freeAbove - 1 : freeAbove));
    // ...and never across a frozen man: the move stops at the edge of the
    // player's own stretch. `stretch` numbers the free players by how many
    // frozen ones stand above them; the target must carry the same number.
    const stretch: number[] = [];
    let walls = 0;
    for (const x of order) {
      if (lockedIds.has(x)) walls += 1;
      else stretch.push(walls);
    }
    const mine = stretch[from];
    to = Math.max(stretch.indexOf(mine), Math.min(stretch.lastIndexOf(mine), to));
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
    const wall = overtakeReason(id);
    if (wall) {
      setRefused({ player_id: id, reason: wall });
      return;
    }
    setRefused(null);
    setBenchOrder((b) => reorderBench(pinFrozen(orderBench(ctx.roster, starterIds, b), frozenSlots), id, 0));
  };

  /** IL NUMERO DI DIFENSORI, CONGELATO DAL PRIMO CALCIO D'INIZIO.
   *
   *  Specchio della regola che il salvataggio applica (v. league_views): qui non
   *  decide niente, serve a dirlo PRIMA — spegnere le pastiglie del modulo e
   *  scriverlo nella barra, invece di lasciar premere Salva e rispondere 409. */
  const defenceLocked = !!lock?.defence_locked && lock.defence_count != null;
  const defenceNow = starterIds.filter((id) => byId.get(id)?.role === 'DEF').length;
  const defenceBlock =
    defenceLocked && defenceNow !== lock!.defence_count
      ? `La giornata è cominciata: i difensori schierati erano ${lock!.defence_count} e `
        + `non se ne può più cambiare il numero (adesso ne hai ${defenceNow}). `
        + 'Puoi ancora cambiare un difensore con un altro difensore.'
      : null;

  const byRole = (a: TeamLineupPlayer, b: TeamLineupPlayer) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role] || b.form - a.form;
  const starters = ctx.roster.filter((p) => starterIds.includes(p.player_id)).sort(byRole);
  const bench = benchIds.map((id) => byId.get(id)).filter((p): p is TeamLineupPlayer => !!p);
  // Mentre il dito è giù si mostra l'anteprima, non l'ordine salvato: è il senso
  // stesso del trascinare, vedere dove sta andando prima di lasciare.
  const shownBench = (dragPreview ?? benchIds)
    .map((id) => byId.get(id))
    .filter((p): p is TeamLineupPlayer => !!p);
  const starterRoles = starterIds.map((id) => byId.get(id)?.role).filter((r): r is PlayerRole => !!r);
  const classicErrors = isClassic && constraints ? validateClassic(starterRoles, constraints) : [];
  const gkOk = gkStarters.length === 1;
  const valid =
    starterIds.length === XI && gkOk && classicErrors.length === 0 && !closed && !defenceBlock;
  /** C'è qualcosa da mandare? Dopo un salvataggio riuscito no, finché non si
   *  tocca di nuovo qualcosa — e «qualcosa» comprende l'ordine della panchina,
   *  che è una scelta come le altre. */
  const dirty = savedPrint !== lineupPrint(gkId, starterIds, benchIds, sendAll);
  const canSave = valid && dirty;
  /** Salvata e senza niente da fare: NON è un errore, ed è il motivo per cui non
   *  passa da `saveBlock` — che è rosso, e il rosso qui direbbe una bugia. */
  const upToDate = valid && !dirty;
  const saveBlock = valid
    ? null
    : closed
      ? 'La giornata è chiusa: la formazione non è più modificabile.'
      : defenceBlock ??
      classicErrors[0] ??
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
  /** PERCHÉ QUESTO MODULO NON SI PUÒ — null se si può.
   *
   *  Una funzione sola, chiamata da DUE posti: da chi disegna la pastiglia, per
   *  spegnerla, e da chi la applica, per rifiutare. Erano due regole diverse, ed è
   *  il modo in cui una pastiglia poteva essere accesa e poi rifiutata al tocco:
   *  quella che spegneva guardava solo il numero di difensori, quella che
   *  applicava guardava anche i congelati di ogni reparto. Con due attaccanti che
   *  avevano già giocato, il 4-5-1 sembrava disponibile e non lo era. */
  const moduleBlock = (m: [number, number, number]): string | null => {
    if (closed) return 'La giornata è chiusa.';
    if (defenceLocked && m[0] !== lock!.defence_count) {
      return `La giornata è cominciata: i difensori restano ${lock!.defence_count}. `
        + 'Puoi ancora cambiare centrocampo e attacco.';
    }
    const target: Record<PlayerRole, number> = { GK: 1, DEF: m[0], MID: m[1], ATT: m[2] };
    for (const role of ROLES) {
      // Un reparto non si può stringere sotto il numero dei suoi congelati: quelli
      // restano dove sono, e il modulo li vorrebbe fuori.
      const frozen = starterIds.filter(
        (id) => lockedIds.has(id) && byId.get(id)?.role === role,
      ).length;
      if (frozen > target[role]) {
        return `Non puoi passare a ${moduleName(m)}: hai ${frozen} ${ROLE_WORD_PLURAL[role]} `
          + 'con la partita già iniziata, e restano dove sono.';
      }
    }
    return null;
  };

  const applyModule = (m: [number, number, number]) => {
    const why = moduleBlock(m);
    if (why) {
      setModuleNote(why);
      return;
    }
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

  /** SUGGERISCI SI SPEGNE QUANDO LA GIORNATA È COMINCIATA.
   *
   *  Rifà l'undici da capo per forma, e a giornata cominciata è la cosa più
   *  sbagliata che possa fare: butta via scelte deliberate su giocatori che non
   *  si possono più rimettere a posto, e può cambiare il numero di difensori —
   *  che dal primo calcio d'inizio è fissato. Sarebbe un pulsante offerto
   *  dall'app che produce uno stato che l'app stessa rifiuta di salvare.
   *
   *  Provato: nello scenario di prova proponeva un portiere diverso da quello
   *  schierato, a otto titolari su undici ormai immobili. */
  const suggestBlock = closed
    ? 'La giornata è chiusa.'
    : defenceLocked || lockedIds.size > 0
      ? 'La giornata è cominciata: rifare la formazione da capo sposterebbe giocatori che non puoi più muovere.'
      : null;

  const noticeLater = (msg: string) => {
    setNotice(msg);
    setTimeout(() => setNotice(null), 4200);
  };

  // Estratto perché lo chiamano due bottoni: quello in cima su desktop e quello
  // nella barra in fondo sul telefono.
  const onSuggest = () => {
    if (suggestBlock) {
      noticeLater(suggestBlock);
      return;
    }
    setStarterIds(fromSuggestion(ctx.suggested_lineup));
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
      // Da qui in poi non c'è più niente da mandare, finché non si tocca qualcosa.
      // Solo dopo l'`await`, e solo se non ha sollevato: segnare «salvata» una
      // formazione che il server ha rifiutato sarebbe la bugia peggiore di tutte.
      setSavedPrint(lineupPrint(gkId, starterIds, benchIds, sendAll));
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Errore nel salvataggio');
    } finally {
      setSaving(false);
      setTimeout(() => setToast(null), 2800);
    }
  };

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
                  ? lock.mode === 'own' && lock.closes_with
                    ? `Formazione chiusa: ${lock.closes_with.home}-${lock.closes_with.away} è iniziata (${fmtDeadline(lock.closes_at)}) e avevi un giocatore in quella partita.`
                    : 'Giornata chiusa: la formazione non è più modificabile.'
                  : lock.mode === 'player'
                    ? lockedIds.size
                      ? `${lockedIds.size} giocatori hanno la partita iniziata e restano dove sono; sugli altri puoi decidere fino a ${fmtDeadline(lock.closes_at)}.`
                      : `Ogni giocatore si blocca all'inizio della sua partita. Ultimo calcio d'inizio: ${fmtDeadline(lock.closes_at)}.`
                    : lock.mode === 'own'
                      ? lock.closes_with
                        ? `Si schiera fino a ${fmtDeadline(lock.closes_at)}, con ${lock.closes_with.home}-${lock.closes_with.away}: la prima partita in cui hai un giocatore.`
                        : `Si schiera fino alla prima partita in cui hai un giocatore: ${fmtDeadline(lock.closes_at)}.`
                      : `La formazione si blocca al primo calcio d'inizio della giornata: ${fmtDeadline(lock.closes_at)}.`}
              </div>
            ) : null}
            {/* «SE NON LA TOCCHI, GIOCA QUESTA». Detto qui perche' e' vero:
                la formazione della giornata prima e' anche quella che il punteggio
                usa per chi non schiera, e senza scriverlo la pagina sembrerebbe
                proporre una bozza qualunque. */}
            {ctx.lineup_source?.kind === 'baseline' ? (
              <div className="mt-1 text-[11px] font-semibold text-ink-soft">
                Proposta dal suggeritore quando la rosa si è completata: se non la tocchi, gioca questa.
              </div>
            ) : null}
            {ctx.lineup_source?.kind === 'previous' ? (
              <div className="mt-1 text-[11px] font-semibold text-ink-soft">
                Ripresa dalla giornata {ctx.lineup_source.from_matchday}: se non la tocchi, gioca questa.
                {ctx.lineup_source.vacant_roles.length ? (
                  <span className="text-bad">
                    {' '}Mancano {ctx.lineup_source.vacant_roles.length}{' '}
                    {ctx.lineup_source.vacant_roles.length === 1 ? 'giocatore' : 'giocatori'} che non
                    {ctx.lineup_source.vacant_roles.length === 1 ? ' è' : ' sono'} più in rosa.
                  </span>
                ) : null}
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
                title={suggestBlock ?? undefined}
              >
                Suggerisci XI
              </Button>
              {/* A grey Salva that does not say why is a dead end: the tooltip carries
                  the first thing standing in the way. */}
              <Button
                onClick={onSave}
                disabled={!canSave || saving}
                title={saveBlock ?? (upToDate ? 'Già salvata: non c\'è niente di nuovo da mandare.' : undefined)}
              >
                {saving ? 'Salvataggio…' : upToDate ? 'Salvata ✓' : 'Salva'}
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
                const why = moduleBlock(m);
                return (
                  <button
                    key={moduleName(m)}
                    type="button"
                    onClick={() => (why ? setModuleNote(why) : applyModule(m))}
                    aria-pressed={active}
                    aria-disabled={why ? true : undefined}
                    disabled={closed}
                    className={clsx(
                      'shrink-0 rounded-full border px-3 py-1.5 text-xs font-bold tabular-nums transition',
                      active
                        ? 'border-brand bg-brand text-on-brand'
                        : 'border-line bg-surface text-ink-soft hover:bg-surface-2',
                      // Spento, non nascosto: sparire non spiega niente, e il tocco
                      // sul bottone spento porta il motivo qui sotto.
                      !active && why && 'opacity-40',
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
            {/* LA REGOLA PER INTERO, dove c'e' spazio per dirla. E' una regola
                della lega, non il prezzo di una modifica: vale per chi schiera,
                che abbia toccato qualcosa o no. La parte che nessuno indovina e'
                la panchina letta due volte — prima i pari reparto, poi gli altri —
                e va detta cosi', perche' «entrano solo difensori» farebbe temere
                un buco che non esiste. */}
            {defenceLocked ? (
              <div className="mt-1.5 rounded-lg bg-warn-bg px-2.5 py-1.5 text-[11px] leading-snug text-warn">
                <b>Il tuo primo giocatore è sceso in campo: i difensori restano {lock!.defence_count}.</b>{' '}
                Puoi ancora cambiare un difensore con un altro difensore. Nei cambi dalla panchina,
                in difesa entra prima un difensore, nel tuo ordine; se nessuno ha voto, entra il
                primo degli altri. Allo stesso modo un difensore copre un altro ruolo solo se
                nessun altro ha voto.
              </div>
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
          {/* Corta sul telefono, dove il campo e' l'unica superficie e ogni riga di
              spiegazione e' spazio tolto a quello che spiega. Le due mosse sono
              anche le uniche possibili: si scoprono al primo tocco. */}
          <div className="mt-1 text-[11px] text-ink-faint">
            Tocca un giocatore per i suoi dati, un posto vuoto per riempirlo.
            <span className="hidden lg:inline">
              {' '}{isClassic ? 'Schieramento per ruolo.' : 'Posizione attesa di ogni titolare (dai dati storici).'}
              {' '}Il portiere veste la muta invertita.
              {isClassic ? null : " Toccando un giocatore si accendono le sue zone d'influenza."}
            </span>
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
            {isClassic ? null : (
              <div className="mt-1 text-[11px] text-ink-faint">Clicca il nome per vederne le zone sulla mappa.</div>
            )}

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
          <div className="mt-0.5 hidden text-[11px] text-ink-faint lg:block">
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
              <Fragment key={p.player_id}>
              {/* IL MURO. A frozen bench player is a wall: the free rows above him
                  stay above, the ones below stay below, and the drag stops here.
                  Drawn so the limit is seen before it is felt. */}
              {lockedIds.has(p.player_id) && i > 0 ? (
                <div
                  className="flex items-center gap-2 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[.12em] text-warn"
                  aria-hidden="true"
                >
                  <span className="h-px flex-1 border-t border-dashed border-warn" />
                  nessuno passa di qui
                  <span className="h-px flex-1 border-t border-dashed border-warn" />
                </div>
              ) : null}
              <RosterRow
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
              </Fragment>
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
                  // `valid` e non `canSave`: da quando il pulsante si spegne a
                  // formazione salvata, `canSave` è falso anche quando va tutto
                  // bene — e il contatore diventava rosso su un undici perfetto.
                  // Il colore qui parla della FORMAZIONE, non del pulsante.
                  valid ? 'text-good' : 'text-bad',
                )}
              >
                {starterIds.length}/{XI}
              </span>
              <span className="text-[11px] uppercase tracking-wide text-ink-faint">titolari</span>
            </div>
            {toast ? (
              <div className="mt-0.5 text-[11px] font-semibold leading-snug text-good">{toast}</div>
            ) : notice ? (
              <div className="mt-0.5 text-[11px] font-semibold leading-snug text-ink-soft">{notice}</div>
            ) : saveBlock ? (
              <div className="mt-0.5 text-[11px] font-semibold leading-snug text-bad">{saveBlock}</div>
            ) : upToDate ? (
              <div className="mt-0.5 text-[11px] leading-snug text-ink-faint">
                Salvata. Niente di nuovo da mandare.
              </div>
            ) : defenceLocked ? (
              /* LA REGOLA DI LEGA, detta a chi schiera e non a chi modifica: i
                 cambi dalla panchina sono una cosa che succedera' dopo, quando
                 questa pagina sara' chiusa da un pezzo, e vanno nominati. */
              <div className="mt-0.5 text-[11px] leading-snug text-warn">
                Nei cambi, in difesa entra prima un difensore; se nessuno ha voto, il primo degli altri.
              </div>
            ) : null}
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={onSuggest}
            className={clsx('shrink-0', suggestBlock && 'opacity-45')}
          >
            Suggerisci
          </Button>
          <Button onClick={onSave} disabled={!canSave || saving} className="shrink-0">
            {saving ? 'Salvo…' : upToDate ? 'Salvata ✓' : 'Salva'}
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
        /* NIENTE ZONE IN CLASSIC. In questa modalità il punteggio non guarda dove
           un giocatore si muove: guarda il suo voto e il suo ruolo. Le zone gialle
           erano quindi un'informazione vera ma senza conseguenze — bella da
           vedere, e proprio per questo fuorviante: chi la vede accendersi mentre
           schiera pensa che stia decidendo qualcosa. L'idea di aura, se va
           introdotta, va introdotta dove conta, non come decorazione altrove. */
        footprint={null}
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

  /** QUANTO PUÒ ESSERE LARGA L'ETICHETTA COL NOME, senza poter toccare quella del
   *  vicino.
   *
   *  Non un numero fisso: era `max-w-[70px]`, e settanta pixel su una linea da
   *  cinque — dove fra un compagno e l'altro ce ne sono cinquantatré — è già una
   *  sovrapposizione, solo che con caratteri da otto pixel non la si vedeva.
   *  Ingrandire il testo l'avrebbe resa visibile.
   *
   *  Qui la larghezza È la distanza dal vicino più vicino, misurata sull'asse
   *  orizzontale COME SI VEDE (che gira col campo), meno un filo. Così due
   *  etichette non possono toccarsi qualunque cosa succeda sopra: linee da tre o
   *  da cinque, disposizione a reparti o sparsa per heatmap, campo in piedi o
   *  coricato. Chi è solo sulla sua riga si prende il tetto e non di più: un nome
   *  lungo come mezzo campo sarebbe brutto quanto una sovrapposizione.
   *
   *  Il vicino conta solo se è ANCHE vicino in verticale: due giocatori su linee
   *  diverse hanno le etichette a settanta pixel di distanza fra loro e non si
   *  incontrano mai, per quanto lunghi siano i nomi. */
  const seenX = (d: { left: number; top: number }) => (vertical ? d.top : d.left);
  const seenY = (d: { left: number; top: number }) => (vertical ? 100 - d.left : d.top);
  const labelRoom = (d: { left: number; top: number }, selfId: number) => {
    let nearest = Infinity;
    for (const o of dots) {
      // Per IDENTITÀ e non per riferimento: chi chiama passa le coordinate, non
      // l'oggetto, quindi un confronto `===` non riconoscerebbe mai il pallino
      // stesso — che dista zero da sé, e azzererebbe la larghezza di ogni
      // etichetta.
      if ('p' in o && o.p.player_id === selfId) continue;
      if (Math.abs(seenY(o) - seenY(d)) > 12) continue;
      nearest = Math.min(nearest, Math.abs(seenX(o) - seenX(d)));
    }
    return Math.min(32, nearest);
  };

  return (
    <div
      className={clsx(
        'relative mt-3 w-full overflow-hidden rounded-xl border border-good/40 shadow-inner',
        vertical ? 'aspect-[5/7]' : 'aspect-[7/5]',
      )}
      /* IL TAGLIO DELL'ERBA.
       *
       *  Le strisce alternate sono la citazione di `.vf-hero`, l'intestazione
       *  dell'app, che fa la stessa cosa con lo stesso mezzo — bianco a bassissima
       *  opacità in bande ripetute su un fondo verde. Il campo entra così nella
       *  stessa famiglia invece di essere un rettangolo verde qualunque.
       *
       *  Chiaro E scuro, non chiaro e basta: una sola banda schiarita si legge
       *  come una macchia di luce, due bande opposte si leggono come due passate
       *  del rullo in versi contrari, che è quello che sono.
       *
       *  Dieci bande, che sono DUE PER ZONA: la griglia del motore è 5×4, e la
       *  profondità sta sui cinque. Le mezzerie cadono così sui confini delle
       *  zone, e quando si accende la heatmap gialla il taglio dell'erba non la
       *  contraddice — le passa sotto in righe che finiscono dove finisce lei.
       *
       *  Il verso gira col campo, come tutto il resto qui dentro: le bande sono
       *  perpendicolari alla lunghezza, cioè orizzontali quando la porta sta in
       *  basso e verticali quando sta a sinistra. */
      style={{
        backgroundImage: [
          `repeating-linear-gradient(${vertical ? '180deg' : '90deg'},`
          // Provate tre intensità affiancate: sotto queste il taglio non si legge,
          // sopra le bande cominciano a spezzare la heatmap gialla — che è
          // l'unica cosa sul campo a portare informazione, e vince lei.
          + ' rgb(255 255 255 / .11) 0 10%, rgb(0 0 0 / .07) 10% 20%)',
          `linear-gradient(${vertical ? 'to top' : 'to right'}, #16a34a, #22c55e)`,
        ].join(', '),
      }}
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
            <span className="mt-0.5 rounded bg-black/45 px-1 text-[10px] font-bold leading-tight text-white/90">
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
          /* Il tetto sta QUI e non sull'etichetta: una percentuale si risolve
             sull'elemento che contiene, e l'etichetta è contenuta dal bottone —
             largo quanto il suo contenuto, cioè una quarantina di pixel. Il
             bottone invece è posizionato dentro il campo, quindi la sua
             percentuale è una percentuale DI CAMPO, che è la misura giusta. */
          style={{ ...place(left, top), maxWidth: `${labelRoom({ left, top }, p.player_id)}%` }}
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
          <span className="mt-0.5 flex max-w-full items-center gap-0.5 rounded bg-black/55 px-1 text-[10px] font-bold leading-tight text-white">
            {showRole ? <span className="shrink-0 opacity-80">{ROLE_LABEL_SHORT[p.role]}</span> : null}
            <span className="truncate">{p.name.split(/\s+/).pop()}</span>
          </span>
        </button>
    );
  }
}
