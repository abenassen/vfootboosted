import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getLeagueFixtures } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type { LeagueFixtureItem } from '../types/league';

export default function CompetitionPage() {
  const { competitionId } = useParams();
  const { selectedLeagueId } = useLeagueContext();
  const [fixtures, setFixtures] = useState<LeagueFixtureItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedLeagueId || !competitionId) return;
    setLoading(true);
    setError(null);
    void getLeagueFixtures(selectedLeagueId, Number(competitionId))
      .then(setFixtures)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [competitionId, selectedLeagueId]);

  const title = useMemo(() => fixtures[0]?.competition_name ?? `Competition ${competitionId ?? ''}`, [fixtures, competitionId]);
  const upcoming = fixtures.filter((f) => f.status !== 'finished');
  const past = fixtures.filter((f) => f.status === 'finished');

  if (!selectedLeagueId) {
    return (
      <Card className="p-4">
        <SectionTitle>Competition</SectionTitle>
        <div className="mt-2 text-sm text-slate-600">Seleziona prima una lega.</div>
      </Card>
    );
  }

  if (loading) return <div className="text-sm text-slate-500">Caricamento calendario competizione…</div>;
  if (error) return <div className="text-sm text-red-600">Errore: {error}</div>;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <SectionTitle>Competition</SectionTitle>
        <div className="mt-2 text-2xl font-black">{title}</div>
        <div className="mt-2 text-sm text-slate-600">
          Fixture totali: {fixtures.length} · Future/Live: {upcoming.length} · Concluse: {past.length}
        </div>
        <Link to="/league" className="mt-3 inline-flex rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white">
          Torna alla Lega
        </Link>
      </Card>

      <Card className="p-4">
        <SectionTitle>Prossime Partite</SectionTitle>
        <div className="mt-3 space-y-2">
          {upcoming.length ? (
            upcoming.map((f) => <FixtureRow key={f.fixture_id} f={f} />)
          ) : (
            <div className="text-sm text-slate-500">Nessuna partita futura.</div>
          )}
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>Partite Recenti</SectionTitle>
        <div className="mt-3 space-y-2">
          {past.length ? (
            past.map((f) => <FixtureRow key={f.fixture_id} f={f} />)
          ) : (
            <div className="text-sm text-slate-500">Nessuna partita conclusa.</div>
          )}
        </div>
      </Card>
    </div>
  );
}

function FixtureRow({ f }: { f: LeagueFixtureItem }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="font-semibold">
          {f.home_team.name} <span className="text-slate-400">vs</span> {f.away_team.name}
          <div className="mt-1 text-xs text-slate-500">
            Round {f.round_no} · Leg {f.leg_no} {f.kickoff ? `· ${new Date(f.kickoff).toLocaleString()}` : ''}
          </div>
          {f.score ? (
            <div className="mt-1 text-sm font-semibold">
              {f.score.home_total.toFixed(1)} - {f.score.away_total.toFixed(1)}
            </div>
          ) : null}
        </div>
        <div className="flex flex-col items-end gap-1">
          <Badge tone={f.status === 'finished' ? 'green' : f.status === 'live' ? 'amber' : 'slate'}>
            {f.status}
          </Badge>
          <Link to={`/matches/${f.fixture_id}`}>
            <Button size="sm" variant="secondary">Dettagli</Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
