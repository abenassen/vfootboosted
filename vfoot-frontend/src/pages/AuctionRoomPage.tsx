import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import { useLeagueContext } from '../league/LeagueContext';
import { useAuctionSocket } from '../hooks/useAuctionSocket';
import {
  assignPlayer,
  cancelNomination,
  closeAuctionSession,
  closeNomination,
  createAuction,
  getActiveAuction,
  getAuctionState,
  nominatePlayer,
  placeBid,
  revertNomination,
  searchPlayers,
  undoLastAuctionAction,
  voidBid,
} from '../api';
import type {
  ActiveAuctionInfo,
  AuctionState,
  ClassicRole,
  PlayerSearchItem,
} from '../types/league';

const ROLE_LABEL: Record<ClassicRole, string> = {
  POR: 'Portieri',
  DIF: 'Difensori',
  CEN: 'Centrocampisti',
  ATT: 'Attaccanti',
};
const ROLE_SHORT: Record<ClassicRole, string> = { POR: 'P', DIF: 'D', CEN: 'C', ATT: 'A' };
const ROLES: ClassicRole[] = ['POR', 'DIF', 'CEN', 'ATT'];

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
      return `Chiamata annullata: ${p.player_name} torna in lista`;
    case 'assignment_reverted':
      return `Acquisto revocato: ${p.player_name} (rimborso ${p.amount ?? '?'})`;
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
    return <Card className="p-6 text-sm text-slate-600">Seleziona una lega.</Card>;
  }
  if (loading) {
    return <Card className="p-6 text-sm text-slate-600">Caricamento asta…</Card>;
  }

  if (info && info.mode !== 'classic') {
    return (
      <Card className="p-6 text-sm text-slate-600">
        L’asta è disponibile solo per le leghe in modalità <b>classic</b>.
      </Card>
    );
  }

  if (!auctionId) {
    return (
      <div className="space-y-4">
        <SectionTitle>Asta della lega</SectionTitle>
        <Card className="p-6 text-sm text-slate-600">
          Nessun’asta in corso.
          {isAdmin ? (
            <div className="mt-3">
              <Button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const res = (await createAuction(selectedLeagueId)) as { auction_id: number };
                    await loadInfo();
                    setMsg(`Asta avviata (#${res.auction_id}).`);
                  })
                }
              >
                Avvia asta iniziale
              </Button>
              <div className="mt-2 text-xs text-slate-500">
                Il pool è l’intero listone congelato della lega.
              </div>
            </div>
          ) : (
            <div className="mt-2 text-xs text-slate-500">
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
          <Badge tone={socketStatus === 'open' ? 'green' : socketStatus === 'connecting' ? 'amber' : 'red'}>
            {socketStatus === 'open' ? 'Live' : socketStatus === 'connecting' ? 'Connessione…' : 'Offline'}
          </Badge>
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
              onVoidBid={(bidId) => run(() => voidBid(bidId), 'Offerta annullata.')}
              onAssignCurrent={(teamId, price) =>
                run(() => assignPlayer(auctionId, state.open_nomination!.player_id, teamId, price), 'Assegnato.')
              }
            />

            {isAdmin && state.status === 'active' ? (
              <AdminControls
                auctionId={auctionId}
                leagueId={selectedLeagueId}
                state={state}
                busy={busy}
                hasOpen={!!state.open_nomination}
                run={run}
              />
            ) : null}

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
  const cls = tone === 'green' ? 'bg-green-50 text-green-800 border-green-200' : 'bg-red-50 text-red-800 border-red-200';
  return <div className={`rounded-xl border px-3 py-2 text-sm ${cls}`}>{children}</div>;
}

