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
  const groupedByRound = useMemo(() => {
    const buckets = new Map<
      string,
      { roundNo: number; roundLabel: string; realMatchday: number | null; fixtures: LeagueFixtureItem[] }
    >();
    for (const f of fixtures) {
      const roundLabel = f.round_label ?? `Round ${f.round_no}`;
      const realMd = typeof f.real_matchday === 'number' ? f.real_matchday : null;
      const key = `${roundLabel}|${f.round_no}|${realMd ?? 'na'}`;
      if (!buckets.has(key)) {
        buckets.set(key, {
          roundNo: f.round_no,
          roundLabel,
          realMatchday: realMd,
          fixtures: [],
        });
      }
      buckets.get(key)!.fixtures.push(f);
    }
    return [...buckets.values()].sort((a, b) => {
      const am = a.realMatchday ?? 9999;
      const bm = b.realMatchday ?? 9999;
      if (am !== bm) return am - bm;
      return a.roundNo - b.roundNo;
    });
  }, [fixtures]);

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
          Fixture totali: {fixtures.length} · Round/Stage: {groupedByRound.length}
        </div>
        <Link to="/league" className="mt-3 inline-flex rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white">
          Torna alla Lega
        </Link>
      </Card>

      <Card className="p-4">
        <SectionTitle>Calendario per Round / Matchday</SectionTitle>
        <div className="mt-3 space-y-3">
          {groupedByRound.length ? (
            groupedByRound.map((g) => (
              <div key={`${g.roundLabel}-${g.roundNo}-${g.realMatchday ?? 'na'}`} className="rounded-xl border border-slate-100 bg-slate-50 p-3">
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-semibold">{g.roundLabel}</span>
                  <Badge tone="slate">Round {g.roundNo}</Badge>
                  {g.realMatchday !== null ? <Badge tone="amber">Real MD {g.realMatchday}</Badge> : <Badge tone="red">Non schedulato</Badge>}
                </div>
                <div className="mt-2 space-y-2">
                  {g.fixtures.map((f) => <FixtureRow key={f.fixture_id} f={f} />)}
                </div>
              </div>
            ))
          ) : (
            <div className="text-sm text-slate-500">Nessuna partita disponibile.</div>
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
            Round {f.round_no} · Leg {f.leg_no}
            {typeof f.real_matchday === 'number' ? ` · Real MD ${f.real_matchday}` : ''}
            {f.kickoff ? ` · ${new Date(f.kickoff).toLocaleString()}` : ''}
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
