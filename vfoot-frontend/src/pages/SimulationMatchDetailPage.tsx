import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getSimulationFixtureDetail } from '../api/simulation';
import {
  fixtureToHeaderVM,
  lineupToVM,
  zonesToCells,
  zonesToDuelVM,
} from '../api/simulationAdapters';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import { MatchScoreHeader } from '../components/match/MatchScoreHeader';
import { ZonePitchGrid } from '../components/match/ZonePitchGrid';
import { ZoneDuelList } from '../components/match/ZoneDuelList';
import { LineupPanel } from '../components/match/LineupPanel';
import { useAsync } from '../utils/useAsync';

export default function SimulationMatchDetailPage() {
  const { fixtureId } = useParams();
  const id = Number(fixtureId);
  const { data, loading, error } = useAsync(() => getSimulationFixtureDetail(id), [fixtureId]);
  const [selectedZone, setSelectedZone] = useState<string | null>(null);

  const vm = useMemo(() => {
    if (!data) return null;
    return {
      header: fixtureToHeaderVM(data),
      cells: zonesToCells(data.vector_report.top_zones),
      duels: zonesToDuelVM(data.vector_report.top_zones, data.home_team, data.away_team),
      home: lineupToVM(data.home_lineup, data.home_team, 'home'),
      away: lineupToVM(data.away_lineup, data.away_team, 'away'),
    };
  }, [data]);

  if (loading) return <div className="text-sm text-slate-500">Caricamento partita…</div>;
  if (error || !data || !vm) {
    return (
      <Card className="p-4 text-sm text-red-600">
        Errore nel caricamento della partita: {error?.message ?? 'sconosciuto'}
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <MatchScoreHeader
          header={vm.header}
          eyebrow={
            <SectionTitle>
              Giornata {data.fantasy_round} · Serie A reale {data.real_matchday}
            </SectionTitle>
          }
          action={
            <Link to="/simulation/matches">
              <Button variant="ghost" size="sm">
                ← Partite
              </Button>
            </Link>
          }
          footer={<Badge tone="slate">margine zona-vettore {data.vector_report.total_margin.toFixed(3)}</Badge>}
        />
      </Card>

      <Card className="p-4">
        <SectionTitle>Duello a zone (decisive)</SectionTitle>
        <div className="mt-3 grid gap-4 md:grid-cols-[180px_1fr]">
          <ZonePitchGrid cells={vm.cells} selectedZone={selectedZone} onSelectZone={setSelectedZone} />
          <ZoneDuelList zones={vm.duels} selectedZone={selectedZone} onSelect={setSelectedZone} />
        </div>
        <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-slate-500">
          <span className="flex items-center gap-1">
            <span className="h-3 w-3 rounded bg-green-500" /> {data.home_team} (casa)
          </span>
          <span className="flex items-center gap-1">
            <span className="h-3 w-3 rounded bg-sky-500" /> {data.away_team} (trasferta)
          </span>
          <span className="flex items-center gap-1">
            <span className="h-3 w-3 rounded bg-slate-200" /> zona non decisiva
          </span>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <LineupPanel lineup={vm.home} />
        </Card>
        <Card className="p-4">
          <LineupPanel lineup={vm.away} />
        </Card>
      </div>
    </div>
  );
}
