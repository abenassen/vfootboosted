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

export function ZoneInspector({ zone }: { zone: ZoneInspectorVM }) {
  const tone = zone.winner === 'home' ? 'green' : zone.winner === 'away' ? 'slate' : 'amber';
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-bold text-slate-900">{zone.name}</div>
          <div className="text-[11px] text-slate-400">
            Vince <span className="font-semibold">{zone.winnerLabel}</span> · margine {zone.margin.toFixed(3)}
          </div>
        </div>
        <Badge tone={tone}>{zone.winnerLabel}</Badge>
      </div>

      {zone.features.length ? (
        <div className="mt-3">
          <div className="text-[11px] uppercase tracking-wide text-slate-400">Confronto per feature</div>
          <div className="mt-2 space-y-2">
            {zone.features.map((f) => (
              <FeatureRow key={f.feature} f={f} />
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-3 text-xs text-slate-400">Nessuna azione rilevante in questa zona.</div>
      )}

      {zone.homePlayers.length || zone.awayPlayers.length ? (
        <div className="mt-4 grid grid-cols-2 gap-3">
          <PlayerColumn title={zone.homeName} players={zone.homePlayers} side="home" />
          <PlayerColumn title={zone.awayName} players={zone.awayPlayers} side="away" />
        </div>
      ) : null}
    </div>
  );
}

function FeatureRow({ f }: { f: ZoneFeatureVM }) {
  const scale = Math.max(f.home, f.away, 0.0001);
  return (
    <div>
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-slate-600">{featureLabel(f.feature)}</span>
        <span
          className={clsx(
            'rounded px-1.5 py-0.5 font-medium',
            f.swing >= 0 ? 'bg-green-100 text-green-800' : 'bg-sky-100 text-sky-800',
          )}
        >
          {f.swing >= 0 ? '+' : ''}
          {f.swing.toFixed(2)}
        </span>
      </div>
      <div className="mt-0.5 flex items-center gap-1">
        <span className="w-10 text-right font-mono text-[10px] text-slate-500">{f.home}</span>
        <div className="flex h-2 flex-1 justify-end overflow-hidden rounded-l-full bg-slate-100">
          <div className="h-full rounded-l-full bg-green-500" style={{ width: `${(f.home / scale) * 100}%` }} />
        </div>
        <div className="flex h-2 flex-1 overflow-hidden rounded-r-full bg-slate-100">
          <div className="h-full rounded-r-full bg-sky-500" style={{ width: `${(f.away / scale) * 100}%` }} />
        </div>
        <span className="w-10 font-mono text-[10px] text-slate-500">{f.away}</span>
      </div>
    </div>
  );
}

function PlayerColumn({ title, players, side }: { title: string; players: ZonePlayerVM[]; side: 'home' | 'away' }) {
  const max = Math.max(0.0001, ...players.map((p) => Math.abs(p.contribution)));
  const bar = side === 'home' ? 'bg-green-500' : 'bg-sky-500';
  return (
    <div>
      <div className={clsx('text-[11px] font-semibold', side === 'home' ? 'text-green-700' : 'text-sky-700')}>{title}</div>
      <div className="mt-1 space-y-1">
        {players.length ? (
          players.map((p) => (
            <div key={p.name} className="text-[11px]">
              <div className="flex items-center justify-between">
                <span className="truncate text-slate-700">{p.name}</span>
                <span className="ml-1 font-mono text-slate-400">
                  {p.contribution >= 0 ? '+' : ''}
                  {p.contribution.toFixed(2)}
                </span>
              </div>
              <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
                <div className={clsx('h-full', bar)} style={{ width: `${(Math.abs(p.contribution) / max) * 100}%` }} />
              </div>
            </div>
          ))
        ) : (
          <div className="text-[11px] text-slate-300">—</div>
        )}
      </div>
    </div>
  );
}
