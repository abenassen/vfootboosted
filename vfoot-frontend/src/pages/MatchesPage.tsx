import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { getLeagueFixtures } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { useCompetitionContext, useCompetitionFromQuery } from '../league/CompetitionContext';
import { competitionFormatLabel } from '../league/competitionFormat';
import { Badge, Card, SectionTitle } from '../components/ui';
import { useResetOnChange, useUrlParam } from '../utils/useUrlParam';
import Crest from '../components/Crest';
import type {
  CompetitionBlocker,
  CompetitionRoundRow,
  CompetitionStagePlan,
  LeagueFixtureItem,
} from '../types/league';

/** One entry of the round selector.
 *
 *  Not one per round, because a whole PHASE can be undrawn: a group stage entered
 *  by the top four of the championship is six rounds of "da definire", and six
 *  chips saying the same thing is not a calendar. A run of undrawn rounds fed by
 *  the same rule collapses into one entry that presents the rule instead. */
type CalendarEntry =
  | { kind: 'round'; key: string; label: string; roundNo: number; realMatchday: number | null }
  | {
      kind: 'phase';
      key: string;
      label: string;
      plans: CompetitionStagePlan[];
      rows: CompetitionRoundRow[];
    };

const BLOCKER_TONE: Record<CompetitionBlocker['kind'], string> = {
  da_giocare: 'border-line bg-surface-2 text-ink-soft',
  da_conteggiare: 'border-good/40 bg-good-bg text-good',
  recupero: 'border-warn/40 bg-warn-bg text-warn',
  sorgente_da_definire: 'border-line bg-surface-2 text-ink-soft',
  senza_giornate: 'border-bad/40 bg-bad-bg text-bad',
};

/** What the reader can do about it, which is the part the raw reason does not say. */
const BLOCKER_HINT: Record<CompetitionBlocker['kind'], string> = {
  da_giocare: '',
  da_conteggiare: 'Finché la giornata non viene conclusa, questa fase non può essere sorteggiata.',
  recupero:
    'La lega è andata avanti, ma questa fase legge una giornata ferma in attesa del recupero: ' +
    'sarà sorteggiata quando quella giornata verrà conteggiata, e se nel frattempo le sue ' +
    'giornate saranno passate verrà spostata più avanti.',
  sorgente_da_definire: '',
  senza_giornate:
    'Il sorteggio non verrà più fatto: giocarla su giornate già iniziate darebbe una ' +
    'competizione senza formazioni, decisa da partite scelte da nessuno. Da Gestione lega ' +
    'puoi annullarla, oppure lasciarla lì e riproporla la stagione prossima.',
};

/** The one blocker that is not a wait: nothing will unblock it. */
const isTerminal = (b: CompetitionBlocker | null | undefined) => b?.kind === 'senza_giornate';

