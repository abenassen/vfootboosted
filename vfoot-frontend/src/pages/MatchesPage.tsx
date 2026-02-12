import { Link } from 'react-router-dom';
import { Card, SectionTitle, Badge, Button } from '../components/ui';
import { getMatches } from '../mock/api';
import { useAsync } from '../utils/useAsync';

export default function MatchesPage() {
  const { data, loading, error } = useAsync(getMatches, []);

  if (loading) return <div className="text-sm text-slate-500">Caricamento match…</div>;
  if (error || !data) return <div className="text-sm text-red-600">Errore: {error?.message}</div>;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <SectionTitle>Giornata 24</SectionTitle>
        <div className="mt-3 space-y-3">
          {data.map((m) => (
            <div key={m.match_id} className="flex items-center justify-between gap-4 rounded-xl border border-slate-100 bg-slate-50 px-3 py-3">
              <div>
                <div className="font-semibold">{m.home.name} <span className="text-slate-400">vs</span> {m.away.name}</div>
                <div className="mt-1 text-sm text-slate-500">
                  {m.score ? `${m.score.home_total.toFixed(1)} – ${m.score.away_total.toFixed(1)}` : 'In arrivo'}
                  <span className="mx-2">·</span>
                  {m.status === 'finished' ? <Badge tone="green">finito</Badge> : m.status === 'live' ? <Badge tone="amber">live</Badge> : <Badge tone="slate">scheduled</Badge>}
                </div>
              </div>
              <Link to={`/matches/${m.match_id}`}><Button variant="secondary" size="sm">Dettagli</Button></Link>
            </div>
          ))}
        </div>
      </Card>

      <div className="text-xs text-slate-500">Nota: dati mock (in futuro arrivano dal backend).</div>
    </div>
  );
}
