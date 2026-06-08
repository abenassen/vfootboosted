import clsx from 'clsx';

// Generic horizontal bar where each value is shown as a share of the total.
export interface DistributionBarItem {
  label: string;
  value: number;
  colorClass?: string;
}

export function DistributionBars({
  items,
  showPercent = true,
}: {
  items: DistributionBarItem[];
  showPercent?: boolean;
}) {
  const total = items.reduce((s, i) => s + i.value, 0) || 1;
  return (
    <div className="space-y-3">
      {items.map((b) => (
        <div key={b.label}>
          <div className="flex items-center justify-between text-xs text-slate-600">
            <span>{b.label}</span>
            <span className="font-semibold">
              {b.value}
              {showPercent ? ` · ${Math.round((b.value / total) * 100)}%` : ''}
            </span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100">
            <div
              className={clsx('h-full', b.colorClass ?? 'bg-slate-400')}
              style={{ width: `${(b.value / total) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

// Ranked bars normalized against the largest value, with the raw count on the
// right. Used for things like scoreline frequency.
export interface RankedBarItem {
  label: string;
  value: number;
}

export function RankedBars({
  items,
  colorClass = 'bg-indigo-400',
}: {
  items: RankedBarItem[];
  colorClass?: string;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="space-y-2">
      {items.map((l) => (
        <div key={l.label} className="flex items-center gap-2 text-xs">
          <span className="w-10 font-mono font-semibold text-slate-700">{l.label}</span>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
            <div className={clsx('h-full', colorClass)} style={{ width: `${(l.value / max) * 100}%` }} />
          </div>
          <span className="w-8 text-right text-slate-500">{l.value}</span>
        </div>
      ))}
    </div>
  );
}
