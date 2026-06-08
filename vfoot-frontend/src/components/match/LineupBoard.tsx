import clsx from 'clsx';
import { useState } from 'react';
import { SectionTitle } from '../ui';
import { toMinutes } from '../../utils/vfoot';

export type SubEventKind = 'covered' | 'uncovered' | 'disciplinary';
export type GapKind = 'pre_entry' | 'post_exit' | 'mid' | 'absent';

export interface LineupSubEvent {
  kind: SubEventKind;
  gapKind: GapKind;
  gapStart: number; // seconds
  gapEnd: number; // seconds
  bench?: string;
  coveredSeconds?: number;
  uncoveredSeconds: number;
}

export interface LineupPlayerVM {
  id: string | number;
  name: string;
  isGoalkeeper: boolean;
  zones: string[]; // zone keys to light up on the pitch map (combined slot)
  share: number; // 0..1 relative influence within the team (starter + subs)
  avgCol: number | null; // spatial tendency: 0 = defense ... 4 = attack
  events: LineupSubEvent[];
}

// Spatial tendency band. The goalkeeper has its own identity; outfield bands are
// inferred from where the slot acted (no fixed roles).
function tendencyBand(avgCol: number | null, isGoalkeeper: boolean): { label: string; chip: string } {
  if (isGoalkeeper) return { label: 'POR', chip: 'bg-amber-500' };
  if (avgCol == null) return { label: '—', chip: 'bg-slate-300' };
  if (avgCol < 1.0) return { label: 'DIF', chip: 'bg-blue-500' };
  if (avgCol < 2.5) return { label: 'CEN', chip: 'bg-emerald-500' };
  return { label: 'ATT', chip: 'bg-orange-500' };
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
  // Goalkeeper first, then most defensive to most advanced (no fixed roles:
  // inferred from where the slot acted). Slots with no action go last.
  const ordered = [...players].sort((a, b) => {
    if (a.isGoalkeeper !== b.isGoalkeeper) return a.isGoalkeeper ? -1 : 1;
    return (a.avgCol ?? 99) - (b.avgCol ?? 99);
  });

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
        {ordered.map((p) => {
          const selected = p.id === selectedPlayerId;
          const isOpen = expanded.has(p.id);
          const hasGaps = p.events.length > 0;
          const sentOff = p.events.some((e) => e.kind === 'disciplinary');
          const band = tendencyBand(p.avgCol, p.isGoalkeeper);
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
                    <span
                      className={clsx('rounded px-1 py-0.5 text-[9px] font-bold leading-none text-white', band.chip)}
                      title="Tendenza spaziale (difesa→attacco)"
                    >
                      {band.label}
                    </span>
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
                <div className="mt-1.5 space-y-1 border-t border-slate-100 pt-1.5 text-[11px] text-slate-600">
                  {p.events.map((e, i) => (
                    <EventLine key={i} e={e} />
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

function EventLine({ e }: { e: LineupSubEvent }) {
  // Headline describing what happened to the starter over time.
  let head: string;
  if (e.kind === 'disciplinary') {
    head = `🟥 espulso al ${toMinutes(e.gapStart)}`;
  } else if (e.gapKind === 'absent') {
    head = 'non sceso in campo';
  } else if (e.gapKind === 'pre_entry') {
    head = `entrato in campo al ${toMinutes(e.gapEnd)}`;
  } else if (e.gapKind === 'post_exit') {
    head = `uscito al ${toMinutes(e.gapStart)}`;
  } else {
    head = `fuori ${toMinutes(e.gapStart)}–${toMinutes(e.gapEnd)}`;
  }

  const coverVerb =
    e.gapKind === 'pre_entry' ? 'prima coperto da' : e.gapKind === 'absent' ? 'coperto da' : 'poi coperto da';
  const showUncovered = e.uncoveredSeconds >= 60;

  return (
    <div>
      <span className="text-slate-700">{head}</span>
      {e.kind === 'covered' && e.bench ? (
        <span className="text-slate-500">
          {' '}· {coverVerb} <b className="text-slate-700">{e.bench}</b>{' '}
          <span className="text-green-600">({toMinutes(e.coveredSeconds)})</span>
          {showUncovered ? <span className="text-amber-600"> · {toMinutes(e.uncoveredSeconds)} scoperti</span> : null}
        </span>
      ) : e.kind === 'disciplinary' ? (
        <span className="text-red-600"> · non sostituibile</span>
      ) : (
        <span className="text-amber-600"> · {toMinutes(e.gapEnd - e.gapStart)} scoperti, nessun subentro</span>
      )}
    </div>
  );
}
