export interface MacroContributionVM {
  label: string;
  net: number; // >0 favours home (green), <0 favours away (sky); sums to the margin
}

// Per-macro signed contribution to the zone margin, as diverging bars (home left
// / away right). Faithful: the bars sum to the zone result, so it's clear WHICH
// category decided it — unlike an equal-axis volume radar.
export function MacroContributions({
  items,
  homeName,
  awayName,
}: {
  items: MacroContributionVM[];
  homeName: string;
  awayName: string;
}) {
  const maxAbs = Math.max(0.0001, ...items.map((m) => Math.abs(m.net)));
  const ordered = [...items].sort((a, b) => Math.abs(b.net) - Math.abs(a.net));
  return (
    <div>
      <div className="flex items-center justify-between text-[11px] font-semibold">
        <span className="text-red-600">◄ {homeName}</span>
        <span className="text-blue-700">{awayName} ►</span>
      </div>
      <div className="mt-1.5 space-y-1.5">
        {ordered.map((m) => {
          const frac = Math.abs(m.net) / maxAbs;
          const home = m.net > 0;
          return (
            <div key={m.label} className="flex items-center gap-2 text-[11px]" title={`${m.label}: ${m.net.toFixed(3)}`}>
              <span className="w-16 shrink-0 text-slate-600">{m.label}</span>
              <div className="flex flex-1 items-center">
                <div className="flex h-2.5 flex-1 justify-end overflow-hidden rounded-l-full bg-slate-100">
                  {home ? <div className="h-full bg-red-500" style={{ width: `${frac * 100}%` }} /> : null}
                </div>
                <div className="h-3 w-px bg-slate-300" />
                <div className="flex h-2.5 flex-1 overflow-hidden rounded-r-full bg-slate-100">
                  {!home ? <div className="h-full bg-blue-600" style={{ width: `${frac * 100}%` }} /> : null}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
