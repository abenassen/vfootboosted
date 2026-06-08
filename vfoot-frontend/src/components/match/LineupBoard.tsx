import clsx from 'clsx';
import { SectionTitle } from '../ui';
import { toMinutes } from '../../utils/vfoot';

const MATCH_SECONDS = 5400; // 90'; the real end can be slightly later (added time)

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
  role: string | null; // GK | DEF | MID | ATT (slot's dominant contributor)
  zones: string[]; // zone keys to light up on the pitch map (combined slot)
  share: number; // 0..1 relative influence within the team (starter + subs)
  avgCol: number | null; // spatial centre of gravity, for fine ordering
  events: LineupSubEvent[];
}

const ROLE_BAND: Record<string, { label: string; chip: string }> = {
  GK: { label: 'POR', chip: 'bg-amber-500' },
  DEF: { label: 'DIF', chip: 'bg-blue-500' },
  MID: { label: 'CEN', chip: 'bg-emerald-500' },
  ATT: { label: 'ATT', chip: 'bg-orange-500' },
};
const ROLE_RANK: Record<string, number> = { GK: 0, DEF: 1, MID: 2, ATT: 3 };

function tendencyBand(role: string | null): { label: string; chip: string } {
  return (role && ROLE_BAND[role]) || { label: '—', chip: 'bg-slate-300' };
}

// Full lineup list. Clicking a player lights up their zones on the pitch map
// (via onSelectPlayer); substituted players expand to show who covered them
// and when. No zone codes are shown — the spatial map carries that.
export function LineupColumn({
  teamName,
  side,
  players,
  gkRating,
  selectedPlayerId,
  onSelectPlayer,
}: {
  teamName: string;
  side: 'home' | 'away';
  players: LineupPlayerVM[];
  gkRating?: number | null;
  selectedPlayerId?: string | number | null;
  onSelectPlayer?: (id: string | number | null) => void;
}) {
  const max = Math.max(0.0001, ...players.map((p) => p.share));
  const bar = side === 'home' ? 'bg-green-500' : 'bg-sky-500';
  const accent = side === 'home' ? 'text-green-700' : 'text-sky-700';
  // Goalkeeper → defenders → midfielders → attackers; within a role, by spatial
  // centre of gravity. Slots with no role/action go last.
  const ordered = [...players].sort((a, b) => {
    const ra = a.role ? ROLE_RANK[a.role] ?? 9 : 9;
    const rb = b.role ? ROLE_RANK[b.role] ?? 9 : 9;
    if (ra !== rb) return ra - rb;
    return (a.avgCol ?? 99) - (b.avgCol ?? 99);
  });

  return (
    <div>
      <SectionTitle>{teamName}</SectionTitle>
      <div className="mt-2 space-y-1">
        {ordered.map((p) => {
          const selected = p.id === selectedPlayerId;
          const hasGaps = p.events.length > 0;
          const sentOff = p.events.some((e) => e.kind === 'disciplinary');
          const band = tendencyBand(p.role);
          // Both starter and the substitute(s) who covered the slot, on one line
          // (no hard hierarchy: the reserve sometimes matters more, or the
          // starter never played).
          const slotNames = [p.name, ...p.events.filter((e) => e.kind === 'covered' && e.bench).map((e) => e.bench!)];
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
                      {slotNames.map((name, i) => (
                        <span key={i}>
                          {i > 0 ? <span className="text-slate-400"> / </span> : null}
                          {name}
                        </span>
                      ))}
                    </span>
                  </div>
                  {p.role === 'GK' ? (
                    <div className="mt-0.5 text-[11px] text-slate-500">
                      {gkRating == null ? (
                        'portiere'
                      ) : (
                        <>
                          gol evitati{' '}
                          <b className={gkRating >= 0 ? 'text-green-600' : 'text-red-600'}>
                            {gkRating >= 0 ? '+' : ''}
                            {gkRating.toFixed(2)}
                          </b>
                        </>
                      )}
                    </div>
                  ) : (
                    <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-slate-100">
                      <div className={clsx('h-full', bar)} style={{ width: `${(p.share / max) * 100}%` }} />
                    </div>
                  )}
                </button>
                {hasGaps ? <span className="shrink-0 text-[10px] text-amber-600" title="Slot con sostituzioni">⇄</span> : null}
              </div>
              {hasGaps ? (
                <div className="mt-1.5 space-y-1 border-t border-slate-100 pt-1.5 text-[11px] text-slate-600">
                  <SlotTimeline events={p.events} side={side} />
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

// Minute timeline for a slot: team colour = starter on the pitch, grey = covered
// by a substitute, amber/red = uncovered / sent off. Makes the respective
// minutes of starter and substitute visible at a glance.
function SlotTimeline({ events, side }: { events: LineupSubEvent[]; side: 'home' | 'away' }) {
  const matchEnd = Math.max(MATCH_SECONDS, ...events.map((e) => e.gapEnd));
  const baseColor = side === 'home' ? 'bg-green-500' : 'bg-sky-500';
  return (
    <div className="flex items-center gap-1 text-[9px] text-slate-400">
      <span>0'</span>
      <div
        className={clsx('relative h-2 flex-1 overflow-hidden rounded-full', baseColor)}
        title="colore squadra = titolare in campo · grigio = subentro · ambra = scoperto"
      >
        {events.map((e, i) => {
          const left = (e.gapStart / matchEnd) * 100;
          const width = ((e.gapEnd - e.gapStart) / matchEnd) * 100;
          const coveredFrac =
            e.kind === 'covered' && e.coveredSeconds
              ? Math.min(1, e.coveredSeconds / Math.max(1, e.gapEnd - e.gapStart))
              : 0;
          return (
            <div key={i} className="absolute top-0 h-full" style={{ left: `${left}%`, width: `${width}%` }}>
              <div className={clsx('h-full w-full', e.kind === 'disciplinary' ? 'bg-red-400' : 'bg-amber-300')} />
              {coveredFrac > 0 ? (
                <div className="absolute left-0 top-0 h-full bg-slate-400" style={{ width: `${coveredFrac * 100}%` }} />
              ) : null}
            </div>
          );
        })}
      </div>
      <span>{toMinutes(matchEnd)}</span>
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
