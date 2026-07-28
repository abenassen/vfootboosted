import { useState } from 'react';
import { Button, Card, SectionTitle } from '../components/ui';
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
  const [exporting, setExporting] = useState(false);

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega per vedere la rosa.</div>;
  if (loading) return <div className="text-sm text-slate-500">Caricamento rosa…</div>;
  if (error || !data) return <div className="text-sm text-red-600">Errore: {error?.message ?? '…'}</div>;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <SectionTitle>Squadra</SectionTitle>
            <div className="mt-1 text-xl font-black">{data.team.name}</div>
            <div className="text-sm text-slate-500">{data.roster.length} giocatori in rosa</div>
          </div>
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
        </div>
      </Card>
      <RosterView data={data} />
    </div>
  );
}
