import clsx from 'clsx';
import { useMemo } from 'react';
import type { MatchResult } from './MatchScoreHeader';

export interface ZoneCellVM {
  zoneKey: string;
  col: number; // 1-based, left (defense) -> right (attack) for the home team
  row: number; // 1-based
  winner: MatchResult;
  margin: number;
}

const WINNER_BG: Record<MatchResult, string> = {
  home: 'bg-green-500',
  away: 'bg-sky-500',
  draw: 'bg-slate-300',
};

// 5x4 (configurable) pitch grid. Only the provided cells are "decisive"; the
// rest render as empty pitch. Cells are clickable and the selected one gets a
// ring, so a host page can sync selection with a detail list.
export function ZonePitchGrid({
  cells,
  cols = 5,
  rows = 4,
  selectedZone,
  onSelectZone,
}: {
  cells: ZoneCellVM[];
  cols?: number;
  rows?: number;
  selectedZone?: string | null;
  onSelectZone?: (zoneKey: string | null) => void;
}) {
  const byKey = useMemo(() => {
    const map = new Map<string, ZoneCellVM>();
    for (const c of cells) map.set(c.zoneKey, c);
    return map;
  }, [cells]);
  const maxAbs = useMemo(() => Math.max(0.0001, ...cells.map((c) => Math.abs(c.margin))), [cells]);

  const items = [];
  for (let row = 1; row <= rows; row++) {
    for (let col = 1; col <= cols; col++) {
      const key = `Z_${col}_${row}`;
      const cell = byKey.get(key);
      const selected = selectedZone === key;
      const intensity = cell ? 0.35 + 0.65 * (Math.abs(cell.margin) / maxAbs) : 1;
      items.push(
        <button
          key={key}
          type="button"
          disabled={!cell && !onSelectZone}
          title={cell ? `${key} · ${cell.winner} ${cell.margin.toFixed(2)}` : key}
          onClick={cell && onSelectZone ? () => onSelectZone(selected ? null : key) : undefined}
          className={clsx(
            'flex aspect-square items-center justify-center rounded text-[9px] font-semibold transition',
            cell ? `${WINNER_BG[cell.winner]} text-white` : 'bg-slate-100 text-slate-300',
            cell && onSelectZone && 'hover:brightness-110',
            selected && 'ring-2 ring-white ring-offset-1 ring-offset-emerald-900',
          )}
          style={cell ? { opacity: intensity } : undefined}
        >
          {cell ? cell.margin.toFixed(1) : ''}
        </button>,
      );
    }
  }

  return (
    <div>
      <div
        className="grid gap-1 rounded-xl bg-emerald-900/90 p-2"
        style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
      >
        {items}
      </div>
      <div className="mt-1 text-center text-[10px] text-slate-400">difesa ← → attacco (casa)</div>
    </div>
  );
}
