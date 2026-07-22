import { useParams } from 'react-router-dom';
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
    return <Card className="p-4 text-sm text-red-600">Errore nel caricamento della partita: {error?.message ?? 'sconosciuto'}</Card>;
  }
  // Classic leagues carry mode:'classic' in the payload -> fantavoto detail (no zone
  // duel). Aura leagues fall through to the zone-duel MatchDetail.
  if ('mode' in data && data.mode === 'classic') {
    return <ClassicMatchDetail fixture={data as ClassicFixtureDetail} backTo="/matches" />;
  }
  return <MatchDetail fixture={data as SimFixtureDetail} backTo="/matches" />;
}
