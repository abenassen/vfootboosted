import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getLeagueFixtures } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type { LeagueFixtureItem } from '../types/league';

export default function MatchesPage() {
  const { selectedLeagueId } = useLeagueContext();
  const [fixtures, setFixtures] = useState<LeagueFixtureItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedLeagueId) return;
    setLoading(true);
    setError(null);
    void getLeagueFixtures(selectedLeagueId)
      .then(setFixtures)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [selectedLeagueId]);

  const grouped = useMemo(() => {
    const map = new Map<string, LeagueFixtureItem[]>();
    for (const f of fixtures) {
      const key = `${f.competition_id}:${f.competition_name}`;
      const curr = map.get(key) ?? [];
      curr.push(f);
      map.set(key, curr);
    }
    return [...map.entries()].map(([k, v]) => ({ key: k, competitionName: v[0].competition_name, fixtures: v }));
  }, [fixtures]);

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega per vedere le partite.</div>;
  if (loading) return <div className="text-sm text-slate-500">Caricamento partite…</div>;
  if (error) return <div className="text-sm text-red-600">Errore: {error}</div>;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <SectionTitle>Partite</SectionTitle>
        <div className="mt-2 text-sm text-slate-600">Partite recenti e prossime per tutte le competizioni della lega selezionata.</div>
      </Card>

      {grouped.map((g) => {
        const next = g.fixtures.filter((f) => f.status !== 'finished');
        const past = g.fixtures.filter((f) => f.status === 'finished');
        return (
          <Card key={g.key} className="p-4">
            <SectionTitle>{g.competitionName}</SectionTitle>
            <div className="mt-2 grid gap-4 md:grid-cols-2">
              <div>
                <div className="text-xs font-semibold text-slate-500">Prossime</div>
                <div className="mt-2 space-y-2">
                  {next.length ? next.map((f) => <FixtureRow key={f.fixture_id} f={f} />) : <div className="text-xs text-slate-500">Nessuna.</div>}
                </div>
              </div>
              <div>
                <div className="text-xs font-semibold text-slate-500">Recenti</div>
                <div className="mt-2 space-y-2">
                  {past.length ? past.map((f) => <FixtureRow key={f.fixture_id} f={f} />) : <div className="text-xs text-slate-500">Nessuna.</div>}
                </div>
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function FixtureRow({ f }: { f: LeagueFixtureItem }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-2 text-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="font-semibold">
          {f.home_team.name} <span className="text-slate-400">vs</span> {f.away_team.name}
          <div className="mt-1 text-xs text-slate-500">
            {f.round_label ?? `Round ${f.round_no}`} ·
            {typeof f.real_matchday === 'number' ? ` MD ${f.real_matchday} · ` : ' '}
            {f.kickoff ? new Date(f.kickoff).toLocaleString() : 'Data da definire'}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Badge tone={f.status === 'finished' ? 'green' : f.status === 'live' ? 'amber' : 'slate'}>{f.status}</Badge>
          <Link to={`/matches/${f.fixture_id}`}>
            <Button size="sm" variant="secondary">Dettagli</Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
