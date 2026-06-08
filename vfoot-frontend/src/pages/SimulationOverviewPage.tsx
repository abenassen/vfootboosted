import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getSimulationOverview } from '../api/simulation';
import { standingsToVM } from '../api/simulationAdapters';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import { StandingsTable } from '../components/league/StandingsTable';
import { DistributionBars, RankedBars } from '../components/charts/Bars';
import { useAsync } from '../utils/useAsync';
import type { SimOverview } from '../types/simulation';

export default function SimulationOverviewPage() {
  const { data, loading, error } = useAsync(() => getSimulationOverview(), []);
  const [selectedTeam, setSelectedTeam] = useState<string | null>(null);

  const standings = useMemo(() => (data ? standingsToVM(data.standings) : []), [data]);
  const team = useMemo(
    () => (data && selectedTeam ? data.teams.find((t) => t.name === selectedTeam) ?? null : null),
    [data, selectedTeam],
  );

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
        <div className="space-y-4 lg:col-span-2">
          <Card className="p-4">
            <SectionTitle>Classifica</SectionTitle>
            <div className="mt-1 text-[11px] text-slate-400">Clicca una squadra per vederne rosa e valori.</div>
            <div className="mt-2">
              <StandingsTable
                rows={standings}
                promoCount={4}
                selectedKey={selectedTeam}
                onRowClick={(row) => setSelectedTeam((cur) => (cur === row.key ? null : row.key))}
              />
            </div>
          </Card>
          {team ? (
            <Card className="p-4">
              <div className="flex items-center justify-between">
                <SectionTitle>{team.name} · giocatori di punta</SectionTitle>
                <span className="text-xs text-slate-500">
                  speso {team.spent} · residuo {team.remaining_budget} · rosa {team.roster_size}
                </span>
              </div>
              <div className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
                {team.top_players.map((p) => (
                  <div key={p.player_id} className="flex items-center justify-between text-sm">
                    <span className="text-slate-700">{p.name}</span>
                    <span className="text-xs text-slate-500">
                      <span className="font-mono">{p.price}</span>{' '}
                      <span className="text-slate-400">val {p.value.toFixed(0)}</span>
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          ) : null}
        </div>
        <div className="space-y-4">
          <Card className="p-4">
            <SectionTitle>Esiti</SectionTitle>
            <div className="mt-3">
              <DistributionBars
                items={[
                  { label: 'Vittorie casa', value: data.distributions.results.home_wins, colorClass: 'bg-green-500' },
                  { label: 'Pareggi', value: data.distributions.results.draws, colorClass: 'bg-slate-400' },
                  { label: 'Vittorie trasferta', value: data.distributions.results.away_wins, colorClass: 'bg-sky-500' },
                ]}
              />
            </div>
            {data.distributions.score_range ? (
              <div className="mt-4 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
                Punteggio Vfoot per squadra — min <b>{data.distributions.score_range.min}</b> · media{' '}
                <b>{data.distributions.score_range.avg}</b> · max <b>{data.distributions.score_range.max}</b>
              </div>
            ) : null}
          </Card>
          <Card className="p-4">
            <SectionTitle>Risultati più frequenti</SectionTitle>
            <div className="mt-3">
              <RankedBars
                items={data.distributions.top_scorelines.map((l) => ({ label: l.scoreline, value: l.count }))}
              />
            </div>
          </Card>
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
