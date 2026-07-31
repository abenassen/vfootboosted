import { Link, useParams } from 'react-router-dom';
import { getFixtureDetail } from '../api';
import { Card } from '../components/ui';
import { MatchDetail } from '../components/match/MatchDetail';
import { ClassicMatchDetail } from '../components/match/ClassicMatchDetail';
import { useAsync } from '../utils/useAsync';
import type { ClassicFixtureDetail } from '../types/classic';
import type { SimFixtureDetail } from '../types/simulation';

export default function LeagueMatchDetailPage() {
  const { matchId } = useParams();
  const { data, loading, error } = useAsync(() => getFixtureDetail(matchId ?? ''), [matchId]);

  if (loading) return <div className="text-sm text-slate-500">Caricamento partita…</div>;
  if (error || !data) {
    // A fixture that has not been played has no rich detail, and the API says so
    // with a 404: that is a normal state, not a failure, and showing it in red
    // made a match simply not played yet look like a broken page. The calendar no
    // longer links these, so getting here means a bookmark or a typed URL.
    const notPlayedYet = /no rich detail/i.test(error?.message ?? '');
    if (notPlayedYet) {
      return (
        <Card className="p-6 text-center">
          <div className="text-3xl">📋</div>
          <div className="mt-2 font-bold">Partita non ancora giocata</div>
          <p className="mx-auto mt-1 max-w-sm text-sm text-slate-600">
            Il tabellino compare quando la giornata viene conclusa: prima non ci sono
            né voti né formazioni da mostrare.
          </p>
          <Link
            to="/matches"
            className="mt-4 inline-flex rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
          >
            ← Torna al calendario
          </Link>
        </Card>
      );
    }
    return <Card className="p-4 text-sm text-red-600">Errore nel caricamento della partita: {error?.message ?? 'sconosciuto'}</Card>;
  }
  // Classic leagues carry mode:'classic' in the payload -> fantavoto detail (no zone
  // duel). Aura leagues fall through to the zone-duel MatchDetail.
  if ('mode' in data && data.mode === 'classic') {
    return <ClassicMatchDetail fixture={data as ClassicFixtureDetail} backTo="/matches" />;
  }
  return <MatchDetail fixture={data as SimFixtureDetail} backTo="/matches" />;
}
