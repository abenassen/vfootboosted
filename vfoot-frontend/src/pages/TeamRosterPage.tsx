import { Link, useParams } from 'react-router-dom';
import { Button, Card, SectionTitle } from '../components/ui';
import { useAsync } from '../utils/useAsync';
import { getTeamLineup } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import RosterView from '../components/RosterView';

/** Another participant's roster, in the same structured view as one's own — the
 *  read-only counterpart of the Squad page, reached from the League page. The
 *  chosen XI is withheld by the backend; only the roster is shown. */
export default function TeamRosterPage() {
  const { teamId } = useParams();
  const { selectedLeagueId } = useLeagueContext();
  const { data, loading, error } = useAsync(
    () =>
      selectedLeagueId && teamId
        ? getTeamLineup(selectedLeagueId, null, null, Number(teamId))
        : Promise.reject(new Error('Parametri mancanti')),
    [selectedLeagueId, teamId],
  );

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega.</div>;
  if (loading) return <div className="text-sm text-slate-500">Caricamento rosa…</div>;
  if (error || !data) return <div className="text-sm text-red-600">Errore: {error?.message ?? '…'}</div>;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <SectionTitle>Rosa</SectionTitle>
            <div className="mt-1 text-xl font-black">{data.team.name}</div>
            <div className="text-sm text-slate-500">
              {data.team.manager ? `di ${data.team.manager} · ` : ''}
              {data.roster.length} giocatori
            </div>
          </div>
          <Link to="/league">
            <Button variant="ghost" size="sm">
              ← Lega
            </Button>
          </Link>
        </div>
      </Card>
      <RosterView data={data} />
    </div>
  );
}
