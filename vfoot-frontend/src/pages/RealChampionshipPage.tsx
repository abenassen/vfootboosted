import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getRealFixtures } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Card, SectionTitle } from '../components/ui';
import type { RealFixtureItem, RealFixturesResponse } from '../types/realChampionship';

// Calendar + results of the league's REAL reference championship (e.g. Serie A):
// a matchday selector, the round's fixtures with live/finished/scheduled state,
// each played match clickable to its vote-relevant pagella.
export default function RealChampionshipPage() {
  const { selectedLeagueId } = useLeagueContext();
  const [data, setData] = useState<RealFixturesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [matchday, setMatchday] = useState<number | null>(null);

  useEffect(() => {
    setMatchday(null);
    if (!selectedLeagueId) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    void getRealFixtures(selectedLeagueId)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [selectedLeagueId]);

  const matchdays = useMemo(
    () => (data?.matchdays ?? []).map((g) => g.matchday).filter((m): m is number => m != null),
    [data],
  );
  const active = matchday ?? data?.current_matchday ?? matchdays[0] ?? null;
  const group = useMemo(
    () => data?.matchdays.find((g) => g.matchday === active) ?? null,
    [data, active],
  );

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega.</div>;
  if (loading) return <div className="text-sm text-slate-500">Caricamento calendario…</div>;
  if (error) return <div className="text-sm text-red-600">Errore: {error}</div>;
  if (!data?.season)
    return <div className="text-sm text-slate-500">Questa lega non ha una stagione di riferimento.</div>;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-center gap-2">
          <SectionTitle>{data.season.competition}</SectionTitle>
          <Badge tone="blue">{data.season.name}</Badge>
        </div>
        <div className="mt-1 text-sm text-slate-600">Calendario e risultati reali · {matchdays.length} giornate</div>
        <div className="mt-3 flex flex-wrap gap-1">
          {matchdays.map((m) => (
            <button
              key={m}
              onClick={() => setMatchday(m)}
              className={
                m === active
                  ? 'rounded-lg bg-slate-900 px-2.5 py-1 text-xs font-semibold text-white'
                  : 'rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-200'
              }
            >
              {m}
            </button>
          ))}
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>{active != null ? `Giornata ${active}` : 'Giornata'}</SectionTitle>
        <div className="mt-2 space-y-2">
          {group?.fixtures.length ? (
            group.fixtures.map((f) => <RealFixtureRow key={f.id} f={f} />)
          ) : (
            <div className="text-sm text-slate-500">Nessuna partita.</div>
          )}
        </div>
      </Card>
    </div>
  );
}

function fmtKickoff(iso: string | null, provisional: boolean): string {
  if (!iso || provisional) return 'Orario da definire';
  const d = new Date(iso);
  return d.toLocaleString('it-IT', {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function RealFixtureRow({ f }: { f: RealFixtureItem }) {
  const played = f.status === 'finished' || f.status === 'live';
  const hs = f.home_goals ?? 0;
  const as = f.away_goals ?? 0;
  const homeWin = played && hs > as;
  const awayWin = played && as > hs;

  const body = (
    <div className="flex items-center gap-3">
      <div className="flex-1 text-right">
        <span className={homeWin ? 'font-bold text-slate-900' : 'text-slate-600'}>{f.home_team}</span>
      </div>
      <div className="flex items-center gap-1 rounded-lg bg-white px-2 py-1 font-mono text-sm font-bold shadow-sm">
        {played ? (
          <>
            <span className={homeWin ? 'text-green-600' : 'text-slate-700'}>{hs}</span>
            <span className="text-slate-300">-</span>
            <span className={awayWin ? 'text-green-600' : 'text-slate-700'}>{as}</span>
          </>
        ) : (
          <span className="text-slate-400">vs</span>
        )}
      </div>
      <div className="flex-1">
        <span className={awayWin ? 'font-bold text-slate-900' : 'text-slate-600'}>{f.away_team}</span>
      </div>
    </div>
  );

  return (
    <div className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-2.5">
      {f.has_detail ? (
        <Link to={`/serie-a/${f.id}`} className="block transition hover:opacity-80">
          {body}
        </Link>
      ) : (
        body
      )}
      <div className="mt-1 flex items-center justify-center gap-2 text-[10px] uppercase tracking-wide text-slate-400">
        {f.status === 'live' ? (
          <span className="inline-flex items-center gap-1 font-bold text-red-600">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-600" />
            In corso
          </span>
        ) : f.status === 'finished' ? (
          <span>Finale{f.has_detail ? ' · voti disponibili' : ''}</span>
        ) : f.status === 'postponed' ? (
          <span className="font-semibold text-amber-600">Rinviata</span>
        ) : f.status === 'cancelled' ? (
          <span className="font-semibold text-rose-600">Annullata</span>
        ) : (
          <span>{fmtKickoff(f.kickoff, f.kickoff_provisional)}</span>
        )}
      </div>
    </div>
  );
}
