import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getLeagueFixtures } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { useCompetitionContext } from '../league/CompetitionContext';
import { Badge, Card, SectionTitle } from '../components/ui';
import type { LeagueFixtureItem } from '../types/league';

// Calendar of the CURRENTLY selected competition (set via the competition switcher):
// a round selector, the round's fixtures, each clickable to the rich detail.
export default function MatchesPage() {
  const { selectedLeagueId } = useLeagueContext();
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
  const activeRound = round ?? rounds[0] ?? null;
  const shown = useMemo(() => fixtures.filter((f) => f.round_no === activeRound), [fixtures, activeRound]);
  const roundLabel = (r: number) => fixtures.find((f) => f.round_no === r)?.round_label ?? `Giornata ${r}`;

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
          <Badge tone={isKnockout ? 'amber' : 'blue'}>{isKnockout ? 'Coppa' : 'Campionato'}</Badge>
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
        <div className="mt-2 space-y-2">
          {shown.length ? (
            shown.map((f) => <FixtureRow key={f.fixture_id} f={f} />)
          ) : (
            <div className="text-sm text-slate-500">Nessuna partita in questa giornata.</div>
          )}
        </div>
      </Card>
    </div>
  );
}

function FixtureRow({ f }: { f: LeagueFixtureItem }) {
  const finished = f.status === 'finished' && f.score;
  const hs = f.score?.home_total ?? 0;
  const as = f.score?.away_total ?? 0;
  const homeWin = !!finished && hs > as;
  const awayWin = !!finished && as > hs;
  // A lineup can only be set for a fixture that has NOT been played yet: on a
  // concluded season every fixture is finished, so the button must disappear.
  const canSetLineup =
    f.is_user_involved && typeof f.real_matchday === 'number' && f.status !== 'finished';
  return (
    <div className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-2.5">
      <Link to={`/matches/${f.fixture_id}`} className="block transition hover:opacity-80">
        <div className="flex items-center gap-3">
          <div className="flex-1 text-right">
            <span className={homeWin ? 'font-bold text-slate-900' : 'text-slate-600'}>{f.home_team.name}</span>
          </div>
          <div className="flex items-center gap-1 rounded-lg bg-white px-2 py-1 font-mono text-sm font-bold shadow-sm">
            {finished ? (
              <>
                <span className={homeWin ? 'text-green-600' : 'text-slate-700'}>{Math.round(hs)}</span>
                <span className="text-slate-300">-</span>
                <span className={awayWin ? 'text-green-600' : 'text-slate-700'}>{Math.round(as)}</span>
              </>
            ) : (
              <span className="text-slate-400">vs</span>
            )}
          </div>
          <div className="flex-1">
            <span className={awayWin ? 'font-bold text-slate-900' : 'text-slate-600'}>{f.away_team.name}</span>
          </div>
        </div>
      </Link>
      <div className="mt-1 flex items-center justify-center gap-3 text-[10px] uppercase tracking-wide text-slate-400">
        <span>
          Giornata {f.round_no}
          {typeof f.real_matchday === 'number' ? ` · Serie A reale ${f.real_matchday}` : ''}
        </span>
        {canSetLineup ? (
          <Link
            to={`/squad/formation?competition=${f.competition_id}&matchday=${f.real_matchday}`}
            className="rounded bg-slate-900 px-2 py-0.5 font-semibold normal-case text-white hover:bg-slate-700"
          >
            Imposta formazione
          </Link>
        ) : null}
      </div>
    </div>
  );
}
