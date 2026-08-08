import clsx from 'clsx';
import Crest from '../Crest';

// Neutral standings row. Both the simulation and the real league map their own
// data into this shape.
export interface StandingRowVM {
  key: string;
  rank: number;
  name: string;
  /** Opaque crest descriptor. Left undefined by callers that have no crests (the
   *  simulation report), and then no crest column is drawn at all. */
  crest?: string | null;
  played: number;
  wins: number;
  draws: number;
  losses: number;
  goalsFor: number;
  goalsAgainst: number;
  goalDiff: number;
  points: number;
  avgScore?: number;
  highlight?: boolean;
  /** Dentro questi numeri c'è una partita ancora da finire. Non è una proprietà
   *  della tabella ma della RIGA: nella stessa classifica chi ha già giocato ha
   *  un numero fermo e chi è in campo no, e sono due cose diverse da leggere. */
  provisional?: boolean;
}

export function StandingsTable({
  rows,
  /** Positions that WIN something (green) and positions that merely go through
   *  (outlined). Both come from the competition's own prize bands and
   *  qualification rules — it used to be "the top 4", a number from real football
   *  that means nothing in a league whose prizes go to three. */
  prizeRanks,
  qualifyRanks,
  selectedKey,
  onRowClick,
}: {
  rows: StandingRowVM[];
  prizeRanks?: number[];
  qualifyRanks?: number[];
  selectedKey?: string | null;
  onRowClick?: (row: StandingRowVM) => void;
}) {
  const prize = new Set(prizeRanks ?? []);
  const qualify = new Set(qualifyRanks ?? []);
  const showAvg = rows.some((r) => typeof r.avgScore === 'number');
  const showCrest = rows.some((r) => r.crest !== undefined);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-ink-faint">
            <th className="py-2 pr-2">#</th>
            <th className="pr-2">Squadra</th>
            <th className="px-1 text-center">G</th>
            <th className="px-1 text-center">V</th>
            <th className="px-1 text-center">N</th>
            <th className="px-1 text-center">P</th>
            <th className="px-1 text-center">GF</th>
            <th className="px-1 text-center">GS</th>
            <th className="px-1 text-center">DR</th>
            {showAvg ? <th className="px-1 text-center">Media</th> : null}
            <th className="px-1 text-center font-bold">Pt</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr
              key={s.key}
              onClick={onRowClick ? () => onRowClick(s) : undefined}
              className={clsx(
                'border-t border-line',
                onRowClick && 'cursor-pointer hover:bg-surface-2',
                (s.highlight || s.key === selectedKey) && 'bg-brand/10',
              )}
            >
              <td className="py-2 pr-2">
                <span
                  className={clsx(
                    'inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold',
                    prize.has(s.rank)
                      ? 'bg-good-bg text-good'
                      : qualify.has(s.rank)
                        ? 'border border-good/40 bg-surface text-good'
                        : 'bg-surface-2 text-ink-soft',
                  )}
                >
                  {s.rank}
                </span>
              </td>
              <td className="pr-2 font-semibold text-ink">
                <span className="flex items-center gap-2">
                  {showCrest ? <Crest descriptor={s.crest} teamName={s.name} size={22} /> : null}
                  <span className="truncate">{s.name}</span>
                  {s.provisional ? (
                    <span
                      className="inline-block h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-live"
                      title="Partita in corso: questi numeri possono ancora cambiare"
                    />
                  ) : null}
                </span>
              </td>
              <td className="px-1 text-center text-ink-soft">{s.played}</td>
              <td className="px-1 text-center text-ink-soft">{s.wins}</td>
              <td className="px-1 text-center text-ink-soft">{s.draws}</td>
              <td className="px-1 text-center text-ink-soft">{s.losses}</td>
              <td className="px-1 text-center text-ink-soft">{s.goalsFor}</td>
              <td className="px-1 text-center text-ink-soft">{s.goalsAgainst}</td>
              <td className="px-1 text-center text-ink-soft">
                {s.goalDiff > 0 ? `+${s.goalDiff}` : s.goalDiff}
              </td>
              {showAvg ? (
                <td className="px-1 text-center text-ink-faint">
                  {typeof s.avgScore === 'number' ? s.avgScore.toFixed(1) : '—'}
                </td>
              ) : null}
              <td className="px-1 text-center font-bold text-ink">{s.points}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
