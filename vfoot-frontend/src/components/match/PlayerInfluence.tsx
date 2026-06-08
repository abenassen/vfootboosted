import clsx from 'clsx';
import { SectionTitle } from '../ui';
import { zoneShortName } from '../../utils/zoneNames';

export interface PlayerFootprintZone {
  zoneKey: string;
  value: number;
}

export interface PlayerInfluenceVM {
  playerId: string | number;
  name: string;
  total: number;
  footprint: PlayerFootprintZone[]; // top zones by |contribution|
}

// Per-team ranked list of the most influential players, each with the pitch
// zones where they contributed most. Zone chips are clickable so the user can
// jump straight to that zone's breakdown.
export function PlayerInfluence({
  title,
  side,
  players,
  selectedZone,
  onSelectZone,
  limit = 6,
}: {
  title: string;
  side: 'home' | 'away';
  players: PlayerInfluenceVM[];
  selectedZone?: string | null;
  onSelectZone?: (zoneKey: string | null) => void;
  limit?: number;
}) {
  const top = players.slice(0, limit);
  const max = Math.max(0.0001, ...top.map((p) => Math.abs(p.total)));
  const accent = side === 'home' ? 'text-green-700' : 'text-sky-700';
  const bar = side === 'home' ? 'bg-green-500' : 'bg-sky-500';
  return (
    <div>
      <SectionTitle>{title} · giocatori più influenti</SectionTitle>
      <div className="mt-2 space-y-2.5">
        {top.map((p) => (
          <div key={p.playerId}>
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-800">{p.name}</span>
              <span className={clsx('font-mono text-xs', accent)}>
                {p.total >= 0 ? '+' : ''}
                {p.total.toFixed(2)}
              </span>
            </div>
            <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
              <div className={clsx('h-full', bar)} style={{ width: `${(Math.abs(p.total) / max) * 100}%` }} />
            </div>
            {p.footprint.length ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {p.footprint.map((z) => {
                  const selected = z.zoneKey === selectedZone;
                  return (
                    <button
                      key={z.zoneKey}
                      type="button"
                      onClick={onSelectZone ? () => onSelectZone(selected ? null : z.zoneKey) : undefined}
                      title={`${zoneShortName(z.zoneKey)} · ${z.value >= 0 ? '+' : ''}${z.value.toFixed(2)}`}
                      className={clsx(
                        'rounded px-1.5 py-0.5 text-[10px] font-medium transition',
                        selected
                          ? 'bg-slate-900 text-white'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200',
                      )}
                    >
                      {zoneShortName(z.zoneKey)}
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
