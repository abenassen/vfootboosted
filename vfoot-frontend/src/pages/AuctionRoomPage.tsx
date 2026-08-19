import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import { useLeagueContext } from '../league/LeagueContext';
import { useAuctionSocket } from '../hooks/useNudgeSocket';
import {
  assignPlayer,
  cancelNomination,
  closeAuctionSession,
  closeNomination,
  createAuction,
  getActiveAuction,
  getAuctionState,
  markNominationUnsold,
  nominatePlayer,
  placeBid,
  revertNomination,
  undoLastAuctionAction,
  voidBid,
} from '../api';
import { getAuctionPool, getAuctionRosters, type AuctionPoolPlayer } from '../api/backend';
import { foldedMatch } from '../utils/text';
import { CURRENCY_SYMBOL, price } from '../utils/currency';
import type {
  ActiveAuctionInfo,
  AuctionRosterEntry,
  AuctionRosters,
  AuctionState,
  AuctionTeamBudget,
  ClassicRole,
} from '../types/league';

const ROLE_LABEL: Record<ClassicRole, string> = {
  POR: 'Portieri',
  DIF: 'Difensori',
  CEN: 'Centrocampisti',
  ATT: 'Attaccanti',
};
const ROLE_SHORT: Record<ClassicRole, string> = { POR: 'P', DIF: 'D', CEN: 'C', ATT: 'A' };
const ROLES: ClassicRole[] = ['POR', 'DIF', 'CEN', 'ATT'];
// Le quattro tinte dei reparti, prese dai token del tema e non da colori scritti
// a mano: in una riga di rosa la lettera del ruolo è l'unica cosa che si legge
// senza leggere, e con `blue-50` sopra `blue-700` sparirebbe nel tema scuro.
const ROLE_TINT: Record<ClassicRole, string> = {
  POR: 'bg-warn-bg text-warn',
  DIF: 'bg-accent/10 text-accent',
  CEN: 'bg-good-bg text-good',
  ATT: 'bg-bad-bg text-bad',
};

/** Vero quando lo schermo è largo abbastanza per tenere aperte tutte le rose.
 *
 *  1024px è la soglia `lg`, la stessa a cui la pagina passa a tre colonne: le
 *  rose degli altri si aprono da sole esattamente quando compare lo spazio in cui
 *  metterle, e sotto quella soglia restano chiuse — dodici rose da venticinque
 *  giocatori su un telefono sono trecento righe tra chi sta chiamando e chi sta
 *  rilanciando. Resta comunque tutto apribile a mano, sopra e sotto la soglia. */
function useWideScreen(): boolean {
  const query = '(min-width: 1024px)';
  const [wide, setWide] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(query).matches,
  );
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia(query);
    const onChange = (e: MediaQueryListEvent) => setWide(e.matches);
    setWide(mq.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return wide;
}

function eventLine(type: string, payload: Record<string, unknown>): string {
  const p = payload as Record<string, string | number>;
  switch (type) {
    case 'session_created':
      return `Asta creata (${p.pool ?? '?'} giocatori)`;
    case 'nominated':
      return `Chiamato ${p.player_name} (${p.role ?? '?'})`;
    case 'bid':
      return `${p.team_name} offre ${p.amount} su ${p.player_name}`;
    case 'bid_voided':
      return `Annullata offerta da ${p.amount} su ${p.player_name}`;
    case 'assigned':
      return `${p.player_name} → ${p.team_name} per ${p.amount}${p.via === 'assign' ? ' (diretta)' : ''}`;
    case 'nomination_cancelled':
      return p.restored
        ? `${p.player_name} rimesso in lista`
        : `Chiamata annullata: ${p.player_name} torna in lista`;
    case 'nomination_unsold':
      return `Nessuna offerta per ${p.player_name}: fuori dal giro`;
    case 'assignment_reverted':
      // Dove finisce il giocatore dipende dal banco: se c'era già qualcuno in
      // chiamata torna nel sacchetto, altrimenti risale sul banco lui. Sono due
      // esiti diversi e la cronologia deve distinguerli, o la stanza non capisce
      // perché a volte il giocatore ricompare in chiamata e a volte no.
      return `Acquisto revocato: ${p.player_name} (rimborso ${p.amount ?? '?'})${
        p.back_to_pool ? ' · torna in lista' : ' · torna in chiamata'
      }`;
    case 'session_closed':
      return 'Asta chiusa';
    default:
      return type;
  }
}

