import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getSimulationFixtureDetail } from '../api/simulation';
import {
  buildZoneInspector,
  fixtureToHeaderVM,
  lineupToSubReport,
  playerInfluenceVMs,
  scoreBuildVM,
  zonesToCells,
} from '../api/simulationAdapters';
import { Button, Card, SectionTitle } from '../components/ui';
import { MatchScoreHeader } from '../components/match/MatchScoreHeader';
import { ZonePitchGrid } from '../components/match/ZonePitchGrid';
import { ZoneInspector } from '../components/match/ZoneInspector';
import { PlayerInfluence } from '../components/match/PlayerInfluence';
import { ScoreBuildExplainer } from '../components/match/ScoreBuildExplainer';
import { SubstitutionReport } from '../components/match/LineupPanel';
import { useAsync } from '../utils/useAsync';

export default function SimulationMatchDetailPage() {
  const { fixtureId } = useParams();
  const id = Number(fixtureId);
  const { data, loading, error } = useAsync(() => getSimulationFixtureDetail(id), [fixtureId]);
  const [selectedZone, setSelectedZone] = useState<string | null>(null);

  const vm = useMemo(() => {
    if (!data) return null;
    const vr = data.vector_report;
    const cells = zonesToCells(vr.zones);
    const decisive = [...vr.zones]
      .filter((z) => z.features.length > 0)
      .sort((a, b) => Math.abs(b.margin) - Math.abs(a.margin))[0];
    return {
      header: fixtureToHeaderVM(data),
      scoreBuild: scoreBuildVM(data),
      cells,
      zones: vr.zones,
      defaultZone: decisive?.zone_key ?? null,
      homeInfluence: playerInfluenceVMs(vr.home_player_totals),
      awayInfluence: playerInfluenceVMs(vr.away_player_totals),
      homeSub: lineupToSubReport(data.home_lineup),
      awaySub: lineupToSubReport(data.away_lineup),
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

  const activeZoneKey = selectedZone ?? vm.defaultZone;
  const activeZone = vm.zones.find((z) => z.zone_key === activeZoneKey) ?? null;
  const inspector = activeZone
    ? buildZoneInspector(activeZone, data.vector_report.home_player_totals, data.vector_report.away_player_totals, data.home_team, data.away_team)
    : null;

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
        />
      </Card>

      <Card className="p-4">
        <SectionTitle>Come nasce il punteggio</SectionTitle>
        <div className="mt-2">
          <ScoreBuildExplainer vm={vm.scoreBuild} />
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>Mappa del campo · clicca una zona</SectionTitle>
        <div className="mt-3 grid gap-4 md:grid-cols-[minmax(240px,300px)_1fr]">
          <div>
            <ZonePitchGrid cells={vm.cells} selectedZone={activeZoneKey} onSelectZone={setSelectedZone} />
            <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-slate-500">
              <span className="flex items-center gap-1">
                <span className="h-3 w-3 rounded bg-green-500" /> {data.home_team}
              </span>
              <span className="flex items-center gap-1">
                <span className="h-3 w-3 rounded bg-sky-500" /> {data.away_team}
              </span>
            </div>
          </div>
          {inspector ? <ZoneInspector zone={inspector} /> : null}
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <PlayerInfluence
            title={data.home_team}
            side="home"
            players={vm.homeInfluence}
            selectedZone={activeZoneKey}
            onSelectZone={setSelectedZone}
          />
        </Card>
        <Card className="p-4">
          <PlayerInfluence
            title={data.away_team}
            side="away"
            players={vm.awayInfluence}
            selectedZone={activeZoneKey}
            onSelectZone={setSelectedZone}
          />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <SectionTitle>{data.home_team} · sostituzioni</SectionTitle>
          <div className="mt-1">
            <SubstitutionReport report={vm.homeSub} />
          </div>
        </Card>
        <Card className="p-4">
          <SectionTitle>{data.away_team} · sostituzioni</SectionTitle>
          <div className="mt-1">
            <SubstitutionReport report={vm.awaySub} />
          </div>
        </Card>
      </div>
    </div>
  );
}
