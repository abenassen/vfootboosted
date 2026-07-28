import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getActiveAuction, getTeamLineup } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type { TeamLineupContext } from '../types/lineup';
import type { ActiveAuctionInfo } from '../types/league';

export default function MarketPage() {
  const { selectedLeagueId, selectedLeague } = useLeagueContext();
  const [ctx, setCtx] = useState<TeamLineupContext | null>(null);
  const [auction, setAuction] = useState<ActiveAuctionInfo | null>(null);

  useEffect(() => {
    if (!selectedLeagueId) {
      setCtx(null);
      setAuction(null);
      return;
    }
    void getTeamLineup(selectedLeagueId).then(setCtx).catch(() => setCtx(null));
    void getActiveAuction(selectedLeagueId).then(setAuction).catch(() => setAuction(null));
  }, [selectedLeagueId]);

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega per vedere il mercato.</div>;

  const open = !!selectedLeague?.market_open;
  const value = ctx ? ctx.roster.reduce((s, p) => s + p.price, 0) : null;
  // The auction (sala asta) exists only in classic mode. We read it from the active-auction
  // probe so the entry button reflects reality instead of always linking to a gated page.
  const liveAuction = !!auction?.auction_id;
  const isClassic = auction?.mode === 'classic';
  const isAdmin = !!auction?.is_admin;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <SectionTitle>Mercato</SectionTitle>
            <div className="mt-1 text-sm text-slate-600">
              {open
                ? 'Il mercato è aperto: le acquisizioni avvengono tramite l’asta della lega.'
                : 'Il mercato è chiuso. L’admin può aprirlo da Gestione lega.'}
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
        {liveAuction ? (
          <>
            <div className="mt-2 flex items-center gap-2 text-sm text-slate-700">
              <Badge tone="green">Live</Badge>
              <span>
                {isAdmin
                  ? 'Sei il banditore: entra per chiamare i giocatori e aggiudicare.'
                  : 'Asta in corso: entra per seguire e rilanciare in tempo reale.'}
              </span>
            </div>
            <Link to="/auction" className="mt-3 inline-flex">
              <Button>Entra nella sala asta →</Button>
            </Link>
          </>
        ) : !isClassic ? (
          <div className="mt-2 text-sm text-slate-600">
            La sala asta è disponibile solo per le leghe in <b>modalità classic</b>. In questa lega le rose
            si compongono in altro modo.
          </div>
        ) : isAdmin ? (
          <>
            <div className="mt-2 text-sm text-slate-600">
              Non è ancora in corso nessuna asta. Puoi avviare l’asta iniziale della lega dalla sala asta.
            </div>
            <Link to="/auction" className="mt-3 inline-flex">
              <Button variant="secondary">Vai all’asta</Button>
            </Link>
          </>
        ) : (
          <div className="mt-2 text-sm text-slate-600">
            L’asta non è ancora iniziata. Quando l’admin la avvia, potrai entrare nella sala per rilanciare
            in tempo reale.
          </div>
        )}
      </Card>

      <Card className="p-4">
        <SectionTitle>Mercato di riparazione</SectionTitle>
        <div className="mt-2 text-sm text-slate-600">
          Le offerte sugli svincolati a mercato aperto (con svincolo simultaneo di un giocatore della propria
          rosa) sono <b>in arrivo</b>.
        </div>
      </Card>
    </div>
  );
}