export default function AuctionRoomPage() {
  const { selectedLeagueId } = useLeagueContext();
  const [info, setInfo] = useState<ActiveAuctionInfo | null>(null);
  const [state, setState] = useState<AuctionState | null>(null);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const auctionId = info?.auction_id ?? null;
  const isAdmin = info?.is_admin ?? false;

  const refetchState = useCallback(async () => {
    if (!auctionId) return;
    try {
      setState(await getAuctionState(auctionId));
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Errore nel caricamento asta.');
    }
  }, [auctionId]);

  const socketStatus = useAuctionSocket(auctionId, refetchState);

  const loadInfo = useCallback(async () => {
    if (!selectedLeagueId) return;
    setLoading(true);
    try {
      const i = await getActiveAuction(selectedLeagueId);
      setInfo(i);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Errore.');
    } finally {
      setLoading(false);
    }
  }, [selectedLeagueId]);

  useEffect(() => {
    void loadInfo();
  }, [loadInfo]);

  useEffect(() => {
    if (auctionId) void refetchState();
  }, [auctionId, refetchState]);

  // Any admin action → run, surface errors, then refresh state.
  const run = useCallback(
    async (fn: () => Promise<unknown>, okMsg?: string) => {
      setBusy(true);
      setErr(null);
      setMsg(null);
      try {
        await fn();
        if (okMsg) setMsg(okMsg);
        await refetchState();
      } catch (e) {
        setErr(e instanceof Error ? e.message : 'Operazione non riuscita.');
      } finally {
        setBusy(false);
      }
    },
    [refetchState],
  );

  if (!selectedLeagueId) {
    return <Card className="p-6 text-sm text-ink-soft">Seleziona una lega.</Card>;
  }
  if (loading) {
    return <Card className="p-6 text-sm text-ink-soft">Caricamento asta…</Card>;
  }

  if (info && info.mode !== 'classic') {
    return (
      <Card className="p-6 text-sm text-ink-soft">
        L’asta è disponibile solo per le leghe in modalità <b>classic</b>.
      </Card>
    );
  }

  if (!auctionId) {
    return (
      <div className="space-y-4">
        <SectionTitle>Asta della lega</SectionTitle>
        <Card className="p-6 text-sm text-ink-soft">
          Nessun’asta in corso.
          {isAdmin ? (
            <div className="mt-3">
              <Button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    // NIENTE «(#3)» qui dietro: era `auction_id`, la chiave della
                    // sessione nel database, che conta le aste di TUTTE le leghe
                    // insieme — la prima asta di una lega nuova si presentava col
                    // numero di quante ne erano state avviate altrove, e si legge
                    // come «la mia seconda asta». Quello che serve sapere di
                    // un'asta appena aperta è quanti giocatori ha in lista.
                    const res = (await createAuction(selectedLeagueId)) as { players?: number };
                    await loadInfo();
                    setMsg(
                      res.players
                        ? `Asta avviata: ${res.players} giocatori in lista.`
                        : 'Asta avviata.',
                    );
                  })
                }
              >
                Avvia asta iniziale
              </Button>
              <div className="mt-2 text-xs text-ink-faint">
                Il pool è l’intero listone congelato della lega.
              </div>
            </div>
          ) : (
            <div className="mt-2 text-xs text-ink-faint">
              L’amministratore non ha ancora avviato l’asta.
            </div>
          )}
        </Card>
        {err ? <Banner tone="red">{err}</Banner> : null}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SectionTitle className="!mb-0">{state?.name ?? 'Asta'}</SectionTitle>
        <div className="flex items-center gap-2 text-xs">
          {/* Il pallino del collegamento serve finche' c'e' qualcosa da seguire:
              accanto a «Chiusa», un «Live» verde diceva il contrario di quello
              che significa (la presa e' attaccata, non l'asta e' in corso). */}
          {state?.status === 'closed' ? null : (
            <Badge tone={socketStatus === 'open' ? 'green' : socketStatus === 'connecting' ? 'amber' : 'red'}>
              {socketStatus === 'open' ? 'Live' : socketStatus === 'connecting' ? 'Connessione…' : 'Offline'}
            </Badge>
          )}
          {state ? (
            <Badge tone="blue">
              {state.pool_remaining}/{state.pool_total} in lista
            </Badge>
          ) : null}
          {state?.status === 'closed' ? <Badge tone="slate">Chiusa</Badge> : null}
        </div>
      </div>

      {msg ? <Banner tone="green">{msg}</Banner> : null}
      {err ? <Banner tone="red">{err}</Banner> : null}

      {state ? (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-4 lg:col-span-2">
            <CurrentPlayerPanel
              state={state}
              isAdmin={isAdmin}
              busy={busy}
              onBid={(amount, teamId) =>
                run(() => placeBid(state.open_nomination!.nomination_id, amount, teamId), 'Offerta inviata.')
              }
              onClose={() => run(() => closeNomination(state.open_nomination!.nomination_id), 'Assegnato.')}
              onCancel={() =>
                run(() => cancelNomination(state.open_nomination!.nomination_id), 'Chiamata annullata.')
              }
              onUnsold={() =>
                run(
                  () => markNominationUnsold(state.open_nomination!.nomination_id),
                  'Nessuna offerta: si va avanti.',
                )
              }
              onVoidBid={(bidId) => run(() => voidBid(bidId), 'Offerta annullata.')}
              onAssignCurrent={(teamId, price) =>
                run(() => assignPlayer(auctionId, state.open_nomination!.player_id, teamId, price), 'Assegnato.')
              }
            />

            {isAdmin && state.status === 'active' ? (
              <AdminControls
                auctionId={auctionId}
                state={state}
                busy={busy}
                hasOpen={!!state.open_nomination}
                run={run}
              />
            ) : null}

            {/* Le rose stanno PRIMA della cronologia, e nella colonna larga.
                La cronologia è il racconto di quel che è successo; la rosa è
                com'è messa adesso una squadra, che è la cosa su cui si decide
                se rilanciare — e quella andava cercata sulla pagina Rose, che
                non è attaccata al socket e quindi durante un'asta era ferma. */}
            <RosterBoard auctionId={auctionId} state={state} />

            <FeedPanel state={state} />
          </div>

          <div className="space-y-4">
            <BudgetBoard state={state} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Banner({ tone, children }: { tone: 'green' | 'red'; children: React.ReactNode }) {
  const cls = tone === 'green' ? 'bg-good-bg text-good border-good/40' : 'bg-bad-bg text-bad border-bad/40';
  return <div className={`rounded-xl border px-3 py-2 text-sm ${cls}`}>{children}</div>;
}

function CurrentPlayerPanel({
  state,
  isAdmin,
  busy,
  onBid,
  onClose,
  onCancel,
  onUnsold,
  onVoidBid,
  onAssignCurrent,
}: {
  state: AuctionState;
  isAdmin: boolean;
  busy: boolean;
  onBid: (amount: number, teamId?: number) => void;
  onClose: () => void;
  onCancel: () => void;
  onUnsold: () => void;
  onVoidBid: (bidId: number) => void;
  onAssignCurrent: (teamId: number, price: number) => void;
}) {
  const nom = state.open_nomination;
  const [amount, setAmount] = useState('');
  const [onBehalf, setOnBehalf] = useState<number | ''>('');
  // Verbal-auction assignment of THIS player: team + agreed price.
  const [assignTeam, setAssignTeam] = useState<number | ''>('');
  const [assignPrice, setAssignPrice] = useState('1');

  useEffect(() => {
    setAmount(nom ? String(nom.min_next_bid) : '');
    // Seed the assign price with the standing top bid if any (mixed app+verbal),
    // else 1 credit — the admin types the price called out in the room.
    setAssignPrice(nom && nom.top_bid > 0 ? String(nom.top_bid) : '1');
    setAssignTeam(nom && nom.top_bidder_team_id ? nom.top_bidder_team_id : '');
  }, [nom?.nomination_id, nom?.min_next_bid, nom?.top_bid, nom?.top_bidder_team_id]);

  // «Per conto di» torna su me stesso a ogni nuova chiamata. Restava sull'ultima
  // squadra per cui il banditore aveva rilanciato, e la chiamata dopo il tasto
  // Rilancia — che si legge come «offro io» — offriva per un altro.
  useEffect(() => {
    setOnBehalf('');
  }, [nom?.nomination_id]);

  if (!nom) {
    const closed = state.status === 'closed';
    return (
      <Card className="p-4">
        <SectionTitle>In chiamata</SectionTitle>
        <div className="mt-2 text-sm text-ink-faint">
          {closed
            ? // A sessione chiusa non si chiama piu' nessuno, e i controlli del
              // banditore non sono nemmeno in pagina: invitare a usarli era un
              // rimando al nulla.
              'Asta chiusa: le rose sono quelle qui sotto. Nessuna chiamata in corso.'
            : `Nessun giocatore in chiamata. ${isAdmin ? 'Chiama un giocatore dai controlli qui sotto.' : 'In attesa dell’amministratore.'}`}
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-lg font-bold">{nom.player_name}</div>
          <div className="mt-1 flex items-center gap-2 text-xs">
            {nom.player_role ? <Badge tone="blue">{ROLE_LABEL[nom.player_role]}</Badge> : null}
            <span className="text-ink-faint">chiamato da {nom.nominator}</span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-ink-faint">Offerta migliore</div>
          <div className="text-2xl font-extrabold">{nom.top_bid}</div>
          {nom.top_bidder_team_name ? (
            <div className="text-xs text-ink-faint">{nom.top_bidder_team_name}</div>
          ) : (
            <div className="text-xs text-ink-faint">nessuna</div>
          )}
        </div>
      </div>

      {/* Bidding */}
      <div className="mt-4 flex flex-wrap items-end gap-2">
        <div>
          <label htmlFor="bid-amount" className="block text-[11px] font-semibold text-ink-faint">
            La tua offerta (min {nom.min_next_bid})
          </label>
          <input
            id="bid-amount"
            className="mt-1 w-28 rounded-xl border px-3 py-2 text-sm"
            inputMode="numeric"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </div>
        {isAdmin ? (
          <div>
            <label htmlFor="on-behalf" className="block text-[11px] font-semibold text-ink-faint">
              Per conto di
            </label>
            <select
              id="on-behalf"
              className="mt-1 rounded-xl border px-2 py-2 text-sm"
              value={onBehalf}
              onChange={(e) => setOnBehalf(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">— me stesso —</option>
              {state.team_budgets.map((t) => (
                <option key={t.team_id} value={t.team_id}>
                  {t.team_name}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <Button
          disabled={busy || !amount}
          onClick={() => onBid(Number(amount), isAdmin && onBehalf ? Number(onBehalf) : undefined)}
        >
          Rilancia
        </Button>
        <div className="flex gap-1">
          {[1, 5, 10].map((d) => (
            <Button key={d} size="sm" variant="ghost" onClick={() => setAmount(String(nom.min_next_bid + d - 1))}>
              +{d - 1 || ''}
              {d === 1 ? 'min' : ''}
            </Button>
          ))}
        </div>
      </div>

      {/* Bids list */}
      {nom.bids.length ? (
        <div className="mt-4">
          <div className="text-[11px] font-semibold text-ink-faint">Offerte</div>
          <div className="mt-1 space-y-1">
            {nom.bids.map((b) => (
              <div key={b.bid_id} className="flex items-center justify-between rounded-lg border px-2 py-1 text-xs">
                <span>
                  <b>{b.amount}</b> · {b.team_name ?? b.manager}
                </span>
                {isAdmin ? (
                  <button className="text-bad hover:underline" onClick={() => onVoidBid(b.bid_id)}>
                    annulla
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {isAdmin ? (
        <div className="mt-4 space-y-3 border-t pt-3">
          {/* COME SI CHIUDE UNA CHIAMATA, in due modi soli e nell'ordine in cui
              capitano davvero.

              Se c'è un'offerta si aggiudica. Se non ce n'è nessuna — che è la
              situazione più frequente di un'asta, non l'eccezione — si passa al
              prossimo, e prima non esisteva un tasto per farlo: restava «Annulla
              chiamata», che vuol dire un'altra cosa e si legge come «ho sbagliato
              a chiamarlo». Peggio, faceva davvero un'altra cosa: rimetteva il
              giocatore nel sacchetto, e il sorteggio dopo poteva ritirare fuori
              proprio quello che la stanza aveva appena scartato.

              L'annullamento resta ma scende di rango: è la correzione di un
              errore, e da qui in poi lo dice per esteso. */}
          <div className="flex flex-wrap gap-2">
            <Button disabled={busy || nom.top_bid < 1} onClick={onClose}>
              Aggiudica al migliore
            </Button>
            <Button
              variant={nom.top_bid < 1 ? 'primary' : 'secondary'}
              disabled={busy}
              onClick={onUnsold}
            >
              Nessuno lo vuole →
            </Button>
          </div>
          <div className="flex flex-wrap items-baseline gap-2 text-xs text-ink-faint">
            <span>
              {nom.top_bid < 1
                ? 'Nessuna offerta: «Nessuno lo vuole» chiude la chiamata e lo toglie dal sorteggio (resta chiamabile per nome).'
                : 'Chiamato per sbaglio?'}
            </span>
            <button
              type="button"
              disabled={busy}
              onClick={onCancel}
              className="font-semibold text-ink-soft underline hover:text-ink disabled:opacity-50"
            >
              Annulla la chiamata e rimettilo nel sorteggio
            </button>
          </div>
          {/* Verbal auction: assign THIS player to the winner at the agreed price,
              no in-app bids required. */}
          <div className="rounded-xl bg-surface-2 p-2">
            <div className="text-[11px] font-semibold text-ink-faint">
              Assegna {nom.player_name} (rilanci a voce)
            </div>
            <div className="mt-1 flex flex-wrap items-end gap-2">
              <select
                className="rounded-xl border px-2 py-2 text-sm"
                value={assignTeam}
                onChange={(e) => setAssignTeam(e.target.value ? Number(e.target.value) : '')}
                aria-label="Squadra vincitrice"
              >
                <option value="">— squadra —</option>
                {state.team_budgets.map((t) => (
                  <option key={t.team_id} value={t.team_id}>
                    {t.team_name}
                  </option>
                ))}
              </select>
              <input
                className="w-20 rounded-xl border px-3 py-2 text-sm"
                inputMode="numeric"
                value={assignPrice}
                onChange={(e) => setAssignPrice(e.target.value)}
                aria-label="Prezzo di aggiudicazione"
              />
              <Button
                disabled={busy || !assignTeam || !assignPrice}
                onClick={() => onAssignCurrent(Number(assignTeam), Number(assignPrice))}
              >
                Assegna
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

function AdminControls({
  auctionId,
  state,
  busy,
  hasOpen,
  run,
}: {
  auctionId: number;
  state: AuctionState;
  busy: boolean;
  hasOpen: boolean;
  run: (fn: () => Promise<unknown>, okMsg?: string) => Promise<void>;
}) {
  const [role, setRole] = useState<ClassicRole>('DIF');
  const [query, setQuery] = useState('');
  const [assignTeam, setAssignTeam] = useState<number | ''>('');
  const [assignPrice, setAssignPrice] = useState('1');
  const [pool, setPool] = useState<AuctionPoolPlayer[]>([]);

  // The callable pool, fetched once and re-fetched whenever ANYTHING happens in
  // the auction. The key is the id of the latest event, not pool_remaining: every
  // mutation records an event and ids only go up, whereas the count can stay put
  // across a change — a cancelled nomination puts its player back, so an assign
  // and a cancel between two reads leave the same number with different names in
  // it. The socket already fires on each event and the page re-fetches the state,
  // so this rides along on a refresh that was happening anyway.
  const lastEventId = state.events[0]?.id ?? null;
  useEffect(() => {
    let alive = true;
    void getAuctionPool(auctionId)
      .then((p) => alive && setPool(p))
      .catch(() => alive && setPool([]));
    return () => {
      alive = false;
    };
  }, [auctionId, lastEventId]);

  // How many are still in the drawn order. When it empties, calling by name is
  // the only way left to finish a short roster.
  const drawLeft = pool.filter((p) => p.in_draw_order).length;
  const [includeCalled, setIncludeCalled] = useState(false);
  useEffect(() => {
    // Ticks itself when the order runs out: leaving it off there would show an
    // empty search on an auction that still has players to place.
    if (pool.length && drawLeft === 0) setIncludeCalled(true);
  }, [pool.length, drawLeft]);

  const results = useMemo(() => {
    if (query.trim().length < 2) return [];
    return pool
      .filter((p) => (includeCalled || p.in_draw_order) && foldedMatch(query, [p.name, p.full_name]))
      .slice(0, 12);
  }, [pool, query, includeCalled]);

  return (
    <Card className="p-4">
      <SectionTitle>Controlli banditore</SectionTitle>

      {/* Nomination modes */}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          disabled={busy || hasOpen}
          onClick={() => run(() => nominatePlayer(auctionId, { mode: 'random' }), 'Giocatore chiamato.')}
        >
          Chiama a caso
        </Button>
        <div className="flex items-center gap-1">
          <select
            className="rounded-xl border px-2 py-2 text-sm"
            value={role}
            onChange={(e) => setRole(e.target.value as ClassicRole)}
            aria-label="Ruolo"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]} ({state.remaining_by_role[r]})
              </option>
            ))}
          </select>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy || hasOpen}
            onClick={() => run(() => nominatePlayer(auctionId, { mode: 'random_role', role }), 'Giocatore chiamato.')}
          >
            Chiama a caso nel ruolo
          </Button>
        </div>
        <Button
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={() => run(() => undoLastAuctionAction(auctionId), 'Ultima azione annullata.')}
        >
          Annulla ultima azione
        </Button>
        <Button
          size="sm"
          variant="danger"
          disabled={busy}
          onClick={() => run(() => closeAuctionSession(auctionId), 'Asta chiusa.')}
        >
          Chiudi asta
        </Button>
      </div>

      {/* Manual search */}
      <div className="mt-4">
        <label htmlFor="nom-search" className="block text-[11px] font-semibold text-ink-faint">
          Chiama un giocatore specifico
        </label>
        <input
          id="nom-search"
          className="mt-1 w-full rounded-xl border px-3 py-2 text-sm"
          placeholder="Cerca per nome…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={hasOpen}
        />
        {results.length ? (
          <div className="mt-1 max-h-40 space-y-1 overflow-auto">
            {results.map((p) => (
              <button
                key={p.player_id}
                disabled={busy || hasOpen}
                className="block w-full rounded-lg border px-2 py-1 text-left text-xs hover:bg-surface-2 disabled:opacity-50"
                onClick={() =>
                  run(async () => {
                    await nominatePlayer(auctionId, { mode: 'manual', player_id: p.player_id });
                    setQuery('');
                  }, `Chiamato ${p.name}.`)
                }
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate">{p.full_name}</span>
                  <span className="flex shrink-0 items-center gap-1">
                    {p.role ? <span className="text-[10px] text-ink-faint">{p.role}</span> : null}
                    {/* Callable but not in the drawn order: signed after the
                        auction began, or already gone round once. Worth saying,
                        because calling him is a deliberate act. */}
                    {!p.in_draw_order ? (
                      <span className="rounded bg-warn-bg px-1 text-[10px] font-semibold text-warn">
                        fuori lista
                      </span>
                    ) : null}
                  </span>
                </span>
              </button>
            ))}
          </div>
        ) : null}
        <label className="mt-1.5 flex items-center gap-1.5 text-[11px] text-ink-soft">
          <input
            type="checkbox"
            checked={includeCalled}
            disabled={drawLeft === 0}
            onChange={(e) => setIncludeCalled(e.target.checked)}
          />
          <span>
            Includi i già chiamati e non acquistati
            {drawLeft === 0 ? (
              <span className="ml-1 text-ink-faint">· il giro è finito, non resta altro</span>
            ) : (
              <span className="ml-1 text-ink-faint">· {drawLeft} ancora in lista</span>
            )}
          </span>
        </label>
      </div>

      {/* Direct assign shortcut */}
      <div className="mt-4 border-t pt-3">
        <div className="text-[11px] font-semibold text-ink-faint">Assegnazione diretta (asta dal vivo)</div>
        <div className="mt-1 flex flex-wrap items-end gap-2">
          <input
            className="w-40 rounded-xl border px-3 py-2 text-sm"
            placeholder="Cerca giocatore…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Giocatore da assegnare"
          />
          <select
            className="rounded-xl border px-2 py-2 text-sm"
            value={assignTeam}
            onChange={(e) => setAssignTeam(e.target.value ? Number(e.target.value) : '')}
            aria-label="Squadra assegnataria"
          >
            <option value="">— squadra —</option>
            {state.team_budgets.map((t) => (
              <option key={t.team_id} value={t.team_id}>
                {t.team_name}
              </option>
            ))}
          </select>
          <input
            className="w-20 rounded-xl border px-3 py-2 text-sm"
            inputMode="numeric"
            value={assignPrice}
            onChange={(e) => setAssignPrice(e.target.value)}
            aria-label="Prezzo"
          />
        </div>
        {query.trim().length >= 2 && results.length ? (
          <div className="mt-1 max-h-32 space-y-1 overflow-auto">
            {results.map((p) => (
              <button
                key={p.player_id}
                disabled={busy || !assignTeam || !assignPrice}
                className="block w-full rounded-lg border px-2 py-1 text-left text-xs hover:bg-surface-2 disabled:opacity-50"
                onClick={() =>
                  run(async () => {
                    await assignPlayer(auctionId, p.player_id, Number(assignTeam), Number(assignPrice));
                    setQuery('');
                  }, `${p.name} assegnato.`)
                }
              >
                Assegna <b>{p.full_name}</b> a {state.team_budgets.find((t) => t.team_id === assignTeam)?.team_name ?? '—'} per {assignPrice}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {/* Revoke a completed purchase (fix a data-entry error on any past sale). */}
      {state.recent_nominations.some((n) => n.status === 'closed') ? (
        <div className="mt-4 border-t pt-3">
          <div className="text-[11px] font-semibold text-ink-faint">Acquisti recenti</div>
          <div className="mt-1 max-h-40 space-y-1 overflow-auto">
            {state.recent_nominations
              .filter((n) => n.status === 'closed')
              .slice(0, 10)
              .map((n) => (
                <div key={n.nomination_id} className="flex items-center justify-between rounded-lg border px-2 py-1 text-xs">
                  <span>
                    {n.player_name} → <b>{n.winner_team_name}</b> · {n.winning_amount}
                  </span>
                  <button
                    disabled={busy}
                    className="text-bad hover:underline disabled:opacity-50"
                    onClick={() => run(() => revertNomination(n.nomination_id), 'Acquisto revocato.')}
                  >
                    revoca
                  </button>
                </div>
              ))}
          </div>
        </div>
      ) : null}
    </Card>
  );
}

/** Chi ha comprato chi, mentre lo sta comprando.
 *
 *  Il riepilogo qui accanto conta gli slot pieni per reparto — P 0/3, D 8/8 — e
 *  non dice un nome: per sapere chi era andato a chi bisognava uscire dall'asta,
 *  aprire la pagina Rose e ricaricarla a mano. Qui le rose si riempiono da sole,
 *  sullo stesso nudge del socket che aggiorna l'offerta migliore.
 *
 *  La propria sta prima ed è aperta di suo; le altre seguono in ordine alfabetico
 *  — non per budget residuo come il riepilogo, perché una griglia che si
 *  riordina a ogni aggiudicazione fa perdere il posto a chi la stava leggendo. */
function RosterBoard({ auctionId, state }: { auctionId: number; state: AuctionState }) {
  const wide = useWideScreen();
  // Solo le aperture DECISE a mano: il resto resta al valore di partenza, così
  // allargando la finestra le rose si aprono anche se non le si è mai toccate.
  const [overrides, setOverrides] = useState<Record<number, boolean>>({});
  const [rosters, setRosters] = useState<AuctionRosters | null>(null);
  const myTeamId = state.my_team_id;

  // LE ROSE SI RILEGGONO SULL'IMPRONTA, NON SULLO STATO. Il socket manda un nudge
  // a ogni cosa che succede e la pagina rilegge lo stato: se le rose viaggiassero
  // lì dentro, ogni rilancio ne farebbe riscaricare 16 KB a ciascun dispositivo
  // della stanza, per un elenco che un rilancio non tocca. `rosters_rev` cambia
  // solo quando un giocatore cambia proprietario, e allora sì che si rilegge.
  useEffect(() => {
    let alive = true;
    void getAuctionRosters(auctionId)
      .then((r) => alive && setRosters(r))
      .catch(() => {
        /* le rose sono un di più: se non arrivano, l'asta va avanti lo stesso */
      });
    return () => {
      alive = false;
    };
  }, [auctionId, state.rosters_rev]);

  const rosterOf = useMemo(() => {
    const map = new Map<number, AuctionRosterEntry[]>();
    for (const t of rosters?.teams ?? []) map.set(t.team_id, t.roster);
    return map;
  }, [rosters]);
  const last = rosters?.last_purchase ?? null;

  const teams = useMemo(() => {
    const rows = [...state.team_budgets].sort((a, b) => a.team_name.localeCompare(b.team_name, 'it'));
    return [
      ...rows.filter((t) => t.team_id === myTeamId),
      ...rows.filter((t) => t.team_id !== myTeamId),
    ];
  }, [state.team_budgets, myTeamId]);

  const isOpen = (teamId: number) => overrides[teamId] ?? (teamId === myTeamId || wide);
  const allOpen = teams.every((t) => isOpen(t.team_id));

  if (!teams.length) return null;

  return (
    <Card className="p-4">
      <div className="flex items-baseline justify-between gap-2">
        <SectionTitle className="!mb-0">Rose</SectionTitle>
        {teams.length > 1 ? (
          <button
            type="button"
            className="text-[11px] font-semibold text-ink-soft underline hover:text-ink"
            onClick={() =>
              setOverrides(Object.fromEntries(teams.map((t) => [t.team_id, !allOpen])))
            }
          >
            {allOpen ? 'Chiudi tutte' : 'Apri tutte'}
          </button>
        ) : null}
      </div>
      {/* `items-start`: senza, ogni scheda si stira fino all'altezza della più
          alta della sua riga, e accanto a una rosa da ventuno giocatori le altre
          diventavano riquadri quasi vuoti. Griglia e non colonne CSS proprio
          perché è viva: in un impaginato a colonne una rosa che cresce di una
          riga rimescola la posizione di tutte le altre mentre le si legge. */}
      <div className="mt-2 grid items-start gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {teams.map((t) => (
          <TeamRosterCard
            key={t.team_id}
            team={t}
            roster={rosterOf.get(t.team_id) ?? []}
            mine={t.team_id === myTeamId}
            open={isOpen(t.team_id)}
            justBought={last && last.team_id === t.team_id ? last.player_id : null}
            onToggle={() =>
              setOverrides((o) => ({ ...o, [t.team_id]: !isOpen(t.team_id) }))
            }
          />
        ))}
      </div>
    </Card>
  );
}

function TeamRosterCard({
  team,
  roster,
  mine,
  open,
  justBought,
  onToggle,
}: {
  team: AuctionTeamBudget;
  roster: AuctionRosterEntry[];
  mine: boolean;
  open: boolean;
  justBought: number | null;
  onToggle: () => void;
}) {
  // Il conteggio viene dagli slot e non dalla lunghezza dell'elenco: gli slot
  // arrivano con lo stato, quindi il numero è giusto anche nell'istante fra
  // un'aggiudicazione e la rilettura delle rose.
  const quota = ROLES.reduce((s, r) => s + team.slots[r].quota, 0);
  const filled = ROLES.reduce((s, r) => s + team.slots[r].filled, 0);
  return (
    <div className={`rounded-xl border ${mine ? 'border-brand/50 bg-brand/5' : 'border-line'}`}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-2.5 py-2 text-left"
      >
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span className="truncate text-sm font-semibold">{team.team_name}</span>
            {mine ? (
              <span className="shrink-0 rounded bg-brand/15 px-1 text-[10px] font-bold uppercase text-brand">
                tu
              </span>
            ) : null}
          </span>
          <span className="mt-0.5 block text-[11px] text-ink-faint">
            {filled}/{quota} · resta <b className="text-ink-soft">{price(team.available_budget)}</b>
          </span>
        </span>
        <span
          aria-hidden
          className={`shrink-0 text-ink-faint transition-transform ${open ? 'rotate-90' : ''}`}
        >
          ›
        </span>
      </button>

      {open ? (
        roster.length ? (
          <div className="border-t border-line px-2.5 pb-1.5">
            {/* La moneta detta una volta in cima alla colonna, come nella pagina
                Rose, invece che ripetuta accanto a venticinque numeri. */}
            <div className="flex items-center justify-between gap-2 border-b border-line py-1 text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
              <span>Giocatore</span>
              <span className="normal-case tracking-normal">{CURRENCY_SYMBOL}</span>
            </div>
            {roster.map((p) => (
              <div
                key={p.player_id}
                title={p.player_id === justBought ? 'Ultimo acquisto' : undefined}
                className={`-mx-1 flex items-center gap-1.5 rounded px-1 py-[3px] text-xs ${
                  p.player_id === justBought ? 'bg-good-bg' : ''
                }`}
              >
                <span
                  className={`w-4 shrink-0 rounded text-center text-[10px] font-bold leading-4 ${
                    p.role ? ROLE_TINT[p.role] : 'bg-surface-2 text-ink-faint'
                  }`}
                >
                  {p.role ? ROLE_SHORT[p.role] : '?'}
                </span>
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
                <span className="shrink-0 font-semibold tabular-nums">{p.price}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="border-t border-line px-2.5 py-2 text-[11px] text-ink-faint">
            {filled ? 'Caricamento…' : 'Nessun acquisto ancora.'}
          </div>
        )
      ) : null}
    </div>
  );
}

function BudgetBoard({ state }: { state: AuctionState }) {
  const rows = useMemo(
    () => [...state.team_budgets].sort((a, b) => b.available_budget - a.available_budget),
    [state.team_budgets],
  );
  return (
    <Card className="p-4">
      <SectionTitle>Squadre</SectionTitle>
      <div className="mt-2 space-y-2">
        {rows.map((t) => (
          <div key={t.team_id} className="rounded-xl border p-2">
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold">{t.team_name}</div>
              <div className="text-sm">
                <span className="font-bold">{t.available_budget}</span>
                <span className="text-xs text-ink-faint"> / {t.initial_budget}</span>
              </div>
            </div>
            <div className="mt-1 flex gap-1 text-[11px]">
              {ROLES.map((r) => {
                const s = t.slots[r];
                const full = s.remaining <= 0;
                return (
                  <span
                    key={r}
                    className={`rounded px-1.5 py-0.5 ${full ? 'bg-surface-2 text-ink-faint' : 'bg-blue-50 text-blue-700'}`}
                    title={ROLE_LABEL[r]}
                  >
                    {ROLE_SHORT[r]} {s.filled}/{s.quota}
                  </span>
                );
              })}
              <span className="ml-auto text-ink-faint">max {t.max_bid_any}</span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function FeedPanel({ state }: { state: AuctionState }) {
  return (
    <Card className="p-4">
      <SectionTitle>Cronologia</SectionTitle>
      <div className="mt-2 max-h-72 space-y-1 overflow-auto text-xs">
        {state.events.length ? (
          state.events.map((e) => (
            <div key={e.id} className="flex items-baseline gap-2 border-b border-line py-1">
              <span className="text-ink-faint">{new Date(e.created_at).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}</span>
              <span>{eventLine(e.type, e.payload)}</span>
              {e.actor ? <span className="ml-auto text-ink-faint">{e.actor}</span> : null}
            </div>
          ))
        ) : (
          <div className="text-ink-faint">Nessuna attività ancora.</div>
        )}
      </div>
    </Card>
  );
}
