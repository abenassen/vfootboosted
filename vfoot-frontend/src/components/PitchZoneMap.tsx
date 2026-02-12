import clsx from 'clsx';
import type { ZoneGrid } from '../types/contracts';

export type ZoneValueMode = 'coverage' | 'quality' | 'winner' | 'points' | 'margin' | 'key';

export default function PitchZoneMap({
  grid,
  title,
  cells,
  onSelectZone,
  selectedZoneId,
  className,
  legend,
  showZoneLabels = false
}: {
  grid: ZoneGrid;
  title?: string;
  cells: Array<{ zone_id: string; value?: number; tone?: 'home' | 'away' | 'draw' | 'none'; keyLabel?: string }>;
  onSelectZone?: (zoneId: string) => void;
  selectedZoneId?: string | null;
  className?: string;
  legend?: React.ReactNode;
  showZoneLabels?: boolean;
}) {
  const cols = grid.cols;
  const rows = grid.rows;

  return (
    <div className={clsx('rounded-2xl bg-white shadow-card p-4', className)}>
      {title && (
        <div className="flex items-center justify-between gap-2">
          <div className="font-semibold">{title}</div>
          {legend}
        </div>
      )}

      <div
        className="mt-3 grid gap-1 rounded-2xl bg-slate-100 p-2"
        style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
      >
        {cells.map((cell) => {
          const isSel = selectedZoneId === cell.zone_id;
          const bg = zoneColor(cell);
          return (
            <button
              key={cell.zone_id}
              onClick={() => onSelectZone?.(cell.zone_id)}
              className={clsx(
                'relative aspect-[1/1] rounded-lg border transition',
                isSel ? 'border-slate-900 ring-2 ring-slate-900/20' : 'border-transparent',
                'focus:outline-none focus:ring-2 focus:ring-slate-900/20'
              )}
              style={{ background: bg }}
              title={cell.zone_id}
            >
              {showZoneLabels && <div className="absolute top-1 left-1 text-[10px] font-semibold text-slate-700/70">{cell.zone_id}</div>}
              {typeof cell.value === 'number' && (
                <div className="absolute bottom-1 right-1 text-[11px] font-bold text-slate-900/80">
                  {cell.value.toFixed(1)}
                </div>
              )}
              {cell.keyLabel && (
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="rounded-full bg-white/70 px-2 py-1 text-[10px] font-semibold text-slate-800">
                    {cell.keyLabel}
                  </span>
                </div>
              )}
            </button>
          );
        })}
      </div>

      <div className="mt-3 text-xs text-slate-500">
        Campo a zone (griglia {cols}×{rows}). Tocca una zona per vedere i dettagli.
      </div>
    </div>
  );
}

function zoneColor(cell: { value?: number; tone?: 'home' | 'away' | 'draw' | 'none' }) {
  const v = Math.max(0, Math.min(1, cell.value ?? 0));
  const a = 0.08 + 0.75 * v;

  switch (cell.tone) {
    case 'home':
      return `rgba(15, 23, 42, ${a})`; // slate-900-ish
    case 'away':
      return `rgba(37, 99, 235, ${a})`; // blue-600-ish
    case 'draw':
      return `rgba(100, 116, 139, ${a})`; // slate-500-ish
    default:
      return `rgba(148, 163, 184, ${0.08 + 0.5 * v})`;
  }
}
