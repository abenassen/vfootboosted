import clsx from 'clsx';
import type { ReactNode } from 'react';

export type MatchSide = 'home' | 'away';
export type MatchResult = MatchSide | 'draw';

export interface MatchHeaderVM {
  homeName: string;
  awayName: string;
  homeGoals: number;
  awayGoals: number;
  result: MatchResult;
  homeSubtitle?: string;
  awaySubtitle?: string;
}

// Team vs team score banner. `eyebrow`, `action` and `footer` are neutral
// slots so the host page controls surrounding chrome (round labels, back
// links, margin badges, etc.).
export function MatchScoreHeader({
  header,
  eyebrow,
  action,
  footer,
}: {
  header: MatchHeaderVM;
  eyebrow?: ReactNode;
  action?: ReactNode;
  footer?: ReactNode;
}) {
  const homeWin = header.result === 'home';
  const awayWin = header.result === 'away';
  return (
    <div>
      {eyebrow || action ? (
        <div className="flex items-center justify-between">
          <div className="min-w-0">{eyebrow}</div>
          {action}
        </div>
      ) : null}
      <div className="mt-3 flex items-center justify-center gap-4 sm:gap-8">
        <div className="flex-1 text-right">
          <div className={clsx('text-lg', homeWin ? 'font-black text-slate-900' : 'font-semibold text-slate-600')}>
            {header.homeName}
          </div>
          {header.homeSubtitle ? <div className="text-xs text-slate-400">{header.homeSubtitle}</div> : null}
        </div>
        <div className="flex items-center gap-2 rounded-2xl bg-slate-900 px-4 py-2 font-mono text-2xl font-black text-white">
          <span className={homeWin ? 'text-green-400' : ''}>{header.homeGoals}</span>
          <span className="text-slate-500">-</span>
          <span className={awayWin ? 'text-green-400' : ''}>{header.awayGoals}</span>
        </div>
        <div className="flex-1">
          <div className={clsx('text-lg', awayWin ? 'font-black text-slate-900' : 'font-semibold text-slate-600')}>
            {header.awayName}
          </div>
          {header.awaySubtitle ? <div className="text-xs text-slate-400">{header.awaySubtitle}</div> : null}
        </div>
      </div>
      {footer ? <div className="mt-3 flex justify-center">{footer}</div> : null}
    </div>
  );
}
