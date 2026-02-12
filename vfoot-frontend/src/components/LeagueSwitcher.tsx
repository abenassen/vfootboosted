import { useState } from 'react';
import { Badge } from './ui';

const leagues = [
  { id: 'L1', name: 'Lega Friends', matchday: 'G24' },
  { id: 'L2', name: 'Lega Office', matchday: 'G18' }
];

export default function LeagueSwitcher({ compact }: { compact?: boolean }) {
  const [activeId, setActiveId] = useState(leagues[0].id);
  const active = leagues.find((l) => l.id === activeId) ?? leagues[0];

  return (
    <div className="flex items-center gap-2">
      {!compact && <Badge tone="slate">{active.matchday}</Badge>}
      <select
        value={activeId}
        onChange={(e) => setActiveId(e.target.value)}
        className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm"
        aria-label="Selettore lega"
      >
        {leagues.map((l) => (
          <option key={l.id} value={l.id}>
            {l.name}
          </option>
        ))}
      </select>
    </div>
  );
}
