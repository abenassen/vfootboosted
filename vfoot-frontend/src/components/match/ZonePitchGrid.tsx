import clsx from 'clsx';
import { useMemo } from 'react';
import type { MatchResult } from './MatchScoreHeader';
import { ZONE_COLS, ZONE_ROWS, zoneName } from '../../utils/zoneNames';

export interface ZoneCellVM {
  zoneKey: string;
  col: number; // 0-based, 0 = own defense -> ZONE_COLS-1 = attack (home perspective)
  row: number; // 0-based, across the width
  winner: MatchResult;
  margin: number;
  hasPresence: boolean;
}

// On the green pitch, home/away use red/blue (green would vanish into the turf).
const WINNER_RGB: Record<MatchResult, string> = {
  home: '239,68,68', // red-500
  away: '37,99,235', // blue-600
  draw: '148,163,184', // slate-400
};

// Full pitch (every zone) drawn as the same green field used for the lineup, with
// each zone tinted by its winner (red = home, blue = away) and intensity by
// |margin|. Any zone is clickable; the selected one gets a white ring and a
// player's footprint zones an amber ring.
export function ZonePitchGrid({
  cells,
  selectedZone,
  onSelectZone,
  highlightZones,
}: {
  cells: ZoneCellVM[];
  selectedZone?: string | null;
  onSelectZone?: (zoneKey: string | null) => void;
  highlightZones?: string[] | null;
}) {
  const byKey = useMemo(() => new Map(cells.map((c) => [c.zoneKey, c])), [cells]);
  const highlighted = useMemo(() => new Set(highlightZones ?? []), [highlightZones]);
  const hasHighlight = highlighted.size > 0;
  const maxAbs = useMemo(
    () => Math.max(0.0001, ...cells.filter((c) => c.hasPresence).map((c) => Math.abs(c.margin))),
    [cells],
  );

  const items = [];
  for (let row = 0; row < ZONE_ROWS; row++) {
    for (let col = 0; col < ZONE_COLS; col++) {
      const key = `Z_${col}_${row}`;
      const cell = byKey.get(key);
      const active = cell?.hasPresence ?? false;
      const selected = selectedZone === key;
      const isHighlighted = highlighted.has(key);
      const dimmed = hasHighlight && !isHighlighted;
      const intensity = active ? Math.abs(cell!.margin) / maxAbs : 0;
      const bg = active
        ? `rgba(${WINNER_RGB[cell!.winner]},${(dimmed ? 0.18 : 0.62 + 0.33 * intensity).toFixed(3)})`
        : 'rgba(255,255,255,0.05)';
      items.push(
        <button
          key={key}
          type="button"
          title={`${zoneName(key)}${active ? ` · margine ${cell!.margin.toFixed(2)}` : ' · nessuna presenza'}`}
          onClick={onSelectZone ? () => onSelectZone(selected ? null : key) : undefined}
          className={clsx(
            'absolute flex items-center justify-center border border-white/10 text-[9px] font-bold text-white/90 transition',
            onSelectZone && 'hover:brightness-125',
            isHighlighted && 'z-10 ring-2 ring-amber-300',
            selected && 'z-10 ring-2 ring-white',
          )}
          style={{
            left: `${(col / ZONE_COLS) * 100}%`,
            top: `${(row / ZONE_ROWS) * 100}%`,
            width: `${100 / ZONE_COLS}%`,
            height: `${100 / ZONE_ROWS}%`,
            backgroundColor: bg,
          }}
        >
          {active ? cell!.margin.toFixed(1) : ''}
        </button>,
      );
    }
  }

  return (
    <div>
      <div className="relative aspect-[7/5] w-full overflow-hidden rounded-xl border border-green-700/40 bg-gradient-to-r from-green-600 to-green-500 shadow-inner">
        {items}
        {/* pitch markings drawn on top so they stay visible over the zone tints */}
        <div className="pointer-events-none absolute inset-2 rounded border border-white/50" />
        <div className="pointer-events-none absolute inset-y-2 left-1/2 w-px -translate-x-1/2 bg-white/50" />
        <div className="pointer-events-none absolute left-1/2 top-1/2 h-16 w-16 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/50" />
        <div className="pointer-events-none absolute left-2 top-1/2 h-24 w-12 -translate-y-1/2 border border-white/50" />
        <div className="pointer-events-none absolute right-2 top-1/2 h-24 w-12 -translate-y-1/2 border border-white/50" />
      </div>
      <div className="mt-1 flex justify-between px-1 text-[10px] text-slate-400">
        <span>← difesa (casa)</span>
        <span>attacco →</span>
      </div>
    </div>
  );
}
