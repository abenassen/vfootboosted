import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getSimulationFixtureDetail } from '../api/simulation';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import { useAsync } from '../utils/useAsync';
import type {
  SimFixtureDetail,
  SimLineup,
  SimResult,
  SimTopZone,
} from '../types/simulation';

const FEATURE_LABELS: Record<string, string> = {
  xg_shots: 'xG',
  shots: 'Tiri',
  touches_in_box: 'Tocchi in area',
  key_passes: 'Passaggi chiave',
  passes_into_box: 'Passaggi in area',
  progressive_passes_completed: 'Passaggi progressivi',
  progressive_carries: 'Conduzioni progressive',
  ball_recoveries: 'Recuperi',
  interceptions: 'Intercetti',
  pressures: 'Pressioni',
  clearances: 'Spazzate',
  errors_bad_passes: 'Errori passaggio',
  errors_dispossessed: 'Palle perse',
  errors_fouls_committed: 'Falli',
  errors_miscontrols: 'Stop sbagliati',
};

function featureLabel(key: string): string {
  return FEATURE_LABELS[key] ?? key.replace(/_/g, ' ');
}

function minutes(seconds: number): string {
  return `${Math.round(seconds / 60)}'`;
}

const WINNER_BG: Record<SimResult, string> = {
  home: 'bg-green-500',
  away: 'bg-sky-500',
  draw: 'bg-slate-300',
};

export default function SimulationMatchDetailPage() {
  const { fixtureId } = useParams();
  const id = Number(fixtureId);
  const { data, loading, error } = useAsync(() => getSimulationFixtureDetail(id), [fixtureId]);

  if (loading) return <div className="text-sm text-slate-500">Caricamento partita…</div>;
  if (error || !data) {
    return (
      <Card className="p-4 text-sm text-red-600">Errore nel caricamento della partita: {error?.message ?? 'sconosciuto'}</Card>
    );
  }

  return (
    <div className="space-y-4">
      <ScoreHeader data={data} />
      <ZoneDuelCard data={data} />
      <div className="grid gap-4 lg:grid-cols-2">
        <LineupCard title={data.home_team} side="home" lineup={data.home_lineup} />
        <LineupCard title={data.away_team} side="away" lineup={data.away_lineup} />
      </div>
    </div>
  );
}

function ScoreHeader({ data }: { data: SimFixtureDetail }) {
  const homeWin = data.result === 'home';
  const awayWin = data.result === 'away';
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <SectionTitle>
          Giornata {data.fantasy_round} · Serie A reale {data.real_matchday}
        </SectionTitle>
        <Link to="/simulation/matches">
          <Button variant="ghost" size="sm">
            ← Partite
          </Button>
        </Link>
      </div>
      <div className="mt-3 flex items-center justify-center gap-4 sm:gap-8">
        <div className="flex-1 text-right">
          <div className={homeWin ? 'text-lg font-black text-slate-900' : 'text-lg font-semibold text-slate-600'}>
            {data.home_team}
          </div>
          <div className="text-xs text-slate-400">Vfoot {data.home_score.toFixed(2)}</div>
        </div>
        <div className="flex items-center gap-2 rounded-2xl bg-slate-900 px-4 py-2 font-mono text-2xl font-black text-white">
          <span className={homeWin ? 'text-green-400' : ''}>{data.home_goals}</span>
          <span className="text-slate-500">-</span>
          <span className={awayWin ? 'text-green-400' : ''}>{data.away_goals}</span>
        </div>
        <div className="flex-1">
          <div className={awayWin ? 'text-lg font-black text-slate-900' : 'text-lg font-semibold text-slate-600'}>
            {data.away_team}
          </div>
          <div className="text-xs text-slate-400">Vfoot {data.away_score.toFixed(2)}</div>
        </div>
      </div>
      <div className="mt-3 flex justify-center">
        <Badge tone="slate">margine zona-vettore {data.vector_report.total_margin.toFixed(3)}</Badge>
      </div>
    </Card>
  );
}

function ZoneDuelCard({ data }: { data: SimFixtureDetail }) {
  const zones = data.vector_report.top_zones;
  return (
    <Card className="p-4">
      <SectionTitle>Duello a zone (decisive)</SectionTitle>
      <div className="mt-3 grid gap-4 md:grid-cols-[180px_1fr]">
        <PitchGrid zones={zones} />
        <div className="space-y-2">
          {zones.map((z) => (
            <ZoneRow key={z.zone_key} z={z} home={data.home_team} away={data.away_team} />
          ))}
        </div>
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
  );
}

