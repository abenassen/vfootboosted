import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { getLeagueFixtures } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { useCompetitionContext } from '../league/CompetitionContext';
import { competitionFormatLabel } from '../league/competitionFormat';
import { Badge, Card, SectionTitle } from '../components/ui';
import Crest from '../components/Crest';
import type { LeagueFixtureItem } from '../types/league';

// Calendar of the CURRENTLY selected competition (set via the competition switcher):
// a round selector, the round's fixtures, each clickable to the rich detail.
export default function MatchesPage() {
  const { selectedLeagueId, selectedLeague } = useLeagueContext();
  const { selectedCompetitionId, selectedCompetition } = useCompetitionContext();
  const [fixtures, setFixtures] = useState<LeagueFixtureItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState<number | null>(null);

  useEffect(() => {
    setRound(null);
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
  const rounds = useMemo(() => [...new Set(fixtures.map((f) => f.round_no))].sort((a, b) => a - b), [fixtures]);
  /** Where the calendar opens. The first round is almost never the answer: in
   *  February it means scrolling past twenty played rounds to reach the one you
   *  are in. In order of what somebody opening this page wants:
   *    1. the LAST round that has begun and has not been counted — the one being
   *       played, or the one waiting for the admin;
   *    2. otherwise the first round still to come;
   *    3. otherwise the last one, because the season is over. */
  const defaultRound = useMemo(() => {
    const begun = rounds.filter((r) =>
      fixtures.some((f) => f.round_no === r && f.lineup_locked && f.status !== 'finished'));
    if (begun.length) return begun[begun.length - 1];
    const next = rounds.find((r) => fixtures.some((f) => f.round_no === r && f.status !== 'finished'));
    return next ?? rounds[rounds.length - 1] ?? null;
  }, [rounds, fixtures]);
  const activeRound = round ?? defaultRound;
  const shown = useMemo(() => fixtures.filter((f) => f.round_no === activeRound), [fixtures, activeRound]);
  /** A round's name. When parallel groups share it there is no single stage to
   *  name it after — taking the first fixture's label made a whole round read as
   *  "Girone B" while half of it was Girone A. */
  const roundLabel = (r: number) => {
    const inRound = fixtures.filter((f) => f.round_no === r);
    const stages = new Set(inRound.map((f) => f.stage_name).filter(Boolean));
    if (stages.size === 1) return inRound[0]?.round_label ?? `Giornata ${r}`;
    return `Giornata ${r}`;
  };
  const roundRealMatchday = shown.find((f) => typeof f.real_matchday === 'number')?.real_matchday ?? null;
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

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega per vedere le partite.</div>;
  if (!selectedCompetitionId)
    return <div className="text-sm text-slate-500">Questa lega non ha ancora competizioni.</div>;
  if (loading) return <div className="text-sm text-slate-500">Caricamento partite…</div>;
  if (error) return <div className="text-sm text-red-600">Errore: {error}</div>;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-center gap-2">
          <SectionTitle>{selectedCompetition?.name ?? 'Calendario'}</SectionTitle>
          <Badge tone={isKnockout ? 'amber' : 'blue'}>
            {selectedCompetition ? competitionFormatLabel(selectedCompetition) : ''}
          </Badge>
        </div>
        <div className="mt-1 text-sm text-slate-600">
          {fixtures.length} partite · {rounds.length} {isKnockout ? 'turni' : 'giornate'}
        </div>
        <div className="mt-3 flex flex-wrap gap-1">
          {rounds.map((r) => (
            <button
              key={r}
              onClick={() => setRound(r)}
              className={
                r === activeRound
                  ? 'rounded-lg bg-slate-900 px-2.5 py-1 text-xs font-semibold text-white'
                  : 'rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-200'
              }
            >
              {isKnockout ? roundLabel(r) : r}
            </button>
          ))}
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>{activeRound != null ? roundLabel(activeRound) : 'Giornata'}</SectionTitle>
        {/* Said once for the round, not repeated identically under every match of
            it: all the fixtures of a round share the same real matchday. */}
        {roundRealMatchday != null ? (
          <div className="mt-0.5 text-xs text-slate-500">
            Si gioca sulla giornata {roundRealMatchday} di {selectedLeague?.reference_season?.competition ?? 'Serie A'}
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
                  <div className="mb-1.5 text-xs font-bold uppercase tracking-wide text-slate-500">
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
            <div className="text-sm text-slate-500">Nessuna partita in questa giornata.</div>
          )}
        </div>
      </Card>
    </div>
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
  // and a lineup needs a roster the calendar never loads.
  const openable = f.has_detail ?? f.status === 'finished';
  const canSetLineup = f.can_set_lineup ?? false;

  const body = (
    <div className="flex items-center gap-3">
      <div className="flex flex-1 items-center justify-end gap-2">
        <span className={homeWin ? 'font-bold text-slate-900' : 'text-slate-600'}>{f.home_team.name}</span>
        <Crest descriptor={f.home_team.crest} teamName={f.home_team.name} size={24} />
      </div>
      {/* A played match shows a score plate; an unplayed one used to show "vs" in
          the same white box with a shadow, which reads as a button. */}
      {hasScore ? (
        <div className="flex flex-col items-center">
          <div className="flex items-center gap-1 rounded-lg bg-white px-2 py-1 font-mono text-sm font-bold shadow-sm">
            <span className={homeWin ? 'text-green-600' : 'text-slate-700'}>{Math.round(hs)}</span>
            <span className="text-slate-300">-</span>
            <span className={awayWin ? 'text-green-600' : 'text-slate-700'}>{Math.round(as)}</span>
          </div>
          {partial ? (
            <span
              className={clsx(
                'mt-0.5 text-[9px] font-bold uppercase tracking-wide',
                f.score_provisional ? 'text-violet-600' : 'text-slate-400',
              )}
            >
              {/* "live" = qualcosa si muove ancora; "da conteggiare" = il numero è
                  quello definitivo, manca solo che l'amministratore chiuda. */}
              {f.score_provisional ? 'live' : 'da conteggiare'}
            </span>
          ) : null}
        </div>
      ) : (
        <span className="px-2 text-xs font-semibold uppercase tracking-wide text-slate-400">vs</span>
      )}
      <div className="flex flex-1 items-center gap-2">
        <Crest descriptor={f.away_team.crest} teamName={f.away_team.name} size={24} />
        <span className={awayWin ? 'font-bold text-slate-900' : 'text-slate-600'}>{f.away_team.name}</span>
      </div>
    </div>
  );

  return (
    <div
      className={clsx(
        'rounded-xl border px-3 py-2.5',
        f.is_user_involved ? 'border-slate-300 bg-white' : 'border-slate-100 bg-slate-50',
      )}
    >
      {openable ? (
        <Link to={`/matches/${f.fixture_id}`} className="block transition hover:opacity-80">
          {body}
        </Link>
      ) : (
        <div title="Il tabellino sarà disponibile a partita giocata">{body}</div>
      )}
      {canSetLineup ? (
        <div className="mt-2 flex justify-center">
          <Link
            to={`/squad/formation?competition=${f.competition_id}&matchday=${f.real_matchday}`}
            className="rounded-lg bg-slate-900 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-slate-700"
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
