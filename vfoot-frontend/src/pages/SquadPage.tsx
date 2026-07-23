import { Card, SectionTitle } from '../components/ui';
import { useAsync } from '../utils/useAsync';
import { getTeamLineup } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import RosterView from '../components/RosterView';

export default function SquadPage() {
  const { selectedLeagueId } = useLeagueContext();
  const { data, loading, error } = useAsync(
    () => (selectedLeagueId ? getTeamLineup(selectedLeagueId) : Promise.reject(new Error('Nessuna lega selezionata'))),
    [selectedLeagueId],
  );

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega per vedere la rosa.</div>;
  if (loading) return <div className="text-sm text-slate-500">Caricamento rosa…</div>;
  if (error || !data) return <div className="text-sm text-red-600">Errore: {error?.message ?? '…'}</div>;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <SectionTitle>Squadra</SectionTitle>
        <div className="mt-1 text-xl font-black">{data.team.name}</div>
        <div className="text-sm text-slate-500">{data.roster.length} giocatori in rosa</div>
      </Card>
      <RosterView data={data} />
    </div>
  );
}
