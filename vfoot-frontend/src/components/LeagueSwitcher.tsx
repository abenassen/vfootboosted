import { Link } from 'react-router-dom';
import { Badge } from './ui';
import { useLeagueContext } from '../league/LeagueContext';

export default function LeagueSwitcher({ compact }: { compact?: boolean }) {
  const { leagues, selectedLeagueId, selectedLeague, setSelectedLeagueId, loading } = useLeagueContext();

  if (!leagues.length) {
    if (compact) {
      return (
        <Link to="/league-admin" className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm">
          Nessuna lega
        </Link>
      );
    }
    return <Badge tone="amber">{loading ? 'Caricamento leghe...' : 'Nessuna lega'}</Badge>;
  }

  return (
    <div className="flex items-center gap-2">
      {!compact && selectedLeague ? <Badge tone="slate">{selectedLeague.role}</Badge> : null}
      <select
        value={selectedLeagueId ?? ''}
        onChange={(e) => setSelectedLeagueId(e.target.value ? Number(e.target.value) : null)}
        className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm"
        aria-label="Selettore lega"
      >
        {leagues.map((l) => (
          <option key={l.league_id} value={l.league_id}>
            {l.name}
          </option>
        ))}
      </select>
    </div>
  );
}
