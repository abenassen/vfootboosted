import clsx from 'clsx';
import { Badge } from '../ui';
import { featureLabel } from '../../utils/vfoot';
import type { MatchResult } from './MatchScoreHeader';

export interface ZoneContributionVM {
  feature: string;
  swing: number;
}

export interface ZoneDuelVM {
  zoneKey: string;
  winner: MatchResult;
  winnerLabel: string;
  margin: number;
  contributions: ZoneContributionVM[];
}

// List of decisive zone duels with per-zone feature-swing chips. Rows are
// selectable and sync with a ZonePitchGrid via `selectedZone`/`onSelect`.
export function ZoneDuelList({
  zones,
  selectedZone,
  onSelect,
}: {
  zones: ZoneDuelVM[];
  selectedZone?: string | null;
  onSelect?: (zoneKey: string | null) => void;
}) {
  return (
    <div className="space-y-2">
      {zones.map((z) => {
        const selected = selectedZone === z.zoneKey;
        const tone = z.winner === 'home' ? 'green' : z.winner === 'away' ? 'slate' : 'amber';
        return (
          <button
            key={z.zoneKey}
            type="button"
            onClick={onSelect ? () => onSelect(selected ? null : z.zoneKey) : undefined}
            className={clsx(
              'block w-full rounded-xl border bg-slate-50 px-3 py-2 text-left transition',
              selected ? 'border-slate-400 bg-white' : 'border-slate-100',
              onSelect && 'hover:border-slate-300',
            )}
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs font-semibold text-slate-700">{z.zoneKey}</span>
              <div className="flex items-center gap-2">
                <Badge tone={tone}>{z.winnerLabel}</Badge>
                <span className="font-mono text-xs text-slate-500">{z.margin.toFixed(3)}</span>
              </div>
            </div>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {z.contributions.map((c) => (
                <span
                  key={c.feature}
                  className={clsx(
                    'rounded px-1.5 py-0.5 text-[10px] font-medium',
                    c.swing >= 0 ? 'bg-green-100 text-green-800' : 'bg-sky-100 text-sky-800',
                  )}
                >
                  {featureLabel(c.feature)} {c.swing >= 0 ? '+' : ''}
                  {c.swing.toFixed(2)}
                </span>
              ))}
            </div>
          </button>
        );
      })}
    </div>
  );
}