// Renders the 5x4 pitch grid (attack to the right) highlighting the decisive zones.
function PitchGrid({ zones }: { zones: SimTopZone[] }) {
  const byKey = useMemo(() => {
    const map = new Map<string, SimTopZone>();
    for (const z of zones) map.set(z.zone_key, z);
    return map;
  }, [zones]);
  const maxAbs = useMemo(() => Math.max(0.0001, ...zones.map((z) => Math.abs(z.margin))), [zones]);

  const cols = 5;
  const rows = 4;
  const cells = [];
  for (let row = 1; row <= rows; row++) {
    for (let col = 1; col <= cols; col++) {
      const key = `Z_${col}_${row}`;
      const z = byKey.get(key);
      let cls = 'bg-slate-100';
      let opacity = 1;
      if (z) {
        cls = WINNER_BG[z.winner];
        opacity = 0.35 + 0.65 * (Math.abs(z.margin) / maxAbs);
      }
      cells.push(
        <div
          key={key}
          title={z ? `${key} · ${z.winner} ${z.margin.toFixed(2)}` : key}
          className={`flex aspect-square items-center justify-center rounded text-[9px] font-semibold ${cls} ${z ? 'text-white' : 'text-slate-300'}`}
          style={z ? { opacity } : undefined}
        >
          {z ? z.margin.toFixed(1) : ''}
        </div>,
      );
    }
  }
  return (
    <div>
      <div className="grid grid-cols-5 gap-1 rounded-xl bg-emerald-900/90 p-2">{cells}</div>
      <div className="mt-1 text-center text-[10px] text-slate-400">difesa ← → attacco (casa)</div>
    </div>
  );
}

function ZoneRow({ z, home, away }: { z: SimTopZone; home: string; away: string }) {
  const winnerName = z.winner === 'home' ? home : z.winner === 'away' ? away : 'Pari';
  const tone = z.winner === 'home' ? 'green' : z.winner === 'away' ? 'slate' : 'amber';
  return (
    <div className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-2">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs font-semibold text-slate-700">{z.zone_key}</span>
        <div className="flex items-center gap-2">
          <Badge tone={tone}>{winnerName}</Badge>
          <span className="font-mono text-xs text-slate-500">{z.margin.toFixed(3)}</span>
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1">
        {z.top_contributions.map((c) => (
          <span
            key={c.feature}
            className={
              c.swing >= 0
                ? 'rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-medium text-green-800'
                : 'rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-medium text-sky-800'
            }
          >
            {featureLabel(c.feature)} {c.swing >= 0 ? '+' : ''}
            {c.swing.toFixed(2)}
          </span>
        ))}
      </div>
    </div>
  );
}

function LineupCard({ title, side, lineup }: { title: string; side: 'home' | 'away'; lineup: SimLineup }) {
  const sub = lineup.substitution_report;
  const accent = side === 'home' ? 'text-green-600' : 'text-sky-600';
  const starters = [...lineup.starters].sort((a, b) => b.event_score - a.event_score);
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <SectionTitle>{title}</SectionTitle>
        <span className={`text-sm font-bold ${accent}`}>{lineup.score.toFixed(2)}</span>
      </div>

      <div className="mt-3 space-y-1">
        {starters.map((p) => (
          <div key={p.player_id} className="flex items-center justify-between text-sm">
            <span className="text-slate-700">{p.name}</span>
            <span className="font-mono text-xs text-slate-500">{p.event_score.toFixed(2)}</span>
          </div>
        ))}
      </div>

      {lineup.bench.length ? (
        <div className="mt-3 border-t border-slate-100 pt-2">
          <div className="text-[11px] uppercase tracking-wide text-slate-400">Panchina</div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-slate-500">
            {lineup.bench.map((p) => (
              <span key={p.player_id}>{p.name}</span>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-3 border-t border-slate-100 pt-2">
        <div className="text-[11px] uppercase tracking-wide text-slate-400">Sostituzioni temporali</div>
        <div className="mt-1 flex flex-wrap gap-2 text-[11px]">
          <Badge tone="green">coperti {minutes(sub.covered_gap_seconds)}</Badge>
          {sub.uncovered_gap_seconds ? <Badge tone="amber">scoperti {minutes(sub.uncovered_gap_seconds)}</Badge> : null}
          {sub.disciplinary_gap_seconds ? (
            <Badge tone="red">espulsioni {minutes(sub.disciplinary_gap_seconds)}</Badge>
          ) : null}
          <Badge tone="slate">{sub.used_bench_count} subentri</Badge>
        </div>
        {sub.substitutions.length ? (
          <div className="mt-2 space-y-1">
            {sub.substitutions.map((s, i) => {
              const disciplinary = s.reason === 'disciplinary_gap';
              return (
                <div key={`${s.starter_id}-${i}`} className="text-xs text-slate-600">
                  <span className="text-slate-400">
                    {minutes(s.gap[0])}–{minutes(s.gap[1])}
                  </span>{' '}
                  {s.starter}{' '}
                  {s.covered && s.bench ? (
                    <>
                      <span className="text-slate-400">→</span> <b>{s.bench}</b>{' '}
                      <span className="text-green-600">({minutes(s.covered_seconds ?? 0)} coperti)</span>
                    </>
                  ) : disciplinary ? (
                    <span className="text-red-600">— espulso, intervallo non copribile</span>
                  ) : (
                    <span className="text-amber-600">— scoperto, nessun subentro</span>
                  )}
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
    </Card>
  );
}
