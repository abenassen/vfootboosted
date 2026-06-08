import clsx from 'clsx';
import { Badge } from '../ui';
import { featureLabel } from '../../utils/vfoot';
import type { MatchResult } from './MatchScoreHeader';

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
  homeName: string;
  awayName: string;
  features: ZoneFeatureVM[];
  homePlayers: ZonePlayerVM[];
  awayPlayers: ZonePlayerVM[];
}

const pct = (x: number) => `${Math.round(x * 100)}%`;

export function ZoneInspector({ zone }: { zone: ZoneInspectorVM }) {
  const tone = zone.winner === 'home' ? 'green' : zone.winner === 'away' ? 'slate' : 'amber';
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-bold text-slate-900">{zone.name}</div>
          <div className="text-[11px] text-slate-400">
            Vince <span className="font-semibold">{zone.winnerLabel}</span>
          </div>
        </div>
        <Badge tone={tone}>{zone.winnerLabel}</Badge>
      </div>

      {zone.features.length ? (
        <div className="mt-3">
          <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-slate-400">
            <span>{zone.homeName}</span>
            <span>{zone.awayName}</span>
          </div>
          <div className="mt-2 space-y-2.5">
            {zone.features.map((f) => (
              <FeatureRow key={f.feature} f={f} homeName={zone.homeName} awayName={zone.awayName} />
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-3 text-xs text-slate-400">Nessuna azione rilevante in questa zona.</div>
      )}

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

function FeatureRow({ f, homeName, awayName }: { f: ZoneFeatureVM; homeName: string; awayName: string }) {
  const total = f.home + f.away;
  const homeShare = total > 0 ? f.home / total : 0.5;
  return (
    <div title={`${featureLabel(f.feature)} — ${homeName} ${f.home} · ${awayName} ${f.away}`}>
      <div className="text-[11px] text-slate-600">{featureLabel(f.feature)}</div>
      <div className="mt-0.5 flex items-center gap-1.5">
        <span className="w-8 text-right font-mono text-[10px] text-green-700">{pct(homeShare)}</span>
        <div className="flex h-2.5 flex-1 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full bg-green-500" style={{ width: `${homeShare * 100}%` }} />
          <div className="h-full bg-sky-500" style={{ width: `${(1 - homeShare) * 100}%` }} />
        </div>
        <span className="w-8 font-mono text-[10px] text-sky-700">{pct(1 - homeShare)}</span>
      </div>
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
