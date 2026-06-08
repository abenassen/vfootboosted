import clsx from 'clsx';

// Neutral standings row. Both the simulation and the real league map their own
// data into this shape.
export interface StandingRowVM {
  key: string;
  rank: number;
  name: string;
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
}

export function StandingsTable({
  rows,
  promoCount = 0,
  selectedKey,
  onRowClick,
}: {
  rows: StandingRowVM[];
  promoCount?: number;
  selectedKey?: string | null;
  onRowClick?: (row: StandingRowVM) => void;
}) {
  const showAvg = rows.some((r) => typeof r.avgScore === 'number');
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
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
                'border-t border-slate-100',
                onRowClick && 'cursor-pointer hover:bg-slate-50',
                (s.highlight || s.key === selectedKey) && 'bg-amber-50',
              )}
            >
              <td className="py-2 pr-2">
                <span
                  className={clsx(
                    'inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold',
                    promoCount > 0 && s.rank <= promoCount
                      ? 'bg-green-100 text-green-800'
                      : 'bg-slate-100 text-slate-600',
                  )}
                >
                  {s.rank}
                </span>
              </td>
              <td className="pr-2 font-semibold text-slate-900">{s.name}</td>
              <td className="px-1 text-center text-slate-600">{s.played}</td>
              <td className="px-1 text-center text-slate-600">{s.wins}</td>
              <td className="px-1 text-center text-slate-600">{s.draws}</td>
              <td className="px-1 text-center text-slate-600">{s.losses}</td>
              <td className="px-1 text-center text-slate-600">{s.goalsFor}</td>
              <td className="px-1 text-center text-slate-600">{s.goalsAgainst}</td>
              <td className="px-1 text-center text-slate-600">
                {s.goalDiff > 0 ? `+${s.goalDiff}` : s.goalDiff}
              </td>
              {showAvg ? (
                <td className="px-1 text-center text-slate-500">
                  {typeof s.avgScore === 'number' ? s.avgScore.toFixed(1) : '—'}
                </td>
              ) : null}
              <td className="px-1 text-center font-bold text-slate-900">{s.points}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
