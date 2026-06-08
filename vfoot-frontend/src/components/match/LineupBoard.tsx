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
  benchPositive?: boolean; // did the substitute help (true) or hurt (false)?
  coveredSeconds?: number;
  uncoveredSeconds: number;
}

export interface LineupPlayerVM {
  id: string | number;
  name: string;
  role: string | null; // GK | DEF | MID | ATT (slot's dominant contributor)
  zones: string[]; // zone keys to light up on the pitch map (combined slot)
  relevance: number; // 0..1 magnitude of the slot's impact (bar thickness)
  starterPositive: boolean; // did the nominal starter help (true) or hurt (false)?
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
                    <SlotBar player={p} />
                  )}
                </button>
                {hasGaps ? <span className="shrink-0 text-[10px] text-amber-600" title="Slot con sostituzioni">⇄</span> : null}
              </div>
              {hasGaps ? (
                <div className="mt-1 space-y-0.5 text-[11px] text-slate-600">
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

const SEGMENT_COLOR: Record<'pos' | 'neg' | 'unc', string> = {
  pos: 'bg-emerald-500',
  neg: 'bg-rose-500',
  unc: 'bg-slate-200',
};

// One bar per outfield slot: THICKNESS = the slot's impact (relevance), the
// horizontal segments = the minutes each occupant played (left→right over the
// match), coloured by whether they helped (green) or hurt (red); grey = the slot
// was uncovered. Replaces the two separate bars.
function SlotBar({ player }: { player: LineupPlayerVM }) {
  const matchEnd = Math.max(MATCH_SECONDS, ...player.events.map((e) => e.gapEnd), 1);
  const height = 2 + Math.round(8 * Math.min(1, player.relevance)); // 2..10 px
  const starterKind: 'pos' | 'neg' = player.starterPositive ? 'pos' : 'neg';

  const segments: { w: number; kind: 'pos' | 'neg' | 'unc' }[] = [];
  // Substitution moments (occupant changes) marked with a vertical tick.
  const ticks: number[] = [];
  let cursor = 0;
  const mark = (seconds: number) => {
    if (seconds > 0 && seconds < matchEnd) ticks.push((seconds / matchEnd) * 100);
  };
  for (const g of [...player.events].sort((a, b) => a.gapStart - b.gapStart)) {
    if (g.gapStart > cursor) segments.push({ w: g.gapStart - cursor, kind: starterKind });
    mark(g.gapStart);
    const gapLen = g.gapEnd - g.gapStart;
    if (g.kind === 'covered' && g.coveredSeconds) {
      const covered = Math.min(g.coveredSeconds, gapLen);
      segments.push({ w: covered, kind: g.benchPositive ? 'pos' : 'neg' });
      if (gapLen - covered > 0) {
        segments.push({ w: gapLen - covered, kind: 'unc' });
        mark(g.gapStart + covered);
      }
    } else {
      segments.push({ w: gapLen, kind: 'unc' });
    }
    cursor = Math.max(cursor, g.gapEnd);
    mark(cursor);
  }
  if (cursor < matchEnd) segments.push({ w: matchEnd - cursor, kind: starterKind });

  return (
    <div
      className="relative mt-1 w-full"
      style={{ height: 12 }}
      title="spessore = impatto · verde = positivo · rosso = negativo · grigio = scoperto · tacca = sostituzione"
    >
      <div
        className="absolute inset-x-0 top-1/2 flex -translate-y-1/2 items-stretch overflow-hidden rounded-full bg-slate-100"
        style={{ height }}
      >
        {segments.map((s, i) => (
          <div key={i} className={SEGMENT_COLOR[s.kind]} style={{ width: `${(s.w / matchEnd) * 100}%` }} />
        ))}
      </div>
      {ticks.map((pct, i) => (
        <div key={i} className="absolute top-0 h-full w-px -translate-x-1/2 bg-slate-700" style={{ left: `${pct}%` }} />
      ))}
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
