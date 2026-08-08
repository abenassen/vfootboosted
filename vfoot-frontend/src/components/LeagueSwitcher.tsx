import { Link } from 'react-router-dom';
import { Badge } from './ui';
import { useLeagueContext } from '../league/LeagueContext';

export default function LeagueSwitcher({ compact }: { compact?: boolean }) {
  const { leagues, selectedLeagueId, setSelectedLeagueId, loading } = useLeagueContext();

  if (!leagues.length) {
    if (compact) {
      return (
        <Link to="/league-admin" className="rounded-xl border border-line bg-surface px-3 py-2 text-xs font-semibold text-ink-soft shadow-sm">
          Nessuna lega
        </Link>
      );
    }
    return <Badge tone="amber">{loading ? 'Caricamento leghe...' : 'Nessuna lega'}</Badge>;
  }

  // No role badge here any more. It sat between the label and the dropdown of the
  // thing it described, and the role only matters where it is acted on — Le mie
  // leghe already shows amministratore/partecipante per league.
  return (
    <div className={compact ? 'flex w-full items-center gap-2' : 'flex items-center gap-2'}>
      <select
        value={selectedLeagueId ?? ''}
        onChange={(e) => setSelectedLeagueId(e.target.value ? Number(e.target.value) : null)}
        className={
          compact
            ? 'w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm font-semibold text-ink-soft shadow-sm'
            : 'rounded-xl border border-line bg-surface px-3 py-2 text-sm font-semibold text-ink-soft shadow-sm'
        }
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
