import { useState } from 'react';
import { Button } from '../components/ui';
import { useAsync } from '../utils/useAsync';
import { getTeamLineup } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import RosterView from '../components/RosterView';
import TeamIdentityCard from '../components/TeamIdentityCard';

export default function SquadPage() {
  const { selectedLeagueId } = useLeagueContext();
  const { data, loading, error } = useAsync(
    () => (selectedLeagueId ? getTeamLineup(selectedLeagueId) : Promise.reject(new Error('Nessuna lega selezionata'))),
    [selectedLeagueId],
  );
  const [exporting, setExporting] = useState(false);

  if (!selectedLeagueId) return <div className="text-sm text-ink-faint">Seleziona una lega per vedere la rosa.</div>;
  if (loading) return <div className="text-sm text-ink-faint">Caricamento rosa…</div>;
  if (error || !data) return <div className="text-sm text-bad">Errore: {error?.message ?? '…'}</div>;

  return (
    <div className="space-y-4">
      <TeamIdentityCard
        leagueId={selectedLeagueId}
        initialName={data.team.name}
        subtitle={`${data.roster.length} giocatori in rosa`}
        action={
          <Button
            size="sm"
            variant="secondary"
            disabled={exporting || !data.roster.length}
            onClick={() => {
              setExporting(true);
              // Lazy-load ExcelJS (heavy) only when the user actually exports.
              void import('../utils/rosterXlsx')
                .then((m) => m.downloadRosterXlsx(data))
                .finally(() => setExporting(false));
            }}
          >
            {exporting ? 'Preparo…' : '⬇ Scarica rosa (xlsx)'}
          </Button>
        }
      />
      <RosterView data={data} />
    </div>
  );
}
