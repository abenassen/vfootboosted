import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getSimulationFixtures } from '../api/simulation';
import { Button, Card, SectionTitle } from '../components/ui';
import { useAsync } from '../utils/useAsync';
import type { SimFixtureSummary } from '../types/simulation';

export default function SimulationMatchesPage() {
  const { data, loading, error } = useAsync(() => getSimulationFixtures(), []);
  const [round, setRound] = useState<number | null>(null);

  const rounds = useMemo(() => {
    if (!data) return [];
    return [...new Set(data.map((f) => f.fantasy_round))].sort((a, b) => a - b);
  }, [data]);

  const activeRound = round ?? rounds[0] ?? null;

  const fixtures = useMemo(() => {
    if (!data || activeRound == null) return [];
    return data.filter((f) => f.fantasy_round === activeRound);
  }, [data, activeRound]);

  if (loading) return <div className="text-sm text-slate-500">Caricamento partite…</div>;
  if (error || !data) {
    return (
      <Card className="p-4 text-sm text-red-600">
        Errore nel caricamento delle partite simulate: {error?.message ?? 'sconosciuto'}
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <SectionTitle>Partite simulate</SectionTitle>
            <div className="mt-1 text-sm text-slate-600">
              {data.length} partite · {rounds.length} giornate
            </div>
          </div>
          <Link to="/simulation">
            <Button variant="ghost" size="sm">
              ← Panoramica
            </Button>
          </Link>
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
              {r}
            </button>
          ))}
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>Giornata {activeRound}</SectionTitle>
        <div className="mt-2 space-y-2">
          {fixtures.map((f) => (
            <FixtureRow key={f.fixture_id} f={f} />
          ))}
        </div>
      </Card>
    </div>
  );
}

function FixtureRow({ f }: { f: SimFixtureSummary }) {
  const homeWin = f.result === 'home';
  const awayWin = f.result === 'away';
  return (
    <Link
      to={`/simulation/matches/${f.fixture_id}`}
      className="block rounded-xl border border-slate-100 bg-slate-50 px-3 py-2.5 transition hover:border-slate-300 hover:bg-white"
    >
      <div className="flex items-center gap-3">
        <div className="flex-1 text-right">
          <span className={homeWin ? 'font-bold text-slate-900' : 'text-slate-600'}>{f.home_team}</span>
          <span className="ml-2 text-[11px] text-slate-400">{f.home_score.toFixed(1)}</span>
        </div>
        <div className="flex items-center gap-1 rounded-lg bg-white px-2 py-1 font-mono text-sm font-bold shadow-sm">
          <span className={homeWin ? 'text-green-600' : 'text-slate-700'}>{f.home_goals}</span>
          <span className="text-slate-300">-</span>
          <span className={awayWin ? 'text-green-600' : 'text-slate-700'}>{f.away_goals}</span>
        </div>
        <div className="flex-1">
          <span className="mr-2 text-[11px] text-slate-400">{f.away_score.toFixed(1)}</span>
          <span className={awayWin ? 'font-bold text-slate-900' : 'text-slate-600'}>{f.away_team}</span>
        </div>
      </div>
      <div className="mt-1 text-center text-[10px] uppercase tracking-wide text-slate-400">
        Serie A · giornata reale {f.real_matchday}
      </div>
    </Link>
  );
}