function CurrentPlayerPanel({
  state,
  isAdmin,
  busy,
  onBid,
  onClose,
  onCancel,
  onVoidBid,
  onAssignCurrent,
}: {
  state: AuctionState;
  isAdmin: boolean;
  busy: boolean;
  onBid: (amount: number, teamId?: number) => void;
  onClose: () => void;
  onCancel: () => void;
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

  if (!nom) {
    return (
      <Card className="p-4">
        <SectionTitle>In chiamata</SectionTitle>
        <div className="mt-2 text-sm text-slate-500">
          Nessun giocatore in chiamata. {isAdmin ? 'Chiama un giocatore dai controlli qui sotto.' : 'In attesa dell’amministratore.'}
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
            <span className="text-slate-500">chiamato da {nom.nominator}</span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-slate-500">Offerta migliore</div>
          <div className="text-2xl font-extrabold">{nom.top_bid}</div>
          {nom.top_bidder_team_name ? (
            <div className="text-xs text-slate-500">{nom.top_bidder_team_name}</div>
          ) : (
            <div className="text-xs text-slate-400">nessuna</div>
          )}
        </div>
      </div>

      {/* Bidding */}
      <div className="mt-4 flex flex-wrap items-end gap-2">
        <div>
          <label htmlFor="bid-amount" className="block text-[11px] font-semibold text-slate-500">
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
            <label htmlFor="on-behalf" className="block text-[11px] font-semibold text-slate-500">
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
          <div className="text-[11px] font-semibold text-slate-500">Offerte</div>
          <div className="mt-1 space-y-1">
            {nom.bids.map((b) => (
              <div key={b.bid_id} className="flex items-center justify-between rounded-lg border px-2 py-1 text-xs">
                <span>
                  <b>{b.amount}</b> · {b.team_name ?? b.manager}
                </span>
                {isAdmin ? (
                  <button className="text-red-600 hover:underline" onClick={() => onVoidBid(b.bid_id)}>
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
          <div className="flex flex-wrap gap-2">
            <Button disabled={busy || nom.top_bid < 1} onClick={onClose}>
              Aggiudica al migliore
            </Button>
            <Button variant="secondary" disabled={busy} onClick={onCancel}>
              Annulla chiamata
            </Button>
          </div>
          {/* Verbal auction: assign THIS player to the winner at the agreed price,
              no in-app bids required. */}
          <div className="rounded-xl bg-slate-50 p-2">
            <div className="text-[11px] font-semibold text-slate-500">
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
  leagueId,
  state,
  busy,
  hasOpen,
  run,
}: {
  auctionId: number;
  leagueId: number;
  state: AuctionState;
  busy: boolean;
  hasOpen: boolean;
  run: (fn: () => Promise<unknown>, okMsg?: string) => Promise<void>;
}) {
  const [role, setRole] = useState<ClassicRole>('DIF');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PlayerSearchItem[]>([]);
  const [assignTeam, setAssignTeam] = useState<number | ''>('');
  const [assignPrice, setAssignPrice] = useState('1');
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doSearch = (q: string) => {
    setQuery(q);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    searchTimer.current = setTimeout(async () => {
      try {
        setResults(await searchPlayers(q, leagueId, 12));
      } catch {
        setResults([]);
      }
    }, 250);
  };

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
        <label htmlFor="nom-search" className="block text-[11px] font-semibold text-slate-500">
          Chiama un giocatore specifico
        </label>
        <input
          id="nom-search"
          className="mt-1 w-full rounded-xl border px-3 py-2 text-sm"
          placeholder="Cerca per nome…"
          value={query}
          onChange={(e) => doSearch(e.target.value)}
          disabled={hasOpen}
        />
        {results.length ? (
          <div className="mt-1 max-h-40 space-y-1 overflow-auto">
            {results.map((p) => (
              <button
                key={p.player_id}
                disabled={busy || hasOpen}
                className="block w-full rounded-lg border px-2 py-1 text-left text-xs hover:bg-slate-50 disabled:opacity-50"
                onClick={() =>
                  run(async () => {
                    await nominatePlayer(auctionId, { mode: 'manual', player_id: p.player_id });
                    setQuery('');
                    setResults([]);
                  }, `Chiamato ${p.name}.`)
                }
              >
                {p.full_name}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {/* Direct assign shortcut */}
      <div className="mt-4 border-t pt-3">
        <div className="text-[11px] font-semibold text-slate-500">Assegnazione diretta (asta dal vivo)</div>
        <div className="mt-1 flex flex-wrap items-end gap-2">
          <input
            className="w-40 rounded-xl border px-3 py-2 text-sm"
            placeholder="Cerca giocatore…"
            value={query}
            onChange={(e) => doSearch(e.target.value)}
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
                className="block w-full rounded-lg border px-2 py-1 text-left text-xs hover:bg-slate-50 disabled:opacity-50"
                onClick={() =>
                  run(async () => {
                    await assignPlayer(auctionId, p.player_id, Number(assignTeam), Number(assignPrice));
                    setQuery('');
                    setResults([]);
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
          <div className="text-[11px] font-semibold text-slate-500">Acquisti recenti</div>
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
                    className="text-red-600 hover:underline disabled:opacity-50"
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
                <span className="text-xs text-slate-400"> / {t.initial_budget}</span>
              </div>
            </div>
            <div className="mt-1 flex gap-1 text-[11px]">
              {ROLES.map((r) => {
                const s = t.slots[r];
                const full = s.remaining <= 0;
                return (
                  <span
                    key={r}
                    className={`rounded px-1.5 py-0.5 ${full ? 'bg-slate-200 text-slate-500' : 'bg-blue-50 text-blue-700'}`}
                    title={ROLE_LABEL[r]}
                  >
                    {ROLE_SHORT[r]} {s.filled}/{s.quota}
                  </span>
                );
              })}
              <span className="ml-auto text-slate-400">max {t.max_bid_any}</span>
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
            <div key={e.id} className="flex items-baseline gap-2 border-b border-slate-100 py-1">
              <span className="text-slate-400">{new Date(e.created_at).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}</span>
              <span>{eventLine(e.type, e.payload)}</span>
              {e.actor ? <span className="ml-auto text-slate-400">{e.actor}</span> : null}
            </div>
          ))
        ) : (
          <div className="text-slate-500">Nessuna attività ancora.</div>
        )}
      </div>
    </Card>
  );
}
