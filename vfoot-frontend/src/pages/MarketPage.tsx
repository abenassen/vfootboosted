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
  }, [selectedLeagueId]);

  useEffect(() => {
    if (!selectedLeagueId) {
      setData(null);
      setAuction(null);
      return;
    }
    void refresh();
    void getActiveAuction(selectedLeagueId).then(setAuction).catch(() => setAuction(null));
    void getMarketSessions(selectedLeagueId).then((r) => setHistory(r.sessions)).catch(() => setHistory([]));
    const poll = window.setInterval(() => void refresh(), 20_000);
    return () => window.clearInterval(poll);
  }, [selectedLeagueId, refresh]);

  useEffect(() => {
    const t = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const reloadAll = useCallback(async () => {
    await refresh();
    if (selectedLeagueId) {
      void getMarketSessions(selectedLeagueId).then((r) => setHistory(r.sessions)).catch(() => undefined);
    }
  }, [refresh, selectedLeagueId]);

  const act = useCallback(
    async (fn: () => Promise<unknown>) => {
      setBusy(true);
      setError(null);
      try {
        await fn();
        await reloadAll();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'Operazione non riuscita.');
      } finally {
        setBusy(false);
      }
    },
    [reloadAll],
  );

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega per vedere il mercato.</div>;

  const session = data?.session ?? null;
  const isClassic = (data?.mode ?? auction?.mode) === 'classic';
  const isAdmin = !!data?.is_admin;

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

          {session.status === 'open' && data?.my_team_id != null && (
            <OfferPanel data={data!} nowMs={nowMs} busy={busy}
              targetId={targetId} onClearTarget={() => setTargetId(null)}
              onOffer={(t, r, a) => act(async () => { await placeMarketOffer(selectedLeagueId, t, r, a); setTargetId(null); })} />
          )}

          <MyOffersCard offers={data?.my_offers ?? []} nowMs={nowMs} />

          <FreeAgentsCard data={data!} nowMs={nowMs} onPick={pickTarget} />
        </>
      )}

      {history.length > 0 && (
        <Card className="p-4">
          <button className="flex w-full items-center justify-between" onClick={() => setShowHistory((v) => !v)}>
            <SectionTitle>Storico sessioni ({history.length})</SectionTitle>
            <span className="text-xs text-slate-500">{showHistory ? 'nascondi' : 'mostra'}</span>
          </button>
          {showHistory && <HistoryList sessions={history} />}
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
  data, nowMs, busy, targetId, onClearTarget, onOffer,
}: {
  data: MarketActive;
  nowMs: number;
  busy: boolean;
  targetId: number | null;
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
        <div className="mt-2 text-sm text-slate-500">Scegli uno svincolato dalla lista sotto e premi “Offri”.</div>
      ) : (
        <div className="mt-3 space-y-3">
          <div className="flex items-center gap-2 text-sm">
            <Badge tone="blue">{target.role}</Badge>
            <b>{target.name}</b>
            {target.leading && (
              <span className="text-slate-500">
                · in testa {target.leading.team_name} a <b>{target.leading.amount}</b> · scade tra {countdown(target.leading.deadline_at, nowMs)}
              </span>
            )}
            {target.locked && <Badge tone="amber">in definizione</Badge>}
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

function FreeAgentsCard({
  data, nowMs, onPick,
}: {
  data: MarketActive;
  nowMs: number;
  onPick: (playerId: number) => void;
}) {
  const [q, setQ] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('');
  const freeAgents = data.free_agents ?? [];
  const canOffer = data.session?.status === 'open' && data.my_team_id != null;

  const filtered = useMemo(() => {
    // Short AND full name, ignoring accents: the list shows "L. Martínez", plenty
    // of players are known by the first name, and nobody types "Leão".
    return freeAgents.filter(
      (f) => (!roleFilter || f.role === roleFilter) && foldedMatch(q, [f.name, f.full_name]),
    );
  }, [freeAgents, q, roleFilter]);

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
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SectionTitle>Svincolati ({freeAgents.length})</SectionTitle>
        <div className="flex gap-2">
          <select className="rounded-xl border border-slate-200 px-2 py-1.5 text-xs"
            value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
            <option value="">Tutti i ruoli</option>
            {ROLE_ORDER.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
          <input placeholder="Cerca…" className="rounded-xl border border-slate-200 px-3 py-1.5 text-xs"
            value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>
      <div className="mt-3 space-y-4">
        {ROLE_ORDER.filter((r) => byRole.has(r)).map((r) => (
          <div key={r}>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{ROLE_LABEL[r]}</div>
            <div className="mt-1 divide-y divide-slate-100">
              {byRole.get(r)!.slice(0, 100).map((f) => (
                <div key={f.player_id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <div className="min-w-0">
                    <b className="truncate">{f.name}</b>
                    {f.leading && (
                      <span className="ml-2 text-slate-500">
                        in testa {f.leading.mine ? <Badge tone="green">tua</Badge> : f.leading.team_name} a <b>{f.leading.amount}</b>
                        {' · '}scade tra {countdown(f.leading.deadline_at, nowMs)}
                      </span>
                    )}
                    {f.locked && <Badge tone="amber">in definizione</Badge>}
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
              ))}
              {byRole.get(r)!.length > 100 && (
                <div className="py-2 text-xs text-slate-400">…e altri {byRole.get(r)!.length - 100}. Affina la ricerca.</div>
              )}
            </div>
          </div>
        ))}
        {filtered.length === 0 && <div className="text-sm text-slate-500">Nessuno svincolato corrisponde.</div>}
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
