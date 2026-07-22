import { useParams } from 'react-router-dom';
import { getRealMatchDetail } from '../api';
import { Card } from '../components/ui';
import { ClassicMatchDetail } from '../components/match/ClassicMatchDetail';
import { useLeagueContext } from '../league/LeagueContext';
import { useAsync } from '../utils/useAsync';

// Vote-relevant detail of a REAL Serie A match: the per-player pagella
// (voto puro + bonus/malus = fantavoto) for both squads, rendered with the same
// ClassicMatchDetail component used by classic fantasy fixtures. (Aura zone
// breakdown enrichment is a planned follow-up.)
export default function RealMatchDetailPage() {
  const { matchId } = useParams();
  const { selectedLeagueId } = useLeagueContext();
  const { data, loading, error } = useAsync(
    () =>
      selectedLeagueId && matchId
        ? getRealMatchDetail(selectedLeagueId, matchId)
        : Promise.reject(new Error('Lega o partita non selezionata')),
    [selectedLeagueId, matchId],
  );

  if (loading) return <div className="text-sm text-slate-500">Caricamento partita…</div>;
  if (error || !data) {
    return (
      <Card className="p-4 text-sm text-red-600">
        Errore nel caricamento della partita: {error?.message ?? 'sconosciuto'}
      </Card>
    );
  }
  return <ClassicMatchDetail fixture={data} backTo="/serie-a" backLabel="← Serie A" />;
}