// Calendar of the CURRENTLY selected competition (set via the competition switcher):
// a round selector, the round's fixtures, each clickable to the rich detail.
export default function MatchesPage() {
  const { selectedLeagueId, selectedLeague } = useLeagueContext();
  const { selectedCompetitionId, selectedCompetition } = useCompetitionContext();
  // Arrivare qui DA una competizione la seleziona: vedi useCompetitionFromQuery.
  useCompetitionFromQuery();
  const [fixtures, setFixtures] = useState<LeagueFixtureItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // IL TURNO STA NELL'INDIRIZZO (`?turno=3`), non qui dentro: si guarda un turno
  // passato, si apre una partita, si torna indietro — e con lo stato dentro il
  // componente si ripartiva ogni volta dal turno in corso (v. useUrlParam).
  const [turno, setTurno] = useUrlParam('turno');
  // Cambiare competizione lo dimentica: è il conto interno di un'altra. Non al
  // montaggio, però, o cancellerebbe il turno appena ripescato dall'indirizzo.
  useResetOnChange(
    selectedLeagueId && selectedCompetitionId
      ? `${selectedLeagueId}:${selectedCompetitionId}`
      : null,
    useCallback(() => setTurno(null), [setTurno]),
  );

  useEffect(() => {
    if (!selectedLeagueId || !selectedCompetitionId) {
      setFixtures([]);
      return;
    }
    setLoading(true);
    setError(null);
    void getLeagueFixtures(selectedLeagueId, selectedCompetitionId)
      .then(setFixtures)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [selectedLeagueId, selectedCompetitionId]);

  const isKnockout = selectedCompetition?.competition_type === 'knockout';

  /** A round's name. When parallel groups share it there is no single stage to
   *  name it after — taking the first fixture's label made a whole round read as
   *  "Girone B" while half of it was Girone A.
   *
   *  TURNO, non "Giornata": questo è il conto interno della competizione, e
   *  "giornata" è riservata a quella del campionato vero. */
  const roundLabel = (r: number) => {
    const inRound = fixtures.filter((f) => f.round_no === r);
    const stages = new Set(inRound.map((f) => f.stage_name).filter(Boolean));
    if (stages.size === 1) return inRound[0]?.round_label ?? `Turno ${r}`;
    return `Turno ${r}`;
  };

  /** The rounds the competition PLANS, not the ones its fixtures happen to have.
   *
   *  A competition whose stages are fed by rules has rounds long before it has
   *  matches — that is the whole shape of a cup — and reading them off the fixtures
   *  made the final of a cup being played simply not exist. The fixtures are still
   *  the fallback: a competition built before the plan existed, and the mock API,
   *  both send an empty plan. */
  const planRows = useMemo<CompetitionRoundRow[]>(() => {
    const plan = selectedCompetition?.rounds ?? [];
    if (plan.length) return plan;
    return [...new Set(fixtures.map((f) => f.round_no))]
      .sort((a, b) => a - b)
      .map((r) => ({
        round_no: r,
        stage_id: null,
        stage_name: fixtures.find((f) => f.round_no === r)?.stage_name ?? '',
        stage_type: isKnockout ? 'knockout' : 'round_robin',
        local_round: r,
        local_rounds: 0,
        label: roundLabel(r),
        real_matchday: fixtures.find((f) => f.round_no === r)?.real_matchday ?? null,
        fixtures: fixtures.filter((f) => f.round_no === r).length,
      }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCompetition, fixtures, isKnockout]);

  const entries = useMemo<CalendarEntry[]>(() => {
    const pendingStages = (selectedCompetition?.stage_plan ?? []).filter((s) => s.pending);
    const plansFor = (rno: number) =>
      pendingStages.filter((s) => rno >= s.first_round && rno <= s.last_round);

    const out: CalendarEntry[] = [];
    let run: { id: string; plans: CompetitionStagePlan[]; rows: CompetitionRoundRow[] } | null = null;
    const flush = () => {
      if (!run) return;
      out.push({
        kind: 'phase',
        key: `p${run.rows[0].round_no}`,
        // Parallel groups share their rounds, so a phase can be two stages wide.
        label: [...new Set(run.plans.map((p) => p.name))].join(' / '),
        plans: run.plans,
        rows: run.rows,
      });
      run = null;
    };

    for (const row of planRows) {
      const plans = plansFor(row.round_no);
      if (plans.length) {
        const id = plans.map((p) => p.stage_id).join(',');
        if (run && run.id !== id) flush();
        if (!run) run = { id, plans, rows: [] };
        run.rows.push(row);
        continue;
      }
      flush();
      out.push({
        kind: 'round',
        key: `r${row.round_no}`,
        label: row.fixtures ? roundLabel(row.round_no) : row.label,
        roundNo: row.round_no,
        realMatchday: row.real_matchday,
      });
    }
    flush();
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planRows, selectedCompetition, fixtures]);

  /** Where the calendar opens. The first round is almost never the answer: in
   *  February it means scrolling past twenty played rounds to reach the one you
   *  are in. In order of what somebody opening this page wants:
   *    1. the LAST round that has begun and has not been counted — the one being
   *       played, or the one waiting for the admin;
   *    2. otherwise the first round still to come — including a phase that has not
   *       been drawn, which is the "what happens next" of a cup;
   *    3. otherwise the last one, because the season is over. */
  const defaultEntry = useMemo(() => {
    const begun = entries.filter(
      (e) =>
        e.kind === 'round' &&
        fixtures.some((f) => f.round_no === e.roundNo && f.lineup_locked && f.status !== 'finished'),
    );
    if (begun.length) return begun[begun.length - 1].key;
    const next = entries.find(
      (e) =>
        e.kind === 'phase' || fixtures.some((f) => f.round_no === e.roundNo && f.status !== 'finished'),
    );
    return next?.key ?? entries[entries.length - 1]?.key ?? null;
  }, [entries, fixtures]);

  /** Il turno chiesto dall'indirizzo. Si nomina col NUMERO e non con la chiave
   *  interna (`r3`, `p5`) perché l'indirizzo lo legge anche una persona, e perché
   *  una fase non sorteggiata copre più turni: chiedendo uno dei suoi si apre
   *  lei. Un numero che questa competizione non ha vale come se non ci fosse. */
  const wantedKey = useMemo(() => {
    const n = turno != null ? Number(turno) : null;
    if (n == null || !Number.isFinite(n)) return null;
    return (
      entries.find((e) =>
        e.kind === 'round' ? e.roundNo === n : e.rows.some((r) => r.round_no === n),
      )?.key ?? null
    );
  }, [entries, turno]);

  const activeKey = wantedKey ?? defaultEntry;
  const active = entries.find((e) => e.key === activeKey) ?? null;
  const shown = useMemo(
    () => (active?.kind === 'round' ? fixtures.filter((f) => f.round_no === active.roundNo) : []),
    [fixtures, active],
  );
  const roundRealMatchday =
    active?.kind === 'round'
      ? shown.find((f) => typeof f.real_matchday === 'number')?.real_matchday ?? active.realMatchday
      : null;
  // Grouped by stage, in the order the stages appear in the round.
  const shownByStage = useMemo(() => {
    const map = new Map<string | null, LeagueFixtureItem[]>();
    for (const f of shown) {
      const key = f.stage_name ?? null;
      const list = map.get(key);
      if (list) list.push(f);
      else map.set(key, [f]);
    }
    return [...map.entries()];
  }, [shown]);
  const myTeamName = selectedLeague?.team_name?.trim() || null;
  const seasonName = selectedLeague?.reference_season?.competition ?? 'Serie A';

  if (!selectedLeagueId) return <div className="text-sm text-ink-faint">Seleziona una lega per vedere le partite.</div>;
  if (!selectedCompetitionId)
    return <div className="text-sm text-ink-faint">Questa lega non ha ancora competizioni.</div>;
  if (loading) return <div className="text-sm text-ink-faint">Caricamento partite…</div>;
  if (error) return <div className="text-sm text-bad">Errore: {error}</div>;

  const plannedRounds = planRows.length;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-center gap-2">
          <SectionTitle>{selectedCompetition?.name ?? 'Calendario'}</SectionTitle>
          <Badge tone={isKnockout ? 'amber' : 'blue'}>
            {selectedCompetition ? competitionFormatLabel(selectedCompetition) : ''}
          </Badge>
        </div>
        {/* TURNI a prescindere dal formato: questo è il conto interno della
            competizione, e "giornata" è riservata a quella del campionato vero —
            che è un altro numero e viene detto sotto ogni turno ("si gioca sulla
            giornata 22 di Serie A"). */}
        <div className="mt-1 text-sm text-ink-soft">
          {fixtures.length} partite · {plannedRounds} {plannedRounds === 1 ? 'turno' : 'turni'}
        </div>
        <div className="mt-3 flex flex-wrap gap-1">
          {entries.map((e) => (
            <button
              key={e.key}
              onClick={() => setTurno(e.kind === 'round' ? e.roundNo : e.rows[0].round_no)}
              className={clsx(
                'rounded-lg px-2.5 py-1 text-xs font-semibold',
                e.key === activeKey
                  ? 'bg-ink text-paper'
                  : e.kind === 'phase'
                  ? // Drawn hollow: this one is a promise, not a fixture list.
                    'border border-dashed border-line text-ink-faint hover:border-line'
                  : 'bg-surface-2 text-ink-soft hover:bg-surface-2',
              )}
            >
              {e.kind === 'phase' || isKnockout ? e.label : e.roundNo}
            </button>
          ))}
        </div>
      </Card>

      {active?.kind === 'phase' ? (
        <PendingPhase entry={active} seasonName={seasonName} />
      ) : (
        <Card className="p-4">
          <SectionTitle>{active ? active.label : 'Giornata'}</SectionTitle>
          {/* Said once for the round, not repeated identically under every match of
              it: all the fixtures of a round share the same real matchday. */}
          {roundRealMatchday != null ? (
            <div className="mt-0.5 text-xs text-ink-faint">
              Si gioca sulla giornata {roundRealMatchday} di {seasonName}
            </div>
          ) : null}
          <div className="mt-3 space-y-4">
            {shown.length ? (
              // Parallel groups share the same rounds (order_index 1 side by side),
              // so a round holds fixtures from Girone A AND Girone B. Flattened they
              // read as one league, and the round label — taken from whichever
              // fixture came first — named a single group for all of them.
              shownByStage.map(([stageName, group]) => (
                <div key={stageName ?? 'unico'}>
                  {shownByStage.length > 1 && stageName ? (
                    <div className="mb-1.5 text-xs font-bold uppercase tracking-wide text-ink-faint">
                      {stageName}
                    </div>
                  ) : null}
                  <div className="space-y-2">
                    {group.map((f) => (
                      <FixtureRow key={f.fixture_id} f={f} myTeam={myTeamName} />
                    ))}
                  </div>
                </div>
              ))
            ) : (
              <div className="text-sm text-ink-faint">Nessuna partita in questa giornata.</div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}

/** A phase whose teams are still to be decided: the RULE, in place of a fixture list.
 *
 *  Two shapes at once, and deliberately so, because the undetermined part of a
 *  calendar comes in two sizes. A single tie — the final — is named and explained
 *  in one line ("Le vincenti di «Semifinali»"): that is all there is to say, and
 *  saying nothing (which is what the calendar did) makes a cup in progress look
 *  finished. A whole phase — a group stage entered by the top four of a
 *  championship — would be six identical placeholder matches, so the rule replaces
 *  the list entirely and the matchdays it will occupy are given as a span. */
function PendingPhase({ entry, seasonName }: { entry: Extract<CalendarEntry, { kind: 'phase' }>; seasonName: string }) {
  const mds = entry.rows.map((r) => r.real_matchday).filter((m): m is number => typeof m === 'number');
  const first = mds.length ? Math.min(...mds) : null;
  const last = mds.length ? Math.max(...mds) : null;
  const matches = entry.plans.reduce(
    (n, p) => n + p.expected_fixtures_per_round * Math.max(1, entry.rows.length),
    0,
  );
  // One line for the phase: the worst blocker across its stages, since the reader
  // needs to know what is holding it up, not how many things are.
  const blocker = entry.plans.map((p) => p.blocker).find(Boolean) ?? null;
  // "Da definire" would be a lie here: nothing is going to define it. The season has
  // no matchday left, so the phase is not late — it is over before it started.
  const terminal = isTerminal(blocker);

  return (
    <Card className={clsx('border-2 border-dashed p-4', terminal ? 'border-bad/40' : 'border-line')}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SectionTitle className="!mb-0">{entry.label}</SectionTitle>
        <span
          className={clsx(
            'rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide',
            terminal ? 'bg-bad-bg text-bad' : 'bg-surface-2 text-ink-faint',
          )}
        >
          {terminal ? 'non più disputabile' : 'partecipanti da definire'}
        </span>
      </div>

      <div className="mt-3 rounded-xl bg-surface-2 p-3">
        <div className="text-[11px] font-bold uppercase tracking-wide text-ink-faint">Chi ci gioca</div>
        {entry.plans.map((p) => (
          <div key={p.stage_id} className="mt-1 text-sm text-ink-soft">
            {entry.plans.length > 1 ? <b>{p.name}: </b> : null}
            {p.rule_text || 'da sorteggiare'}
          </div>
        ))}
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded-xl border border-line p-3">
          <div className="text-[11px] font-bold uppercase tracking-wide text-ink-faint">Quando</div>
          <div className="mt-0.5 text-sm text-ink-soft">
            {terminal
              ? // The reserved matchdays are still in the plan, but they have gone
                // by — printing them as a date would read as a promise.
                'Le giornate riservate sono passate.'
              : first == null
              ? 'Nessuna giornata riservata.'
              : first === last
              ? `Giornata ${first} di ${seasonName}`
              : `Giornate ${first}–${last} di ${seasonName}`}
          </div>
        </div>
        <div className="rounded-xl border border-line p-3">
          <div className="text-[11px] font-bold uppercase tracking-wide text-ink-faint">Quante partite</div>
          <div className="mt-0.5 text-sm text-ink-soft">
            {matches > 0
              ? `${matches} ${matches === 1 ? 'partita' : 'partite'} in ${entry.rows.length} ${
                  entry.rows.length === 1 ? 'turno' : 'turni'
                }`
              : 'da definire'}
          </div>
        </div>
      </div>

      {blocker ? (
        <div className={clsx('mt-3 rounded-xl border p-3 text-sm', BLOCKER_TONE[blocker.kind])}>
          <b>In attesa:</b> {blocker.detail}.
          {BLOCKER_HINT[blocker.kind] ? (
            <div className="mt-1 text-xs opacity-90">{BLOCKER_HINT[blocker.kind]}</div>
          ) : null}
        </div>
      ) : (
        <div className="mt-3 text-xs text-ink-faint">
          La regola è già soddisfatta: il sorteggio avviene alla prossima chiusura di giornata.
        </div>
      )}
    </Card>
  );
}

function FixtureRow({ f, myTeam }: { f: LeagueFixtureItem; myTeam: string | null }) {
  const finished = f.status === 'finished' && f.score;
  // A round that has begun and has not been counted carries a PARTIAL score, the
  // same number its tabellino shows. Before this the calendar said "vs" over a
  // match that was two thirds played.
  const partial = !finished && !!f.score;
  const hasScore = finished || partial;
  const hs = f.score?.home_total ?? 0;
  const as = f.score?.away_total ?? 0;
  const homeWin = !!finished && hs > as;
  const awayWin = !!finished && as > hs;
  // Both decided by the server: opening a fixture with no detail lands on a 404,
  // and a lineup needs a roster the calendar never loads. In classic `has_detail`
  // si accende anche PRIMA del calcio d'inizio, appena una delle due ha schierato:
  // le formazioni sono pubbliche (v. `_open_before_kickoff` lato server).
  const openable = f.has_detail ?? f.status === 'finished';
  const canSetLineup = f.can_set_lineup ?? false;

  const body = (
    <div className="flex items-center gap-3">
      <div className="flex flex-1 items-center justify-end gap-2">
        <span className={homeWin ? 'font-bold text-ink' : 'text-ink-soft'}>{f.home_team.name}</span>
        <Crest descriptor={f.home_team.crest} teamName={f.home_team.name} size={24} />
      </div>
      {/* A played match shows a score plate; an unplayed one used to show "vs" in
          the same white box with a shadow, which reads as a button. */}
      {hasScore ? (
        <div className="flex flex-col items-center">
          <div className="flex items-center gap-1 rounded-lg bg-surface px-2 py-1 font-mono text-sm font-bold shadow-sm">
            <span className={homeWin ? 'text-good' : 'text-ink-soft'}>{Math.round(hs)}</span>
            <span className="text-ink-faint">-</span>
            <span className={awayWin ? 'text-good' : 'text-ink-soft'}>{Math.round(as)}</span>
          </div>
          {partial ? (
            <span
              className={clsx(
                'mt-0.5 text-[9px] font-bold uppercase tracking-wide',
                f.score_in_progress
                  ? 'text-live'
                  : f.score_provisional
                    ? 'text-warn'
                    : 'text-ink-faint',
              )}
            >
              {/* TRE stati, non due. "live" = c'è una partita vera sul campo;
                  "provvisorio" = si è finito di giocare ma il fornitore non ha
                  ancora confermato i dati, che dura un'ora buona dopo il fischio;
                  "da conteggiare" = il numero è definitivo, manca solo che
                  l'amministratore chiuda. I primi due erano detti con la stessa
                  parola, e per quell'ora il calendario scriveva "live" su partite
                  finite — allo stesso utente a cui era appena arrivata la notifica
                  di fine partita. */}
              {f.score_in_progress
                ? 'live'
                : f.score_provisional
                  ? 'provvisorio'
                  : 'da conteggiare'}
            </span>
          ) : null}
        </div>
      ) : (
        <span className="px-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">vs</span>
      )}
      <div className="flex flex-1 items-center gap-2">
        <Crest descriptor={f.away_team.crest} teamName={f.away_team.name} size={24} />
        <span className={awayWin ? 'font-bold text-ink' : 'text-ink-soft'}>{f.away_team.name}</span>
      </div>
    </div>
  );

  return (
    <div
      className={clsx(
        'rounded-xl border px-3 py-2.5',
        f.is_user_involved ? 'border-line bg-surface' : 'border-line bg-surface-2',
      )}
    >
      {openable ? (
        <Link to={`/matches/${f.fixture_id}`} className="block transition hover:opacity-80">
          {body}
        </Link>
      ) : (
        <div title="Niente da aprire: nessuno ha ancora schierato per questa giornata">{body}</div>
      )}
      {canSetLineup ? (
        <div className="mt-2 flex justify-center">
          <Link
            to={`/squad/formation?competition=${f.competition_id}&matchday=${f.real_matchday}`}
            className="rounded-lg bg-ink px-2.5 py-1 text-[11px] font-semibold text-paper hover:opacity-90"
          >
            {/* Named, because on a row of two unfamiliar team names a bare
                "Imposta formazione" does not say whose match this is. */}
            Imposta la formazione di {myTeam ?? 'la tua squadra'}
          </Link>
        </div>
      ) : null}
    </div>
  );
}
