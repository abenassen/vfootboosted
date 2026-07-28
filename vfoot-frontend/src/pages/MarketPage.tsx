import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ApiError,
  adminMarketOffer,
  controlMarketSession,
  createMarketSession,
  getMarketActive,
  getMarketSessions,
  placeMarketOffer,
} from '../api/backend';
import { getActiveAuction } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type {
  MarketActive,
  MarketFreeAgent,
  MarketOfferRow,
  MarketRecoveryMode,
  MarketSessionHistory,
} from '../types/market';
import type { ActiveAuctionInfo } from '../types/league';

const ROLE_LABEL: Record<string, string> = { POR: 'Portieri', DIF: 'Difensori', CEN: 'Centrocampisti', ATT: 'Attaccanti' };
const ROLE_ORDER = ['POR', 'DIF', 'CEN', 'ATT'];

const RECOVERY_LABEL: Record<MarketRecoveryMode, string> = {
  fixed: 'credito fisso',
  frac30: '30% del prezzo pagato',
  frac50: '50% del prezzo pagato',
  frac75: '75% del prezzo pagato',
};

function recoveryText(mode: MarketRecoveryMode, fixed: number): string {
  return mode === 'fixed' ? `${fixed} credito${fixed === 1 ? '' : 'i'} fisso` : RECOVERY_LABEL[mode];
}

