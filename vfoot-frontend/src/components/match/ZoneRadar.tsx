export interface RadarAxis {
  label: string;
  homeShare: number; // 0..1; away is the complement
}

// PES-style radar comparing the two teams across macro-categories in a zone.
// Each axis is the home/away share (they always sum to 1), so the bigger
// polygon dominates that category.
export function ZoneRadar({
  axes,
  homeName,
  awayName,
  size = 220,
}: {
  axes: RadarAxis[];
  homeName: string;
  awayName: string;
  size?: number;
}) {
  const n = axes.length;
  if (n < 3) return null;
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 30;

  const angle = (i: number) => (i / n) * 2 * Math.PI - Math.PI / 2;
  const point = (i: number, value: number) => {
    const a = angle(i);
    return [cx + r * value * Math.cos(a), cy + r * value * Math.sin(a)] as const;
  };
  const poly = (vals: number[]) => vals.map((v, i) => point(i, v).join(',')).join(' ');

  const homeVals = axes.map((a) => Math.max(0.04, a.homeShare));
  const awayVals = axes.map((a) => Math.max(0.04, 1 - a.homeShare));

  const rings = [0.25, 0.5, 0.75, 1];

  return (
    <div className="flex flex-col items-center px-6">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="overflow-visible">
        {/* grid rings */}
        {rings.map((ring) => (
          <polygon
            key={ring}
            points={poly(axes.map(() => ring))}
            fill="none"
            stroke="#e2e8f0"
            strokeWidth={1}
          />
        ))}
        {/* spokes */}
        {axes.map((_, i) => {
          const [x, y] = point(i, 1);
          return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="#e2e8f0" strokeWidth={1} />;
        })}
        {/* away polygon (sky) */}
        <polygon points={poly(awayVals)} fill="rgba(14,165,233,0.25)" stroke="#0ea5e9" strokeWidth={2} />
        {/* home polygon (green) */}
        <polygon points={poly(homeVals)} fill="rgba(34,197,94,0.25)" stroke="#22c55e" strokeWidth={2} />
        {/* labels */}
        {axes.map((ax, i) => {
          const [x, y] = point(i, 1.18);
          return (
            <text
              key={ax.label}
              x={x}
              y={y}
              textAnchor="middle"
              dominantBaseline="middle"
              className="fill-slate-500"
              style={{ fontSize: 10, fontWeight: 600 }}
            >
              {ax.label}
            </text>
          );
        })}
      </svg>
      <div className="mt-1 flex gap-3 text-[11px] text-slate-500">
        <span className="flex items-center gap-1">
          <span className="h-2.5 w-2.5 rounded-sm bg-green-500" /> {homeName}
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2.5 w-2.5 rounded-sm bg-sky-500" /> {awayName}
        </span>
      </div>
    </div>
  );
}
