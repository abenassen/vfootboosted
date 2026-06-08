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

const WINNER_BG: Record<MatchResult, string> = {
  home: 'bg-green-500',
  away: 'bg-sky-500',
  draw: 'bg-slate-300',
};

// Full pitch grid (every zone shown). Zones with presence are coloured by
// winner with intensity by |margin|; zones where neither team acted are faint.
// Any zone is clickable and the selected one gets a ring.
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
  const byKey = useMemo(() => {
    const map = new Map<string, ZoneCellVM>();
    for (const c of cells) map.set(c.zoneKey, c);
    return map;
  }, [cells]);
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
      const intensity = dimmed ? 0.18 : active ? 0.4 + 0.6 * (Math.abs(cell!.margin) / maxAbs) : 1;
      items.push(
        <button
          key={key}
          type="button"
          title={`${zoneName(key)}${active ? ` · margine ${cell!.margin.toFixed(2)}` : ' · nessuna presenza'}`}
          onClick={onSelectZone ? () => onSelectZone(selected ? null : key) : undefined}
          className={clsx(
            'flex aspect-[4/3] items-center justify-center rounded-md text-[10px] font-bold transition',
            active ? `${WINNER_BG[cell!.winner]} text-white` : 'bg-emerald-800/40 text-emerald-200/40',
            onSelectZone && 'hover:brightness-110',
            isHighlighted && 'ring-2 ring-amber-300',
            selected && 'ring-2 ring-white ring-offset-2 ring-offset-emerald-900',
          )}
          style={active || dimmed ? { opacity: intensity } : undefined}
        >
          {active ? cell!.margin.toFixed(1) : '·'}
        </button>,
      );
    }
  }

  return (
    <div>
      <div
        className="grid gap-1.5 rounded-xl bg-gradient-to-r from-emerald-900 to-emerald-800 p-2.5"
        style={{ gridTemplateColumns: `repeat(${ZONE_COLS}, minmax(0, 1fr))` }}
      >
        {items}
      </div>
      <div className="mt-1 flex justify-between px-1 text-[10px] text-slate-400">
        <span>← difesa (casa)</span>
        <span>attacco →</span>
      </div>
    </div>
  );
}
