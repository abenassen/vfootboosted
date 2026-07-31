import { useEffect, useRef, useState } from 'react';
import clsx from 'clsx';
import { useCompetitionContext } from '../league/CompetitionContext';
import { compColor } from '../league/competitionColors';
import { competitionFormatLabel } from '../league/competitionFormat';

// Custom dropdown (a native <select> can't reliably colour individual options):
// the button shows the CURRENT competition in its accent colour; the open list
// shows EVERY competition as its own colour-coded line, so the colours are distinct
// and match the menu/page accents.
export default function CompetitionSwitcher({ compact }: { compact?: boolean }) {
  const { competitions, selectedCompetitionId, setSelectedCompetitionId } = useCompetitionContext();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    // Dismiss on an outside tap (touchstart, not just mousedown, so it works on a
    // phone) or Escape. Only wired while open, so it costs nothing when closed.
    function onDown(e: Event) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onDown);
    document.addEventListener('touchstart', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('touchstart', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (!competitions.length) {
    return compact ? null : (
      <span className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-400 shadow-sm">
        Nessuna competizione
      </span>
    );
  }

  const idx = Math.max(0, competitions.findIndex((c) => c.competition_id === selectedCompetitionId));
  const cur = competitions[idx];
  const curColor = compColor(idx);
  const label = (c: typeof cur) => `${competitionFormatLabel(c)} · ${c.name}`;

  return (
    <div ref={ref} className={clsx('relative', compact && 'w-full')}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="Selettore competizione"
        className={clsx(
          'flex items-center gap-2 rounded-xl border px-3 py-2 text-sm font-semibold shadow-sm',
          compact ? 'w-full' : 'min-w-[12rem]',
          curColor.border300, curColor.bg50, curColor.text800,
        )}
      >
        <span className={clsx('h-2.5 w-2.5 shrink-0 rounded-full', curColor.dot)} />
        <span className="truncate">{label(cur)}</span>
        <span className="ml-auto text-xs opacity-70">▾</span>
      </button>

      {open ? (
        <div className="absolute z-30 mt-1 w-full min-w-[14rem] overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg">
          {competitions.map((c, i) => {
            const cc = compColor(i);
            const sel = c.competition_id === selectedCompetitionId;
            return (
              <button
                key={c.competition_id}
                type="button"
                onClick={() => {
                  setSelectedCompetitionId(c.competition_id);
                  setOpen(false);
                }}
                className={clsx(
                  'flex min-h-[44px] w-full items-center gap-2 border-l-4 px-3 py-2 text-left text-sm',
                  cc.border600,
                  sel ? cc.bg50 : 'bg-white hover:bg-slate-50',
                )}
              >
                <span className={clsx('h-2.5 w-2.5 shrink-0 rounded-full', cc.dot)} />
                <span className={clsx('truncate', sel ? clsx('font-semibold', cc.text800) : 'text-slate-700')}>
                  {label(c)}
                </span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
