import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  buildZoneInspector,
  fixtureToHeaderVM,
  lineupBoardVMs,
  scoreBuildVM,
  zonesToCells,
} from '../../api/simulationAdapters';
import { Button, Card, SectionTitle } from '../ui';
import { MatchScoreHeader } from './MatchScoreHeader';
import { MatchManagers } from './MatchManagers';
import { ZonePitchGrid } from './ZonePitchGrid';
import { ZoneInspector } from './ZoneInspector';
import { ScoreBuildExplainer } from './ScoreBuildExplainer';
import { LineupColumn } from './LineupBoard';
import type { SimFixtureDetail } from '../../types/simulation';

// The rich match-detail view, fed by a fixture-detail object (same shape from
// the simulation API and the real-league fixture endpoint). Pure presentation;
// the host page handles fetching/loading.
export function MatchDetail({
  fixture,
  backTo,
  backLabel = '← Partite',
}: {
  fixture: SimFixtureDetail;
  backTo: string;
  backLabel?: string;
}) {
  const data = fixture;
  const [selectedZone, setSelectedZone] = useState<string | null>(null);
  const [selectedPlayer, setSelectedPlayer] = useState<string | number | null>(null);

  const vm = useMemo(() => {
    const vr = data.vector_report;
    const decisive = [...vr.zones]
      .filter((z) => z.features.length > 0)
      .sort((a, b) => Math.abs(b.margin) - Math.abs(a.margin))[0];
    return {
      header: fixtureToHeaderVM(data),
      scoreBuild: scoreBuildVM(data),
      cells: zonesToCells(vr.zones),
      zones: vr.zones,
      maxMargin: Math.max(0.0001, ...vr.zones.map((z) => Math.abs(z.margin))),
      defaultZone: decisive?.zone_key ?? null,
      homeBoard: lineupBoardVMs(data.home_lineup, vr.home_player_totals),
      awayBoard: lineupBoardVMs(data.away_lineup, vr.away_player_totals, true),
    };
  }, [data]);

  const highlightZones = useMemo(() => {
    if (selectedPlayer == null) return null;
    return [...vm.homeBoard, ...vm.awayBoard].find((x) => x.id === selectedPlayer)?.zones ?? null;
  }, [vm, selectedPlayer]);

  const activeZoneKey = selectedZone ?? vm.defaultZone;
  const activeZone = vm.zones.find((z) => z.zone_key === activeZoneKey) ?? null;
  const inspector = activeZone
    ? buildZoneInspector(activeZone, data.home_team, data.away_team, vm.maxMargin)
    : null;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <MatchScoreHeader
          header={vm.header}
          eyebrow={
            <SectionTitle>
              Turno {data.fantasy_round} · giornata {data.real_matchday}
            </SectionTitle>
          }
          action={
            <Link to={backTo}>
              <Button variant="ghost" size="sm">
                {backLabel}
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
        <div className="flex items-center justify-between">
          <SectionTitle>Mappa del campo</SectionTitle>
          {selectedPlayer != null ? (
            <button
              onClick={() => setSelectedPlayer(null)}
              className="text-[11px] font-semibold text-ink-faint hover:text-ink-soft"
            >
              ✕ deseleziona giocatore
            </button>
          ) : (
            <span className="text-[11px] text-ink-faint">clicca una zona, o un giocatore in basso</span>
          )}
        </div>
        <div className="mt-3 grid gap-4 md:grid-cols-[minmax(240px,300px)_1fr]">
          <div>
            <ZonePitchGrid
              cells={vm.cells}
              selectedZone={activeZoneKey}
              onSelectZone={(z) => setSelectedZone(z)}
              highlightZones={highlightZones}
            />
            <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-ink-faint">
              <span className="flex items-center gap-1">
                <span className="h-3 w-3 rounded bg-bad" /> {data.home_team}
              </span>
              <span className="flex items-center gap-1">
                <span className="h-3 w-3 rounded bg-blue-600" /> {data.away_team}
              </span>
              {highlightZones ? (
                <span className="flex items-center gap-1">
                  <span className="h-3 w-3 rounded ring-2 ring-warn/40" /> zone del giocatore
                </span>
              ) : null}
            </div>
          </div>
          {inspector ? <ZoneInspector zone={inspector} /> : null}
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>Formazioni · clicca un giocatore per vederne le zone</SectionTitle>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-faint">
          <span>Barra: spessore = impatto, lunghezza = minuti.</span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-3 rounded-full bg-good" /> positivo
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-3 rounded-full bg-bad" /> negativo
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-3 rounded-full bg-surface-2" /> scoperto
          </span>
        </div>
        <div className="mt-3 grid gap-6 sm:grid-cols-2">
          <LineupColumn
            teamName={data.home_team}
            side="home"
            players={vm.homeBoard}
            gkRating={data.home_lineup.gk_rating}
            selectedPlayerId={selectedPlayer}
            onSelectPlayer={setSelectedPlayer}
          />
          <LineupColumn
            teamName={data.away_team}
            side="away"
            players={vm.awayBoard}
            gkRating={data.away_lineup.gk_rating}
            selectedPlayerId={selectedPlayer}
            onSelectPlayer={setSelectedPlayer}
          />
        </div>
      </Card>

      {/* Chi schiera le due squadre. Manca sull'artefatto della simulazione
          storica (squadre inventate, nessun account dietro), e la striscia lo
          sa: senza i due allenatori non disegna niente. */}
      <MatchManagers
        home={data.home_manager}
        away={data.away_manager}
        homeTeam={data.home_team}
        awayTeam={data.away_team}
        result={data.result}
      />
    </div>
  );
}
