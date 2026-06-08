import clsx from 'clsx';
import { Badge } from '../ui';
import { featureLabel } from '../../utils/vfoot';
import type { MatchResult } from './MatchScoreHeader';
import { MacroContributions, type MacroContributionVM } from './MacroContributions';

export interface ZoneFeatureVM {
  feature: string;
  home: number;
  away: number;
  swing: number; // >0 favours home
}

export interface ZonePlayerVM {
  name: string;
  contribution: number;
  share: number; // 0..1 of the team's action in this zone
}

export interface ZoneInspectorVM {
  zoneKey: string;
  name: string;
  winner: MatchResult;
  winnerLabel: string;
  margin: number;
  marginShare: number; // |margin| / match max |margin| (0..1), for the dominance bar
  homeName: string;
  awayName: string;
  macros: MacroContributionVM[];
  features: ZoneFeatureVM[];
  homePlayers: ZonePlayerVM[];
  awayPlayers: ZonePlayerVM[];
}

const pct = (x: number) => `${Math.round(x * 100)}%`;

export function ZoneInspector({ zone }: { zone: ZoneInspectorVM }) {
  const tone = zone.winner === 'home' ? 'green' : zone.winner === 'away' ? 'slate' : 'amber';
  const winnerColor = zone.winner === 'home' ? 'text-green-600' : zone.winner === 'away' ? 'text-sky-600' : 'text-slate-500';
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center justify-between">
        <div className="text-sm font-bold text-slate-900">{zone.name}</div>
        <Badge tone={tone}>{zone.winner === 'draw' ? 'Pari' : 'Vince ' + zone.winnerLabel}</Badge>
      </div>

      {/* Headline: who won and by how much (dominance tug-of-war). */}
      <div className="mt-2">
        <div className="flex items-center justify-between text-[11px]">
          <span className={zone.winner === 'home' ? 'font-semibold text-green-700' : 'text-slate-500'}>{zone.homeName}</span>
          <span className="text-slate-500">
            {zone.winner === 'draw' ? (
              'equilibrio'
            ) : (
              <>
                <span className={`font-semibold ${winnerColor}`}>{zone.winnerLabel}</span> vince · margine{' '}
                <b className="font-mono">{Math.abs(zone.margin).toFixed(2)}</b>
              </>
            )}
          </span>
          <span className={zone.winner === 'away' ? 'font-semibold text-sky-700' : 'text-slate-500'}>{zone.awayName}</span>
        </div>
        <div className="relative mt-1 h-3 overflow-hidden rounded-full bg-slate-100">
          {/* centre line */}
          <div className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-slate-300" />
          {zone.winner !== 'draw' ? (
            <div
              className={`absolute top-0 h-full ${zone.winner === 'home' ? 'bg-green-500' : 'bg-sky-500'}`}
              style={
                zone.winner === 'home'
                  ? { right: '50%', width: `${zone.marginShare * 50}%` }
                  : { left: '50%', width: `${zone.marginShare * 50}%` }
              }
            />
          ) : null}
        </div>
      </div>

      {zone.macros.length ? (
        <div className="mt-3">
          <MacroContributions items={zone.macros} homeName={zone.homeName} awayName={zone.awayName} />
        </div>
      ) : null}

      {zone.features.length ? (
        <details className="mt-3 group">
          <summary className="cursor-pointer list-none text-[11px] uppercase tracking-wide text-slate-400 hover:text-slate-600">
            Dati reali per feature ▾
          </summary>
          <div className="mt-1 flex items-center justify-between text-[10px] uppercase tracking-wide text-slate-400">
            <span className="text-green-700">{zone.homeName}</span>
            <span className="text-sky-700">{zone.awayName}</span>
          </div>
          <div className="mt-1 space-y-0.5">
            {zone.features.map((f) => (
              <FeatureRow key={f.feature} f={f} />
            ))}
          </div>
        </details>
      ) : null}

      {zone.homePlayers.length || zone.awayPlayers.length ? (
        <div className="mt-4">
          <div className="text-[11px] uppercase tracking-wide text-slate-400">Chi ha agito qui</div>
          <div className="mt-1.5 grid grid-cols-2 gap-3">
            <PlayerColumn players={zone.homePlayers} side="home" />
            <PlayerColumn players={zone.awayPlayers} side="away" />
          </div>
        </div>
      ) : null}
    </div>
  );
}

const fmtVal = (v: number) => (Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100));

// Raw per-feature values (actual events), home vs away. The larger side is
// emphasised. This shows the real data behind the macro bars, not a duplicate
// of them.
function FeatureRow({ f }: { f: ZoneFeatureVM }) {
  const homeBig = f.home > f.away;
  const awayBig = f.away > f.home;
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className={clsx('w-12 text-right font-mono', homeBig ? 'font-semibold text-green-700' : 'text-slate-400')}>
        {fmtVal(f.home)}
      </span>
      <span className="flex-1 text-center text-slate-600">{featureLabel(f.feature)}</span>
      <span className={clsx('w-12 font-mono', awayBig ? 'font-semibold text-sky-700' : 'text-slate-400')}>
        {fmtVal(f.away)}
      </span>
    </div>
  );
}

function PlayerColumn({ players, side }: { players: ZonePlayerVM[]; side: 'home' | 'away' }) {
  const bar = side === 'home' ? 'bg-green-500' : 'bg-sky-500';
  return (
    <div className="space-y-1">
      {players.length ? (
        players.slice(0, 5).map((p) => (
          <div key={p.name} className="text-[11px]" title={`contributo ${p.contribution >= 0 ? '+' : ''}${p.contribution.toFixed(2)}`}>
            <div className="flex items-center justify-between">
              <span className="truncate text-slate-700">{p.name}</span>
              <span className="ml-1 font-mono text-slate-400">{pct(p.share)}</span>
            </div>
            <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
              <div className={clsx('h-full', bar)} style={{ width: `${p.share * 100}%` }} />
            </div>
          </div>
        ))
      ) : (
        <div className="text-[11px] text-slate-300">—</div>
      )}
    </div>
  );
}
