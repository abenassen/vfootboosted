import { Link } from 'react-router-dom';
import { Card, SectionTitle, Button, Badge } from '../components/ui';
import { useAsync } from '../utils/useAsync';
import { getLineupContext } from '../mock/api';

export default function SquadPage() {
  const { data, loading, error } = useAsync(getLineupContext, []);

  if (loading) {
    return <div className="text-sm text-slate-500">Caricamento rosa…</div>;
  }
  if (error || !data) {
    return <div className="text-sm text-red-600">Errore: {error?.message ?? '...'}</div>;
  }

  const starters = new Set(data.saved_lineup.starter_player_ids);

  return (
    <div className="space-y-4">
      <Card className="p-4 flex items-center justify-between gap-4">
        <div>
          <SectionTitle>Squadra</SectionTitle>
          <div className="mt-1 text-xl font-black">{data.squad.name}</div>
          <div className="text-sm text-slate-500">Rosa: {data.roster.length} giocatori</div>
        </div>
        <Link to="/squad/formation"><Button>Modifica formazione</Button></Link>
      </Card>

      <Card className="p-4">
        <SectionTitle>Rosa</SectionTitle>
        <div className="mt-3 divide-y">
          {data.roster.map((p) => {
            const isStarter = starters.has(p.player_id);
            const risk = p.status.minutes_expectation.label === 'low';
            return (
              <div key={p.player_id} className="py-3 flex items-center justify-between gap-3">
                <div>
                  <div className="font-semibold">{p.name}</div>
                  <div className="text-xs text-slate-500">{p.real_team} · €{p.price}</div>
                </div>
                <div className="flex items-center gap-2">
                  {risk ? <Badge tone="amber">minuti bassi</Badge> : null}
                  {isStarter ? <Badge tone="green">titolare</Badge> : <Badge tone="slate">rosa</Badge>}
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
