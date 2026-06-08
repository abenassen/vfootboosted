import { Link } from 'react-router-dom';
import { Card, SectionTitle, Button, Badge } from '../components/ui';
import { useAsync } from '../utils/useAsync';
import { getTeamLineup } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import type { PlayerRole } from '../types/lineup';

const ROLE_LABEL: Record<PlayerRole, string> = { GK: 'POR', DEF: 'DIF', MID: 'CEN', ATT: 'ATT' };
const ROLE_CHIP: Record<PlayerRole, string> = {
  GK: 'bg-amber-500',
  DEF: 'bg-blue-500',
  MID: 'bg-emerald-500',
  ATT: 'bg-orange-500',
};
const ROLE_ORDER: Record<PlayerRole, number> = { GK: 0, DEF: 1, MID: 2, ATT: 3 };

export default function SquadPage() {
  const { selectedLeagueId } = useLeagueContext();
  const { data, loading, error } = useAsync(
    () => (selectedLeagueId ? getTeamLineup(selectedLeagueId) : Promise.reject(new Error('Nessuna lega selezionata'))),
    [selectedLeagueId],
  );

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega per vedere la rosa.</div>;
  if (loading) return <div className="text-sm text-slate-500">Caricamento rosa…</div>;
  if (error || !data) return <div className="text-sm text-red-600">Errore: {error?.message ?? '…'}</div>;

  const roster = [...data.roster].sort((a, b) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role] || b.price - a.price);

  return (
    <div className="space-y-4">
      <Card className="flex items-center justify-between gap-4 p-4">
        <div>
          <SectionTitle>Squadra</SectionTitle>
          <div className="mt-1 text-xl font-black">{data.team.name}</div>
          <div className="text-sm text-slate-500">
            Rosa: {data.roster.length} giocatori · valore {data.roster.reduce((s, p) => s + p.price, 0)}
          </div>
        </div>
        <Link to="/squad/formation">
          <Button>Modifica formazione</Button>
        </Link>
      </Card>

      <Card className="p-4">
        <SectionTitle>Rosa</SectionTitle>
        <div className="mt-1 text-[11px] text-slate-400">
          Ruolo e tendenza dedotti da dove il giocatore agisce in campo; minuti dalla storia stagionale.
        </div>
        <div className="mt-2 divide-y">
          {roster.map((p) => (
            <div key={p.player_id} className="flex items-center justify-between gap-3 py-2.5">
              <div className="flex min-w-0 items-center gap-2">
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ${ROLE_CHIP[p.role]}`}>
                  {ROLE_LABEL[p.role]}
                </span>
                <div className="min-w-0">
                  <div className="truncate font-semibold text-slate-900">{p.name}</div>
                  <div className="text-xs text-slate-500">
                    €{p.price} · {p.appearances} pres · {p.avg_minutes}′ medi
                  </div>
                </div>
              </div>
              <MinutesBadge label={p.minutes_label} />
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function MinutesBadge({ label }: { label: 'high' | 'medium' | 'low' }) {
  if (label === 'high') return <Badge tone="green">titolare abituale</Badge>;
  if (label === 'medium') return <Badge tone="slate">spesso impiegato</Badge>;
  return <Badge tone="amber">poco impiegato</Badge>;
}
