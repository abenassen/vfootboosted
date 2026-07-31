import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ApiError,
  getMarketActive,
  getMarketSessions,
  placeMarketOffer,
} from '../api/backend';
import { getActiveAuction } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { foldedMatch } from '../utils/text';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import {
  OFFER_LABEL,
  OFFER_TONE,
  ROLE_LABEL,
  ROLE_ORDER,
  SESSION_LABEL,
  SESSION_TONE,
  countdown,
  recoveryText,
} from '../utils/market';
import type {
  MarketActive,
  MarketFreeAgent,
  MarketOfferRow,
  MarketSessionHistory,
} from '../types/market';
import type { ActiveAuctionInfo } from '../types/league';

export default function MarketPage() {
  const { selectedLeagueId } = useLeagueContext();
  const [data, setData] = useState<MarketActive | null>(null);
  const [history, setHistory] = useState<MarketSessionHistory[]>([]);
  const [auction, setAuction] = useState<ActiveAuctionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [showHistory, setShowHistory] = useState(false);
  const [targetId, setTargetId] = useState<number | null>(null);

  const pickTarget = useCallback((id: number) => {
    setTargetId(id);
    window.setTimeout(() => document.getElementById('offer-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 0);
  }, []);

  const refresh = useCallback(async () => {
    if (!selectedLeagueId) return;
    try {
      setData(await getMarketActive(selectedLeagueId));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Errore nel caricamento del mercato.');
    }
    // Le offerte concluse arrivano da qui: senza ricaricarlo, una trattativa
    // chiusa da un altro sparirebbe dalle "in corso" senza ricomparire altrove.
    void getMarketSessions(selectedLeagueId).then((r) => setHistory(r.sessions)).catch(() => undefined);
  }, [selectedLeagueId]);

  useEffect(() => {
    if (!selectedLeagueId) {
      setData(null);
      setAuction(null);
      return;
    }
    void refresh();
    void getActiveAuction(selectedLeagueId).then(setAuction).catch(() => setAuction(null));
    const poll = window.setInterval(() => void refresh(), 20_000);
    return () => window.clearInterval(poll);
  }, [selectedLeagueId, refresh]);

  useEffect(() => {
    const t = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const act = useCallback(
    async (fn: () => Promise<unknown>) => {
      setBusy(true);
      setError(null);
      try {
        await fn();
        await refresh();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'Operazione non riuscita.');
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  // Le offerte gia' decise di QUESTA sessione: /market/active porta solo quelle
  // ancora vive (piu' le mie e la coda admin), lo storico le ha tutte. Sta sopra
  // il return anticipato perche' e' un hook.
  const sessionId = data?.session?.id ?? null;
  const closedThisSession = useMemo(
    () => (sessionId == null ? [] : history.find((h) => h.id === sessionId)?.offers ?? [])
      .filter((o) => o.status === 'settled' || o.status === 'rejected' || o.status === 'cancelled'),
    [history, sessionId],
  );
  // La sessione viva e' gia' tutta sopra: nello storico solo le precedenti.
  const pastSessions = useMemo(
    () => history.filter((h) => h.id !== sessionId),
    [history, sessionId],
  );

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega per vedere il mercato.</div>;

  const session = data?.session ?? null;
  const isClassic = (data?.mode ?? auction?.mode) === 'classic';
  const isAdmin = !!data?.is_admin;
  const canOffer = session?.status === 'open' && data?.my_team_id != null;

  return (
    <div className="space-y-4">
      {error && <Card className="border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</Card>}

      {!isClassic ? (
        <Card className="p-4">
          <SectionTitle>Mercato</SectionTitle>
          <div className="mt-2 text-sm text-slate-600">
            Il mercato a offerte è disponibile solo per le leghe in <b>modalità classic</b>.
          </div>
        </Card>
      ) : !session ? (
        <NoSessionCard isAdmin={isAdmin} auction={auction} />
      ) : (
        <>
          <SessionHeader data={data!} isAdmin={isAdmin} />

          {canOffer ? (
            <OfferPanel data={data!} nowMs={nowMs} busy={busy}
              targetId={targetId} onPick={pickTarget} onClearTarget={() => setTargetId(null)}
              onOffer={(t, r, a) => act(async () => { await placeMarketOffer(selectedLeagueId, t, r, a); setTargetId(null); })} />
          ) : (
            // Senza squadra, o a sessione sospesa, la ricerca resta ma da sola:
            // dentro "Fai un'offerta" non avrebbe nessuna offerta da fare.
            <FreeAgentSearchCard data={data!} nowMs={nowMs} onPick={pickTarget} />
          )}

          <MyOffersCard offers={data?.my_offers ?? []} nowMs={nowMs} />

          <LiveContestsCard data={data!} nowMs={nowMs} onPick={pickTarget} />

          <ClosedOffersCard offers={closedThisSession} />
        </>
      )}

      {pastSessions.length > 0 && (
        <Card className="p-4">
          <button className="flex w-full items-center justify-between" onClick={() => setShowHistory((v) => !v)}>
            <SectionTitle>Storico sessioni ({pastSessions.length})</SectionTitle>
            <span className="text-xs text-slate-500">{showHistory ? 'nascondi' : 'mostra'}</span>
          </button>
          {showHistory && <HistoryList sessions={pastSessions} />}
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function NoSessionCard({ isAdmin, auction }: { isAdmin: boolean; auction: ActiveAuctionInfo | null }) {
  const liveAuction = !!auction?.auction_id;
  return (
    <Card className="p-4">
      <SectionTitle>Mercato di riparazione</SectionTitle>
      <div className="mt-2 text-sm text-slate-600">
        Nessuna sessione di mercato aperta.{' '}
        {liveAuction && (
          <>C’è un’asta in corso: <Link to="/auction" className="font-semibold text-slate-900 underline">entra nella sala asta →</Link></>
        )}
      </div>
      <div className="mt-2 text-sm text-slate-500">
        {isAdmin
          ? <>Apri una sessione dalla scheda <b>Mercato</b> in <Link to="/league-admin?tab=league" className="underline">Gestione lega</Link>.</>
          : 'Quando l’admin apre una sessione potrai fare offerte sugli svincolati.'}
      </div>
    </Card>
  );
}

function SessionHeader({ data, isAdmin }: { data: MarketActive; isAdmin: boolean }) {
  const s = data.session!;
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <SectionTitle>{s.name}</SectionTitle>
            <Badge tone={SESSION_TONE[s.status]}>{SESSION_LABEL[s.status]}</Badge>
          </div>
          <div className="mt-1 text-sm text-slate-600">
            Recupero: <b>{recoveryText(s.credit_recovery_mode, s.fixed_recovery_amount)}</b>
            {' · '}
            {s.closes_at ? `chiude il ${new Date(s.closes_at).toLocaleString('it-IT')}` : 'chiusura indefinita'}
          </div>
          {data.my_budget && (
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-700">
              <span>Crediti: <b>{data.my_budget.remaining}</b></span>
              <span className="text-slate-500">impegnati offerte: {data.my_budget.reserved}</span>
              <span>disponibili: <b>{data.my_budget.available}</b></span>
            </div>
          )}
        </div>
        {isAdmin && (
          <Link to="/league-admin?tab=league" className="text-xs text-slate-500 underline">Gestisci sessione →</Link>
        )}
      </div>
      {s.status === 'suspended' && (
        <div className="mt-2 text-sm text-amber-600">Sessione sospesa: le offerte sono temporaneamente bloccate.</div>
      )}
    </Card>
  );
}

function OfferPanel({
  data, nowMs, busy, targetId, onPick, onClearTarget, onOffer,
}: {
  data: MarketActive;
  nowMs: number;
  busy: boolean;
  targetId: number | null;
  onPick: (playerId: number) => void;
  onClearTarget: () => void;
  onOffer: (targetId: number, releaseId: number, amount: number) => void;
}) {
  const [releaseId, setReleaseId] = useState<number | null>(null);
  const [amount, setAmount] = useState<number>(1);

  const freeAgents = data.free_agents ?? [];
  const roster = data.my_roster ?? [];
  const available = data.my_budget?.available ?? 0;

  const target = useMemo(() => freeAgents.find((f) => f.player_id === targetId) ?? null, [freeAgents, targetId]);
  const pledged = useMemo(
    () => new Set((data.my_offers ?? []).filter((o) => o.status === 'leading' || o.status === 'accepted').map((o) => o.release_player_id)),
    [data.my_offers],
  );
  const releaseOptions = useMemo(
    () => (target ? roster.filter((p) => p.role === target.role && !pledged.has(p.player_id)) : []),
    [roster, target, pledged],
  );
  const release = releaseOptions.find((p) => p.player_id === releaseId) ?? null;
  const maxAmount = release ? available + release.recovery : available;
  const minAmount = target?.leading ? target.leading.amount + 1 : 1;

  useEffect(() => {
    setReleaseId(null);
    setAmount(target?.leading ? target.leading.amount + 1 : 1);
  }, [target?.player_id, target?.leading?.amount]);

  const valid = !!target && !!release && amount >= minAmount && amount <= maxAmount && !target.locked;

  return (
    <Card className="p-4">
      <div id="offer-panel">
        <SectionTitle>Fai un’offerta</SectionTitle>
      </div>
      {!target ? (
        // Il giocatore si sceglie qui dentro: cercare e offrire sono lo stesso
        // gesto, e mandare l'utente a caccia del nome in un elenco a parte per
        // poi riportarlo su era un giro inutile.
        <div className="mt-3">
          <FreeAgentSearch data={data} nowMs={nowMs} onPick={onPick}
            emptyHint="Scrivi il nome di uno svincolato (o scegli un ruolo) per offrire su di lui." />
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge tone="blue">{target.role}</Badge>
            <b>{target.name}</b>
            {target.leading && (
              <span className="text-slate-500">
                · in testa {target.leading.team_name} a <b>{target.leading.amount}</b> · scade tra {countdown(target.leading.deadline_at, nowMs)}
              </span>
            )}
            {target.locked && <Badge tone="amber">in definizione</Badge>}
            <button className="text-xs text-slate-500 underline" onClick={onClearTarget}>cambia giocatore</button>
          </div>
          <label className="block text-sm">
            <span className="text-slate-600">Svincola (stesso ruolo)</span>
            <select className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
              value={releaseId ?? ''} onChange={(e) => setReleaseId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">— scegli —</option>
              {releaseOptions.map((p) => (
                <option key={p.player_id} value={p.player_id}>
                  {p.name} (pagato {p.price} → recuperi {p.recovery})
                </option>
              ))}
            </select>
            {releaseOptions.length === 0 && (
              <span className="mt-1 block text-xs text-amber-600">Nessun {target.role} svincolabile nella tua rosa.</span>
            )}
          </label>
          <div className="flex flex-wrap items-end gap-3">
            <label className="block text-sm">
              <span className="text-slate-600">Offerta (crediti)</span>
              <input type="number" min={minAmount} max={maxAmount}
                className="mt-1 w-32 rounded-xl border border-slate-200 px-3 py-2 text-sm"
                value={amount} onChange={(e) => setAmount(Number(e.target.value))} />
            </label>
            <div className="text-sm text-slate-600">
              Tetto: <b>{release ? maxAmount : '—'}</b>
              {release && <span className="text-slate-500"> ({available} disp. + {release.recovery} recupero)</span>}
              {target.leading && <span className="text-slate-500"> · minimo rilancio {minAmount}</span>}
            </div>
          </div>
          <div className="flex gap-2">
            <Button disabled={!valid || busy}
              onClick={() => target && release && onOffer(target.player_id, release.player_id, amount)}>
              {target.leading ? 'Rilancia' : 'Offri'}
            </Button>
            <Button variant="ghost" onClick={onClearTarget}>Annulla</Button>
          </div>
        </div>
      )}
    </Card>
  );
}

function MyOffersCard({ offers, nowMs }: { offers: MarketOfferRow[]; nowMs: number }) {
  if (offers.length === 0) return null;
  return (
    <Card className="p-4">
      <SectionTitle>Le mie offerte</SectionTitle>
      <div className="mt-2 divide-y divide-slate-100">
        {offers.map((o) => (
          <div key={o.offer_id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <div>
              <Badge tone="blue">{o.role}</Badge>{' '}
              <b>{o.target_name}</b> <span className="text-slate-500">← svincoli {o.release_name}</span>
            </div>
            <div className="flex items-center gap-3">
              <span>{o.amount} cr <span className="text-slate-400">(recupero {o.recovery})</span></span>
              {o.status === 'leading' && <span className="text-slate-500">scade tra {countdown(o.deadline_at, nowMs)}</span>}
              <Badge tone={OFFER_TONE[o.status]}>{OFFER_LABEL[o.status]}</Badge>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

/** Una riga di svincolato: nome, ruolo, chi e' in testa, e il bottone per offrire. */
function FreeAgentRow({
  f, nowMs, canOffer, onPick,
}: {
  f: MarketFreeAgent;
  nowMs: number;
  canOffer: boolean;
  onPick: (playerId: number) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
      <div className="min-w-0">
        <Badge tone="blue">{f.role}</Badge> <b>{f.name}</b>
        {f.leading && (
          <span className="ml-2 text-slate-500">
            in testa {f.leading.mine ? <b className="text-emerald-700">tu</b> : f.leading.team_name} a <b>{f.leading.amount}</b>
            {' · '}scade tra <span className="tabular-nums">{countdown(f.leading.deadline_at, nowMs)}</span>
          </span>
        )}
        {f.locked && <span className="ml-2"><Badge tone="amber">in validazione</Badge></span>}
      </div>
      <div className="flex items-center gap-2">
        {canOffer && !f.locked && !f.leading?.mine && (
          <Button size="sm" variant={f.leading ? 'secondary' : 'primary'} onClick={() => onPick(f.player_id)}>
            {f.leading ? 'Rilancia' : 'Offri'}
          </Button>
        )}
        {canOffer && f.leading?.mine && <Badge tone="green">tua</Badge>}
      </div>
    </div>
  );
}

/** Cio' su cui si sta giocando adesso: le uniche righe che vale la pena guardare
 *  senza cercare nulla. In cima chi sta per scadere. */
function LiveContestsCard({
  data, nowMs, onPick,
}: {
  data: MarketActive;
  nowMs: number;
  onPick: (playerId: number) => void;
}) {
  const canOffer = data.session?.status === 'open' && data.my_team_id != null;
  const contests = useMemo(() => {
    const rows = (data.free_agents ?? []).filter((f) => f.leading || f.locked);
    // Le bloccate (offerta accettata, in attesa dell'admin) non hanno piu' un
    // countdown: stanno in fondo, non c'e' nulla da fare su di esse.
    return rows.sort((a, b) => {
      if (!!a.locked !== !!b.locked) return a.locked ? 1 : -1;
      return (a.leading?.deadline_at ?? '').localeCompare(b.leading?.deadline_at ?? '');
    });
  }, [data.free_agents]);

  const mine = contests.filter((f) => f.leading?.mine).length;

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <SectionTitle>Offerte in corso ({contests.length})</SectionTitle>
        {mine > 0 && <span className="text-xs text-slate-500">sei in testa su {mine}</span>}
      </div>
      {contests.length === 0 ? (
        <div className="mt-2 text-sm text-slate-500">
          Nessuna offerta aperta. Cerca uno svincolato qui sotto per aprire la prima.
        </div>
      ) : (
        <div className="mt-2 divide-y divide-slate-100">
          {contests.map((f) => (
            <FreeAgentRow key={f.player_id} f={f} nowMs={nowMs} canOffer={canOffer} onPick={onPick} />
          ))}
        </div>
      )}
    </Card>
  );
}

/** Le trattative gia' decise in questa sessione: chi ha preso chi, e a quanto. */
function ClosedOffersCard({ offers }: { offers: MarketOfferRow[] }) {
  const [open, setOpen] = useState(false);
  if (offers.length === 0) return null;
  const settled = offers.filter((o) => o.status === 'settled');
  const shown = open ? offers : offers.slice(0, 5);
  return (
    <Card className="p-4">
      <button className="flex w-full items-baseline justify-between" onClick={() => setOpen((v) => !v)}>
        <SectionTitle>Offerte concluse ({offers.length})</SectionTitle>
        <span className="text-xs text-slate-500">
          {settled.length} acquisti{offers.length > 5 && (open ? ' · mostra meno' : ' · mostra tutte')}
        </span>
      </button>
      <div className="mt-2 divide-y divide-slate-100">
        {shown.map((o) => (
          <div key={o.offer_id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <div className="min-w-0">
              <Badge tone="blue">{o.role}</Badge> <b>{o.target_name}</b>
              <span className="ml-2 text-slate-500">
                {o.status === 'settled' ? 'a' : 'offerto da'} {o.team_name}
                <span className="text-slate-400"> · svincolato {o.release_name}</span>
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span>{o.amount} cr</span>
              <Badge tone={OFFER_TONE[o.status]}>{OFFER_LABEL[o.status]}</Badge>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

/** Gli svincolati sono centinaia: elencarli tutti nasconde le offerte invece di
 *  mostrarle. Qui si arriva sapendo chi si vuole, quindi si parte dalla ricerca
 *  e la lista compare solo dopo. Senza cornice: sta dentro "Fai un'offerta"
 *  quando si puo' offrire, e in una card sua quando si puo' solo guardare. */
function FreeAgentSearch({
  data, nowMs, onPick, emptyHint,
}: {
  data: MarketActive;
  nowMs: number;
  onPick: (playerId: number) => void;
  emptyHint: string;
}) {
  const [q, setQ] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('');
  const freeAgents = data.free_agents ?? [];
  const canOffer = data.session?.status === 'open' && data.my_team_id != null;
  const searching = q.trim().length > 0 || roleFilter !== '';

  const filtered = useMemo(() => {
    if (!searching) return [];
    // Nome corto E nome esteso, senza accenti: la lista mostra "L. Martínez",
    // molti si cercano per nome di battesimo, e nessuno digita "Leão".
    return freeAgents.filter(
      (f) => (!roleFilter || f.role === roleFilter) && foldedMatch(q, [f.name, f.full_name]),
    );
  }, [freeAgents, q, roleFilter, searching]);

  const byRole = useMemo(() => {
    const m = new Map<string, MarketFreeAgent[]>();
    for (const f of filtered) {
      const k = f.role ?? '?';
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(f);
    }
    return m;
  }, [filtered]);

  return (
    <>
      <div className="flex flex-wrap gap-2">
        <input autoComplete="off" placeholder="Nome del giocatore…"
          className="min-w-0 flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm"
          value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="rounded-xl border border-slate-200 px-2 py-2 text-sm"
          value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
          <option value="">Tutti i ruoli</option>
          {ROLE_ORDER.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
        </select>
        {searching && (
          <Button variant="ghost" size="sm" onClick={() => { setQ(''); setRoleFilter(''); }}>Pulisci</Button>
        )}
      </div>

      {!searching ? (
        <div className="mt-3 text-sm text-slate-500">
          {freeAgents.length} svincolati disponibili. {emptyHint}
        </div>
      ) : filtered.length === 0 ? (
        <div className="mt-3 text-sm text-slate-500">
          Nessuno svincolato corrisponde. Chi è già in una rosa non compare qui.
        </div>
      ) : (
        <div className="mt-3 space-y-4">
          <div className="text-xs text-slate-400">{filtered.length} risultati</div>
          {ROLE_ORDER.filter((r) => byRole.has(r)).map((r) => (
            <div key={r}>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{ROLE_LABEL[r]}</div>
              <div className="mt-1 divide-y divide-slate-100">
                {byRole.get(r)!.slice(0, 30).map((f) => (
                  <FreeAgentRow key={f.player_id} f={f} nowMs={nowMs} canOffer={canOffer} onPick={onPick} />
                ))}
                {byRole.get(r)!.length > 30 && (
                  <div className="py-2 text-xs text-slate-400">…e altri {byRole.get(r)!.length - 30}. Affina la ricerca.</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

/** La stessa ricerca per chi non puo' offrire (nessuna squadra, o sessione
 *  sospesa): guardare chi e' libero resta possibile. */
function FreeAgentSearchCard({
  data, nowMs, onPick,
}: {
  data: MarketActive;
  nowMs: number;
  onPick: (playerId: number) => void;
}) {
  return (
    <Card className="p-4">
      <SectionTitle>Cerca uno svincolato</SectionTitle>
      <div className="mt-2">
        <FreeAgentSearch data={data} nowMs={nowMs} onPick={onPick}
          emptyHint="Scrivi un nome (o scegli un ruolo) per trovarli." />
      </div>
    </Card>
  );
}

function HistoryList({ sessions }: { sessions: MarketSessionHistory[] }) {
  return (
    <div className="mt-3 space-y-4">
      {sessions.map((s) => {
        const settled = s.offers.filter((o) => o.status === 'settled');
        return (
          <div key={s.id} className="border-t border-slate-100 pt-3 first:border-0 first:pt-0">
            <div className="flex items-center gap-2 text-sm">
              <b>{s.name}</b>
              <Badge tone={SESSION_TONE[s.status]}>{SESSION_LABEL[s.status]}</Badge>
              <span className="text-xs text-slate-500">{recoveryText(s.credit_recovery_mode, s.fixed_recovery_amount)}</span>
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {s.offers.length} offerte · {settled.length} concluse
            </div>
            {s.offers.length > 0 && (
              <div className="mt-1 divide-y divide-slate-100">
                {s.offers.map((o) => (
                  <div key={o.offer_id} className="flex flex-wrap items-center justify-between gap-2 py-1.5 text-xs">
                    <span>
                      <b>{o.target_name}</b> <span className="text-slate-400">← {o.team_name} / {o.release_name}</span>
                    </span>
                    <span className="flex items-center gap-2">
                      {o.amount} cr <Badge tone={OFFER_TONE[o.status]}>{OFFER_LABEL[o.status]}</Badge>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
