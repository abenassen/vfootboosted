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
  /** Non c'è ancora un risultato: al posto dei due numeri va «vs».
   *
   *  Serve prima che la giornata cominci, dove i gol sono zero perché nessuno ha
   *  giocato — e uno 0-0 stampato nella targa nera si legge come un pareggio, non
   *  come «non è successo niente». */
  scoreless?: boolean;
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
          <div className={clsx('text-lg', homeWin ? 'font-black text-ink' : 'font-semibold text-ink-soft')}>
            {header.homeName}
          </div>
          {header.homeSubtitle ? <div className="text-xs text-ink-faint">{header.homeSubtitle}</div> : null}
        </div>
        <div className="flex items-center gap-2 rounded-2xl bg-ink px-4 py-2 font-mono text-2xl font-black text-paper">
          {header.scoreless ? (
            <span className="text-base uppercase tracking-wide opacity-70">vs</span>
          ) : (
            <>
              <span className={homeWin ? 'text-good' : ''}>{header.homeGoals}</span>
              <span className="text-ink-faint">-</span>
              <span className={awayWin ? 'text-good' : ''}>{header.awayGoals}</span>
            </>
          )}
        </div>
        <div className="flex-1">
          <div className={clsx('text-lg', awayWin ? 'font-black text-ink' : 'font-semibold text-ink-soft')}>
            {header.awayName}
          </div>
          {header.awaySubtitle ? <div className="text-xs text-ink-faint">{header.awaySubtitle}</div> : null}
        </div>
      </div>
      {footer ? <div className="mt-3 flex justify-center">{footer}</div> : null}
    </div>
  );
}
