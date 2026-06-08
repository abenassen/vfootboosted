import clsx from 'clsx';
import { useState } from 'react';
import { SectionTitle } from '../ui';
import { toMinutes } from '../../utils/vfoot';

export type SubEventKind = 'covered' | 'uncovered' | 'disciplinary';

export interface LineupSubEvent {
  kind: SubEventKind;
  gapStart: number; // seconds
  gapEnd: number; // seconds
  bench?: string;
  coveredSeconds?: number;
}

export interface LineupPlayerVM {
  id: string | number;
  name: string;
  zones: string[]; // zone keys to light up on the pitch map
  share: number; // 0..1 relative influence within the team
  events: LineupSubEvent[];
}

// Full lineup list. Clicking a player lights up their zones on the pitch map
// (via onSelectPlayer); substituted players expand to show who covered them
// and when. No zone codes are shown — the spatial map carries that.
export function LineupColumn({
  teamName,
  side,
  players,
  selectedPlayerId,
  onSelectPlayer,
}: {
  teamName: string;
  side: 'home' | 'away';
  players: LineupPlayerVM[];
  selectedPlayerId?: string | number | null;
  onSelectPlayer?: (id: string | number | null) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string | number>>(new Set());
  const max = Math.max(0.0001, ...players.map((p) => p.share));
  const bar = side === 'home' ? 'bg-green-500' : 'bg-sky-500';
  const accent = side === 'home' ? 'text-green-700' : 'text-sky-700';

  const toggle = (id: string | number) =>
    setExpanded((cur) => {
      const next = new Set(cur);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  return (
    <div>
      <SectionTitle>{teamName}</SectionTitle>
      <div className="mt-2 space-y-1">
        {players.map((p) => {
          const selected = p.id === selectedPlayerId;
          const isOpen = expanded.has(p.id);
          const hasGaps = p.events.length > 0;
          const sentOff = p.events.some((e) => e.kind === 'disciplinary');
          return (
            <div
              key={p.id}
              className={clsx(
                'rounded-lg border px-2 py-1.5 transition',
                selected ? 'border-slate-400 bg-slate-50' : 'border-transparent hover:bg-slate-50',
              )}
            >
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={onSelectPlayer ? () => onSelectPlayer(selected ? null : p.id) : undefined}
                  className="min-w-0 flex-1 text-left"
                  title="Mostra le zone del giocatore sulla mappa"
                >
                  <div className="flex items-center gap-1.5">
                    {sentOff ? <span title="Espulso">🟥</span> : null}
                    <span className={clsx('truncate text-sm', selected ? `font-semibold ${accent}` : 'text-slate-800')}>
                      {p.name}
                    </span>
                  </div>
                  <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-slate-100">
                    <div className={clsx('h-full', bar)} style={{ width: `${(p.share / max) * 100}%` }} />
                  </div>
                </button>
                {hasGaps ? (
                  <button
                    type="button"
                    onClick={() => toggle(p.id)}
                    className={clsx(
                      'shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold',
                      sentOff ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700',
                    )}
                    title="Dettaglio sostituzione"
                  >
                    ⇄ {isOpen ? '▲' : '▼'}
                  </button>
                ) : null}
              </div>
              {hasGaps && isOpen ? (
                <div className="mt-1.5 space-y-0.5 border-t border-slate-100 pt-1.5 text-[11px] text-slate-600">
                  {p.events.map((e, i) => (
                    <div key={i}>
                      <span className="text-slate-400">
                        out {toMinutes(e.gapStart)}–{toMinutes(e.gapEnd)}
                      </span>{' '}
                      {e.kind === 'covered' && e.bench ? (
                        <>
                          → <b>{e.bench}</b> <span className="text-green-600">({toMinutes(e.coveredSeconds)})</span>
                        </>
                      ) : e.kind === 'disciplinary' ? (
                        <span className="text-red-600">espulso · non sostituibile</span>
                      ) : (
                        <span className="text-amber-600">scoperto · nessun subentro</span>
                      )}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
