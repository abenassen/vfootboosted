import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import PitchZoneMap from '../components/PitchZoneMap';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import { getMatchDetail } from '../api';
import type { MatchDetailResponse, TeamSide } from '../types/contracts';
import { useAsync } from '../utils/useAsync';

type ViewMode = 'points' | 'margin' | 'key';

export default function MatchDetailPage() {
  const { matchId } = useParams();
  const { data, loading, error } = useAsync(() => getMatchDetail(matchId ?? 'M778'), [matchId]);

  const [selectedZone, setSelectedZone] = useState<string | null>(null);
  const [mode, setMode] = useState<ViewMode>('points');

  // ✅ hooks sempre chiamati, anche quando data è null
  const cells = useMemo(() => (data ? buildCells(data, mode) : []), [data, mode]);

  const zoneInfo = useMemo(() => {
    if (!data || !selectedZone) return null;
    return data.zone_results.find((z) => z.zone_id === selectedZone) ?? null;
  }, [data, selectedZone]);

  // ✅ solo dopo gli hook fai i return condizionali
  if (loading) return <div className="text-sm text-slate-500">Caricamento match…</div>;
  if (error || !data) return <div className="text-sm text-red-600">Errore: {error?.message}</div>;

  const homeName = data.teams.home.name;
  const awayName = data.teams.away.name;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-sm text-slate-500">
              Match · Giornata {data.match.matchday_id.replace('MD', '')}
            </div>
            <div className="mt-1 text-xl font-black">
              {homeName} <span className="text-slate-400">vs</span> {awayName}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone={data.score.home_total >= data.score.away_total ? 'green' : 'red'}>
              {data.score.home_total.toFixed(1)} – {data.score.away_total.toFixed(1)}
            </Badge>
            <Badge tone="slate">{data.provenance?.source ?? 'dati'}</Badge>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {data.story.takeaways.map((t, idx) => (
            <Badge key={idx} tone={t.swing >= 0 ? 'green' : 'red'}>
              {t.text}
            </Badge>
          ))}
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <PitchZoneMap
          grid={data.zone_grid}
          title="Campo a zone"
          cells={cells}
          selectedZoneId={selectedZone}
          onSelectZone={(z) => setSelectedZone(z)}
          legend={
            <div className="flex items-center gap-2">
              <Button size="sm" variant={mode === 'points' ? 'primary' : 'secondary'} onClick={() => setMode('points')}>Punti</Button>
              <Button size="sm" variant={mode === 'margin' ? 'primary' : 'secondary'} onClick={() => setMode('margin')}>Margine</Button>
              <Button size="sm" variant={mode === 'key' ? 'primary' : 'secondary'} onClick={() => setMode('key')}>Fattore</Button>
            </div>
          }
        />

        <ZonePanel data={data} zone={zoneInfo} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="p-4">
          <SectionTitle>Riepilogo fasce</SectionTitle>
          <div className="mt-3 space-y-2 text-sm">
            {Object.entries(data.line_summaries.by_flank).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between">
                <div className="font-semibold capitalize">{k}</div>
                <Badge tone={v.swing >= 0 ? 'green' : 'red'}>
                  {v.swing >= 0 ? '+' : ''}{v.swing.toFixed(1)}
                </Badge>
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-4">
          <SectionTitle>Riepilogo altezze</SectionTitle>
          <div className="mt-3 space-y-2 text-sm">
            {Object.entries(data.line_summaries.by_height).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between">
                <div className="font-semibold capitalize">{k}</div>
                <Badge tone={v.swing >= 0 ? 'green' : 'red'}>
                  {v.swing >= 0 ? '+' : ''}{v.swing.toFixed(1)}
                </Badge>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}


function buildCells(data: MatchDetailResponse, mode: 'points' | 'margin' | 'key') {
  const zones = data.zone_grid.zone_ids;
  const winners = data.zone_maps.winner_map.values;
  const points = data.zone_maps.points_map.values;
  const margins = data.zone_maps.margin_map.values;
  const keys = data.zone_maps.key_factor_map.values;

  const maxPoints = Math.max(...points, 0.0001);

  return zones.map((zoneId, idx) => {
    const w = winners[idx] ?? 'draw';
    const tone = w as TeamSide | 'draw';

    if (mode === 'points') {
      const v = (points[idx] ?? 0) / maxPoints;
      return { zone_id: zoneId, tone, value: points[idx] ?? 0, _v: v } as any;
    }

    if (mode === 'margin') {
      const v = Math.max(0, Math.min(1, margins[idx] ?? 0));
      return { zone_id: zoneId, tone, value: (margins[idx] ?? 0) * 10, _v: v } as any;
    }

    // key
    return { zone_id: zoneId, tone, keyLabel: (keys[idx] ?? '').slice(0, 3).toUpperCase(), value: undefined } as any;
  }).map((c: any) => {
    // use value normalization for background alpha
    const v = c._v ?? 0.15;
    return { ...c, value: mode === 'key' ? undefined : c.value, _v: undefined, valueNorm: v };
  }).map((c: any) => ({ zone_id: c.zone_id, tone: c.tone, value: c.value, keyLabel: c.keyLabel, valueNorm: c.valueNorm }));
}

function ZonePanel({ data, zone }: { data: MatchDetailResponse; zone: MatchDetailResponse['zone_results'][number] | null }) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <SectionTitle>Dettaglio zona</SectionTitle>
          <div className="mt-1 font-black">{zone ? zone.zone_id : 'Seleziona una zona'}</div>
        </div>
        {!zone ? null : (
          <Badge tone={zone.points.swing >= 0 ? 'green' : 'red'}>
            swing {zone.points.swing >= 0 ? '+' : ''}{zone.points.swing.toFixed(1)}
          </Badge>
        )}
      </div>

      {!zone ? (
        <div className="mt-3 text-sm text-slate-500">
          Tocca una zona sul campo per vedere: punti, macro-confronto e top giocatori.
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          <div className="flex items-center justify-between text-sm">
            <div className="text-slate-500">Punti zona</div>
            <div className="font-bold">Casa {zone.points.home.toFixed(1)} · Trasferta {zone.points.away.toFixed(1)}</div>
          </div>

          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Confronto macro</div>
            <div className="mt-2 space-y-2">
              {Object.entries(zone.macro_scores).map(([k, s]) => (
                <MacroBar key={k} label={k} home={s.home} away={s.away} />
              ))}
            </div>
            <div className="mt-2 text-xs text-slate-500">
              Fattore decisivo: <span className="font-semibold text-slate-700">{zone.key_factor}</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Casa</div>
              <div className="mt-2 space-y-2">
                {zone.top_contributors.home.slice(0, 3).map((p) => (
                  <div key={p.player_id} className="flex items-center justify-between text-sm">
                    <div className="font-semibold">{p.name}</div>
                    <Badge tone="slate">{p.contrib >= 0 ? '+' : ''}{p.contrib.toFixed(1)}</Badge>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Trasferta</div>
              <div className="mt-2 space-y-2">
                {zone.top_contributors.away.slice(0, 3).map((p) => (
                  <div key={p.player_id} className="flex items-center justify-between text-sm">
                    <div className="font-semibold">{p.name}</div>
                    <Badge tone="slate">{p.contrib >= 0 ? '+' : ''}{p.contrib.toFixed(1)}</Badge>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {zone.explain_stats ? (
            <details className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
              <summary className="cursor-pointer text-sm font-semibold text-slate-700">Mostra dettagli (esempio stats)</summary>
              <div className="mt-3 space-y-3">
                {Object.entries(zone.explain_stats).map(([macro, stats]) => (
                  <div key={macro}>
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{macro}</div>
                    <div className="mt-1 space-y-1 text-sm">
                      {stats.map((st) => (
                        <div key={st.label} className="flex items-center justify-between">
                          <div>{st.label}</div>
                          <div className="font-semibold">{st.home} – {st.away}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </details>
          ) : null}

          <div className="text-xs text-slate-500">
            Nota: i macro-score sono un primo layer Vfoot e possono essere raffinati con ingestion real-data (es. Sofascore).
          </div>
        </div>
      )}
    </Card>
  );
}

function MacroBar({ label, home, away }: { label: string; home: number; away: number }) {
  const total = home + away + 1e-9;
  const left = (home / total) * 100;
  const right = (away / total) * 100;

  return (
    <div>
      <div className="flex items-center justify-between text-xs text-slate-500">
        <div className="font-semibold">{label}</div>
        <div>{home.toFixed(2)} / {away.toFixed(2)}</div>
      </div>
      <div className="mt-1 h-2 rounded-full bg-slate-200 overflow-hidden">
        <div className="h-full bg-slate-900" style={{ width: `${left}%` }} />
        <div className="h-full bg-blue-600" style={{ width: `${right}%` }} />
      </div>
    </div>
  );
}
