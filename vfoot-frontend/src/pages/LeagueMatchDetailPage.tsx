import { useParams } from 'react-router-dom';
import { getFixtureDetail } from '../api';
import { Card } from '../components/ui';
import { MatchDetail } from '../components/match/MatchDetail';
import { useAsync } from '../utils/useAsync';

export default function LeagueMatchDetailPage() {
  const { matchId } = useParams();
  const { data, loading, error } = useAsync(() => getFixtureDetail(matchId ?? ''), [matchId]);

  if (loading) return <div className="text-sm text-slate-500">Caricamento partita…</div>;
  if (error || !data) {
    return <Card className="p-4 text-sm text-red-600">Errore nel caricamento della partita: {error?.message ?? 'sconosciuto'}</Card>;
  }
  return <MatchDetail fixture={data} backTo="/matches" />;
}
