import { Link } from 'react-router-dom';
import { getSimulationOverview } from '../api/simulation';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import { useAsync } from '../utils/useAsync';
import type { SimOverview, SimStanding } from '../types/simulation';

export default function SimulationOverviewPage() {
  const { data, loading, error } = useAsync(() => getSimulationOverview(), []);

  if (loading) return <div className="text-sm text-slate-500">Caricamento simulazione…</div>;
  if (error || !data) {
    return (
      <Card className="p-4">
        <SectionTitle>Simulazione non disponibile</SectionTitle>
        <div className="mt-2 text-sm text-slate-600">{error?.message ?? 'Artefatto non trovato.'}</div>
        <div className="mt-2 text-xs text-slate-500">
          Rigenera l'artefatto con{' '}
          <code className="rounded bg-slate-100 px-1 py-0.5">python manage.py simulate_historical_vfoot_league</code>{' '}
          e assicurati che il backend sia in esecuzione.
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <HeaderCard data={data} />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <StandingsCard standings={data.standings} />
        </div>
        <div className="space-y-4">
          <ResultsCard data={data} />
          <ScorelinesCard data={data} />
        </div>
      </div>
      {data.notes.length ? (
        <Card className="p-4">
          <SectionTitle>Note</SectionTitle>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-600">
            {data.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}

function HeaderCard({ data }: { data: SimOverview }) {
  const c = data.config;
  const stats: { label: string; value: string }[] = [
    { label: 'Manager', value: String(c.teams) },
    { label: 'Giornate', value: String(c.matchdays) },
    { label: 'Partite', value: String(data.distributions.total_fixtures) },
    { label: 'Rosa', value: `${c.squad_size} (${c.starters}+${c.bench_size})` },
    { label: 'Budget', value: String(c.budget) },
    { label: 'Pool giocatori', value: String(data.player_pool_size) },
  ];
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <SectionTitle>Lega simulata · Serie A storica (StatsBomb)</SectionTitle>
          <h1 className="mt-1 text-xl font-black text-slate-900">Dry-run storico Vfoot</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <Badge tone="slate">scoring: {c.scoring_mode}</Badge>
            {c.temporal_substitutions ? <Badge tone="green">sostituzioni temporali</Badge> : null}
            <span className="text-slate-400">{data.version}</span>
          </div>
        </div>
        <Link to="/simulation/matches">
          <Button variant="primary" size="sm">
            Sfoglia le partite →
          </Button>
        </Link>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-6">
        {stats.map((s) => (
          <div key={s.label} className="rounded-xl bg-slate-50 px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-slate-500">{s.label}</div>
            <div className="text-lg font-bold text-slate-900">{s.value}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function StandingsCard({ standings }: { standings: SimStanding[] }) {
  return (
    <Card className="p-4">
      <SectionTitle>Classifica</SectionTitle>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
              <th className="py-2 pr-2">#</th>
              <th className="pr-2">Squadra</th>
              <th className="px-1 text-center">G</th>
              <th className="px-1 text-center">V</th>
              <th className="px-1 text-center">N</th>
              <th className="px-1 text-center">P</th>
              <th className="px-1 text-center">GF</th>
              <th className="px-1 text-center">GS</th>
              <th className="px-1 text-center">DR</th>
              <th className="px-1 text-center">Media</th>
              <th className="px-1 text-center font-bold">Pt</th>
            </tr>
          </thead>
          <tbody>
            {standings.map((s) => (
              <tr key={s.team} className="border-t border-slate-100">
                <td className="py-2 pr-2">
                  <span
                    className={
                      s.rank <= 4
                        ? 'inline-flex h-6 w-6 items-center justify-center rounded-full bg-green-100 text-xs font-bold text-green-800'
                        : 'inline-flex h-6 w-6 items-center justify-center rounded-full bg-slate-100 text-xs font-bold text-slate-600'
                    }
                  >
                    {s.rank}
                  </span>
                </td>
                <td className="pr-2 font-semibold text-slate-900">{s.team}</td>
                <td className="px-1 text-center text-slate-600">{s.played}</td>
                <td className="px-1 text-center text-slate-600">{s.wins}</td>
                <td className="px-1 text-center text-slate-600">{s.draws}</td>
                <td className="px-1 text-center text-slate-600">{s.losses}</td>
                <td className="px-1 text-center text-slate-600">{s.goals_for}</td>
                <td className="px-1 text-center text-slate-600">{s.goals_against}</td>
                <td className="px-1 text-center text-slate-600">
                  {s.goal_diff > 0 ? `+${s.goal_diff}` : s.goal_diff}
                </td>
                <td className="px-1 text-center text-slate-500">{s.avg_score_for.toFixed(1)}</td>
                <td className="px-1 text-center font-bold text-slate-900">{s.points}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ResultsCard({ data }: { data: SimOverview }) {
  const r = data.distributions.results;
  const total = r.home_wins + r.draws + r.away_wins || 1;
  const bars: { label: string; value: number; cls: string }[] = [
    { label: 'Vittorie casa', value: r.home_wins, cls: 'bg-green-500' },
    { label: 'Pareggi', value: r.draws, cls: 'bg-slate-400' },
    { label: 'Vittorie trasferta', value: r.away_wins, cls: 'bg-sky-500' },
  ];
  const range = data.distributions.score_range;
  return (
    <Card className="p-4">
      <SectionTitle>Esiti</SectionTitle>
      <div className="mt-3 space-y-3">
        {bars.map((b) => (
          <div key={b.label}>
            <div className="flex items-center justify-between text-xs text-slate-600">
              <span>{b.label}</span>
              <span className="font-semibold">
                {b.value} · {Math.round((b.value / total) * 100)}%
              </span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full ${b.cls}`} style={{ width: `${(b.value / total) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
      {range ? (
        <div className="mt-4 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
          Punteggio Vfoot per squadra — min <b>{range.min}</b> · media <b>{range.avg}</b> · max <b>{range.max}</b>
        </div>
      ) : null}
    </Card>
  );
}

function ScorelinesCard({ data }: { data: SimOverview }) {
  const lines = data.distributions.top_scorelines;
  const max = Math.max(1, ...lines.map((l) => l.count));
  return (
    <Card className="p-4">
      <SectionTitle>Risultati più frequenti</SectionTitle>
      <div className="mt-3 space-y-2">
        {lines.map((l) => (
          <div key={l.scoreline} className="flex items-center gap-2 text-xs">
            <span className="w-10 font-mono font-semibold text-slate-700">{l.scoreline}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full bg-indigo-400" style={{ width: `${(l.count / max) * 100}%` }} />
            </div>
            <span className="w-8 text-right text-slate-500">{l.count}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}
