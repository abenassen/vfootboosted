import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getTeamLineup } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type { TeamLineupContext } from '../types/lineup';

export default function MarketPage() {
  const { selectedLeagueId, selectedLeague } = useLeagueContext();
  const [ctx, setCtx] = useState<TeamLineupContext | null>(null);

  useEffect(() => {
    if (!selectedLeagueId) {
      setCtx(null);
      return;
    }
    void getTeamLineup(selectedLeagueId).then(setCtx).catch(() => setCtx(null));
  }, [selectedLeagueId]);

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega per vedere il mercato.</div>;

  const open = !!selectedLeague?.market_open;
  const value = ctx ? ctx.roster.reduce((s, p) => s + p.price, 0) : null;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <SectionTitle>Mercato</SectionTitle>
            <div className="mt-1 text-sm text-slate-600">
              {open ? 'Il mercato è aperto: puoi acquisire giocatori tramite l’asta.' : 'Il mercato è chiuso.'}
            </div>
          </div>
          <Badge tone={open ? 'green' : 'slate'}>{open ? 'aperto' : 'chiuso'}</Badge>
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>La tua rosa</SectionTitle>
        {ctx ? (
          <div className="mt-2 text-sm text-slate-700">
            <b>{ctx.team.name}</b> · {ctx.roster.length} giocatori · valore complessivo <b>{value}</b>
          </div>
        ) : (
          <div className="mt-2 text-sm text-slate-500">Nessuna squadra associata in questa lega.</div>
        )}
        <Link to="/squad" className="mt-3 inline-flex">
          <Button variant="secondary" size="sm">
            Vedi rosa
          </Button>
        </Link>
      </Card>

      <Card className="p-4">
        <SectionTitle>Asta</SectionTitle>
        <div className="mt-2 text-sm text-slate-600">
          Acquisizioni e scambi si svolgono tramite l’<b>asta</b> della lega: chiamata del giocatore,
          rilanci in diretta e aggiudicazione. Tutti i partecipanti seguono l’asta live dalla sala.
        </div>
        <Link to="/auction" className="mt-3 inline-flex">
          <Button>Entra nella sala asta</Button>
        </Link>
      </Card>
    </div>
  );
}