function countdown(deadlineIso: string | null, nowMs: number): string {
  if (!deadlineIso) return '—';
  const ms = new Date(deadlineIso).getTime() - nowMs;
  if (ms <= 0) return 'in validazione';
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

const OFFER_TONE: Record<string, 'green' | 'amber' | 'slate' | 'red' | 'blue'> = {
  leading: 'blue',
  accepted: 'amber',
  settled: 'green',
  outbid: 'slate',
  rejected: 'red',
  cancelled: 'slate',
};
const OFFER_LABEL: Record<string, string> = {
  leading: 'in testa',
  accepted: 'accettata',
  settled: 'conclusa',
  outbid: 'superata',
  rejected: 'rifiutata',
  cancelled: 'annullata',
};

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
    // Defer so the panel is rendered before we scroll to it.
    window.setTimeout(() => document.getElementById('offer-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 0);
  }, []);

  const refresh = useCallback(async () => {
    if (!selectedLeagueId) return;
    try {
      const active = await getMarketActive(selectedLeagueId);
      setData(active);
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

  // Local 1s tick drives the live countdowns without hammering the server.
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

  const isAdmin = !!data?.is_admin;
  const session = data?.session ?? null;
  const isClassic = (data?.mode ?? auction?.mode) === 'classic';

  return (
    <div className="space-y-4">
      {error && (
        <Card className="border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</Card>
      )}

      {!isClassic ? (
        <Card className="p-4">
          <SectionTitle>Mercato</SectionTitle>
          <div className="mt-2 text-sm text-slate-600">
            Il mercato a offerte è disponibile solo per le leghe in <b>modalità classic</b>.
          </div>
        </Card>
      ) : !session ? (
        <NoSessionCard isAdmin={isAdmin} busy={busy} onCreate={(opts) => act(() => createMarketSession(selectedLeagueId, opts))} auction={auction} />
      ) : (
        <>
          <SessionHeader
            data={data!}
            busy={busy}
            onControl={(action) => act(() => controlMarketSession(selectedLeagueId, session.id, action))}
          />

          {session.status === 'open' && data?.my_team_id != null && (
            <OfferPanel data={data!} nowMs={nowMs} busy={busy}
              targetId={targetId} onClearTarget={() => setTargetId(null)}
              onOffer={(t, r, a) => act(async () => { await placeMarketOffer(selectedLeagueId, t, r, a); setTargetId(null); })} />
          )}

          <MyOffersCard offers={data?.my_offers ?? []} nowMs={nowMs} />

          {isAdmin && (
            <AdminQueueCard
              queue={data?.admin_queue ?? []}
              busy={busy}
              onAccept={(oid) => act(() => adminMarketOffer(selectedLeagueId, oid, 'accept'))}
              onReject={(oid) => act(() => adminMarketOffer(selectedLeagueId, oid, 'reject'))}
            />
          )}

          <FreeAgentsCard
            data={data!}
            nowMs={nowMs}
            isAdmin={isAdmin}
            busy={busy}
            onPick={pickTarget}
            onCancelLeading={(oid) => act(() => adminMarketOffer(selectedLeagueId, oid, 'cancel'))}
          />
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

function NoSessionCard({
  isAdmin, busy, onCreate, auction,
}: {
  isAdmin: boolean;
  busy: boolean;
  onCreate: (opts: { name?: string; credit_recovery_mode: MarketRecoveryMode; fixed_recovery_amount?: number; closes_at?: string | null }) => void;
  auction: ActiveAuctionInfo | null;
}) {
  const [mode, setMode] = useState<MarketRecoveryMode>('frac50');
  const [fixed, setFixed] = useState(1);
  const [name, setName] = useState('Mercato di riparazione');
  const [closesAt, setClosesAt] = useState('');
  const [scheduled, setScheduled] = useState(false);
  const liveAuction = !!auction?.auction_id;

  return (
    <Card className="p-4">
      <SectionTitle>Mercato di riparazione</SectionTitle>
      <div className="mt-2 text-sm text-slate-600">
        Nessuna sessione di mercato aperta. {liveAuction && 'C’è un’asta in corso: '}
        {liveAuction && <Link to="/auction" className="font-semibold text-slate-900 underline">entra nella sala asta →</Link>}
      </div>
      {isAdmin ? (
        <div className="mt-4 space-y-3 border-t border-slate-100 pt-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Apri una sessione</div>
          <label className="block text-sm">
            <span className="text-slate-600">Nome</span>
            <input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
              value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Recupero crediti dallo svincolo</span>
            <select className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
              value={mode} onChange={(e) => setMode(e.target.value as MarketRecoveryMode)}>
              <option value="fixed">Credito fisso</option>
              <option value="frac30">30% del prezzo pagato (arrotondato per eccesso)</option>
              <option value="frac50">50% del prezzo pagato (arrotondato per eccesso)</option>
              <option value="frac75">75% del prezzo pagato (arrotondato per eccesso)</option>
            </select>
          </label>
          {mode === 'fixed' && (
            <label className="block text-sm">
              <span className="text-slate-600">Crediti fissi recuperati</span>
              <input type="number" min={0} className="mt-1 w-32 rounded-xl border border-slate-200 px-3 py-2 text-sm"
                value={fixed} onChange={(e) => setFixed(Math.max(0, Number(e.target.value)))} />
            </label>
          )}
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={scheduled} onChange={(e) => setScheduled(e.target.checked)} />
            Chiusura programmata (altrimenti indefinita, la chiudi a mano)
          </label>
          {scheduled && (
            <label className="block text-sm">
              <span className="text-slate-600">Data/ora di chiusura</span>
              <input type="datetime-local" className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                value={closesAt} onChange={(e) => setClosesAt(e.target.value)} />
            </label>
          )}
          <Button disabled={busy || (scheduled && !closesAt)}
            onClick={() => onCreate({
              name: name.trim() || undefined,
              credit_recovery_mode: mode,
              fixed_recovery_amount: mode === 'fixed' ? fixed : undefined,
              closes_at: scheduled && closesAt ? new Date(closesAt).toISOString() : null,
            })}>
            Apri sessione
          </Button>
        </div>
      ) : (
        <div className="mt-2 text-sm text-slate-500">Quando l’admin apre una sessione potrai fare offerte sugli svincolati.</div>
      )}
    </Card>
  );
}

function SessionHeader({
  data, busy, onControl,
}: {
  data: MarketActive;
  busy: boolean;
  onControl: (action: 'suspend' | 'resume' | 'close') => void;
}) {
  const s = data.session!;
  const tone = s.status === 'open' ? 'green' : s.status === 'suspended' ? 'amber' : 'slate';
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <SectionTitle>{s.name}</SectionTitle>
            <Badge tone={tone}>{s.status === 'open' ? 'aperta' : s.status === 'suspended' ? 'sospesa' : 'chiusa'}</Badge>
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
        {data.is_admin && s.status !== 'closed' && (
          <div className="flex gap-2">
            {s.status === 'open' ? (
              <Button size="sm" variant="secondary" disabled={busy} onClick={() => onControl('suspend')}>Sospendi</Button>
            ) : (
              <Button size="sm" variant="secondary" disabled={busy} onClick={() => onControl('resume')}>Riattiva</Button>
            )}
            <Button size="sm" variant="danger" disabled={busy}
              onClick={() => { if (window.confirm('Chiudere la sessione? Le offerte in testa non ancora scadute saranno annullate.')) onControl('close'); }}>
              Chiudi
            </Button>
          </div>
        )}
      </div>
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
  // Roster players eligible as the release for the chosen target: same role, not
  // already committed to another live offer of mine.
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

  // When the picked target changes, reset the release choice and seed the amount
  // to the minimum legal value (1, or one credit over the current leader).
  useEffect(() => {
    setReleaseId(null);
    setAmount(target?.leading ? target.leading.amount + 1 : 1);
  }, [target?.player_id, target?.leading?.amount]);

  const valid = !!target && !!release && amount >= minAmount && amount <= maxAmount && !target.locked;

  return (
    <Card className="p-4" >
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

function AdminQueueCard({
  queue, busy, onAccept, onReject,
}: {
  queue: MarketOfferRow[];
  busy: boolean;
  onAccept: (oid: number) => void;
  onReject: (oid: number) => void;
}) {
  return (
    <Card className="p-4">
      <SectionTitle>Offerte da validare ({queue.length})</SectionTitle>
      {queue.length === 0 ? (
        <div className="mt-2 text-sm text-slate-500">Nessuna offerta in attesa. Le offerte scadute senza rilanci compaiono qui.</div>
      ) : (
        <div className="mt-2 divide-y divide-slate-100">
          {queue.map((o) => (
            <div key={o.offer_id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
              <div>
                <Badge tone="blue">{o.role}</Badge>{' '}
                <b>{o.target_name}</b> <span className="text-slate-500">← {o.team_name} svincola {o.release_name}</span>
                {' · '}<b>{o.amount}</b> cr
              </div>
              <div className="flex gap-2">
                <Button size="sm" disabled={busy} onClick={() => onAccept(o.offer_id)}>Accetta (applica rose)</Button>
                <Button size="sm" variant="danger" disabled={busy} onClick={() => onReject(o.offer_id)}>Rifiuta</Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function FreeAgentsCard({
  data, nowMs, isAdmin, busy, onPick, onCancelLeading,
}: {
  data: MarketActive;
  nowMs: number;
  isAdmin: boolean;
  busy: boolean;
  onPick: (playerId: number) => void;
  onCancelLeading: (offerId: number) => void;
}) {
  const [q, setQ] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('');
  const freeAgents = data.free_agents ?? [];
  const canOffer = data.session?.status === 'open' && data.my_team_id != null;

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return freeAgents.filter((f) =>
      (!roleFilter || f.role === roleFilter) &&
      (!needle || (f.name ?? '').toLowerCase().includes(needle)));
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
                      <Button size="sm" variant={f.leading ? 'secondary' : 'primary'}
                        onClick={() => onPick(f.player_id)}>
                        {f.leading ? 'Rilancia' : 'Offri'}
                      </Button>
                    )}
                    {canOffer && f.leading?.mine && <Badge tone="green">tua</Badge>}
                    {isAdmin && f.leading && (
                      <Button size="sm" variant="ghost" disabled={busy}
                        onClick={() => { if (window.confirm('Annullare l’offerta in testa?')) onCancelLeading(f.leading!.offer_id); }}>
                        Annulla
                      </Button>
                    )}
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
              <Badge tone={s.status === 'closed' ? 'slate' : s.status === 'open' ? 'green' : 'amber'}>
                {s.status === 'closed' ? 'chiusa' : s.status === 'open' ? 'aperta' : 'sospesa'}
              </Badge>
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
