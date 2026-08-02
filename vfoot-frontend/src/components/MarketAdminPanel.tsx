import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ApiError,
  adminMarketOffer,
  controlMarketSession,
  createMarketSession,
  getMarketActive,
} from '../api/backend';
import { Badge, Button, Card, SectionTitle } from './ui';
import { OfferDeadline } from './OfferDeadline';
import {
  SESSION_LABEL,
  SESSION_TONE,
  recoveryText,
} from '../utils/market';
import type { MarketActive, MarketFreeAgent, MarketOfferRow, MarketRecoveryMode } from '../types/market';

/** Admin-side management of the repair market: open/suspend/close a session and
 *  validate the offers that reach it. Self-contained (own data + polling) so it
 *  drops into Gestione lega as a single card. */
export default function MarketAdminPanel({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<MarketActive | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const load = useCallback(async () => {
    try {
      setData(await getMarketActive(leagueId));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Errore nel caricamento del mercato.');
    }
  }, [leagueId]);

  useEffect(() => {
    void load();
    const poll = window.setInterval(() => void load(), 20_000);
    return () => window.clearInterval(poll);
  }, [load]);

  useEffect(() => {
    const t = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const act = useCallback(async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Operazione non riuscita.');
    } finally {
      setBusy(false);
    }
  }, [load]);

  const session = data?.session ?? null;
  const isClassic = data?.mode === 'classic';
  const queue = data?.admin_queue ?? [];
  const leadingOffers = useMemo(
    () => (data?.free_agents ?? []).filter((f) => f.leading).sort((a, b) => (a.leading!.deadline_at ?? '').localeCompare(b.leading!.deadline_at ?? '')),
    [data?.free_agents],
  );

  if (data && !isClassic) {
    return (
      <Card className="p-4">
        <SectionTitle>Mercato di riparazione</SectionTitle>
        <div className="mt-2 text-sm text-slate-600">Disponibile solo per le leghe in <b>modalità classic</b>.</div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {error && <Card className="border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</Card>}

      {session && (
        <>
          <Card className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <SectionTitle>{session.name}</SectionTitle>
                  <Badge tone={SESSION_TONE[session.status]}>{SESSION_LABEL[session.status]}</Badge>
                </div>
                <div className="mt-1 text-sm text-slate-600">
                  Recupero: <b>{recoveryText(session.credit_recovery_mode, session.fixed_recovery_amount)}</b>
                  {' · '}
                  {session.closes_at ? `chiude il ${new Date(session.closes_at).toLocaleString('it-IT')}` : 'chiusura indefinita'}
                </div>
              </div>
              {session.status !== 'closed' && (
                <div className="flex gap-2">
                  {session.status === 'open' ? (
                    <Button size="sm" variant="secondary" disabled={busy} onClick={() => act(() => controlMarketSession(leagueId, session.id, 'suspend'))}>Sospendi</Button>
                  ) : (
                    <Button size="sm" variant="secondary" disabled={busy} onClick={() => act(() => controlMarketSession(leagueId, session.id, 'resume'))}>Riattiva</Button>
                  )}
                  <Button size="sm" variant="danger" disabled={busy}
                    onClick={() => { if (window.confirm('Chiudere la sessione? Ogni offerta ancora in testa passa in validazione, anche se non ha compiuto 24 ore: le troverai qui sotto da accettare o rifiutare.')) void act(() => controlMarketSession(leagueId, session.id, 'close')); }}>
                    Chiudi
                  </Button>
                </div>
              )}
            </div>
            <div className="mt-3 text-xs text-slate-500">
              Le offerte che restano in testa 24h senza rilanci passano in “da validare”. Applicando l’offerta
              il giocatore svincolato lascia la rosa e quello acquistato entra al prezzo offerto.
            </div>
          </Card>
        </>
      )}

      {/* Fuori dal ramo "c'e' una sessione": la coda le sopravvive. */}
      <QueueCard queue={queue} sessionLive={!!session} busy={busy}
        onAccept={(id) => act(() => adminMarketOffer(leagueId, id, 'accept'))}
        onReject={(id) => act(() => adminMarketOffer(leagueId, id, 'reject'))} />

      {session && (
        <>
          <Card className="p-4">
            <SectionTitle>Offerte in testa ({leadingOffers.length})</SectionTitle>
            {leadingOffers.length === 0 ? (
              <div className="mt-2 text-sm text-slate-500">Nessuna offerta attiva al momento.</div>
            ) : (
              <div className="mt-2 divide-y divide-slate-100">
                {leadingOffers.map((f) => (
                  <LeadingRow key={f.player_id} f={f} nowMs={nowMs} busy={busy} closesAt={data?.session?.closes_at}
                    onCancel={() => { if (window.confirm('Annullare l’offerta in testa?')) void act(() => adminMarketOffer(leagueId, f.leading!.offer_id, 'cancel')); }} />
                ))}
              </div>
            )}
          </Card>
        </>
      )}

      {!session && (
        <CreateSessionCard busy={busy} onCreate={(opts) => act(() => createMarketSession(leagueId, opts))} />
      )}
    </div>
  );
}

/** Le offerte che aspettano una decisione.
 *
 *  Sta fuori dal blocco della sessione di proposito: alla chiusura le offerte in
 *  testa finiscono qui dentro, ma la sessione smette di essere "viva" e prima
 *  spariva anche la coda — le offerte restavano accettate e non concluse, senza
 *  nessuna schermata da cui deciderle. Le rose non cambiano finche' non si
 *  accetta, quindi non e' un dettaglio estetico: era lavoro bloccato. */
function QueueCard({ queue, sessionLive, busy, onAccept, onReject }: {
  queue: MarketOfferRow[];
  sessionLive: boolean;
  busy: boolean;
  onAccept: (offerId: number) => void;
  onReject: (offerId: number) => void;
}) {
  // Senza sessione e senza coda non c'e' niente da dire: la card sparisce e
  // resta solo l'invito ad aprire una sessione.
  if (!sessionLive && queue.length === 0) return null;
  const fromClosed = queue.filter((o) => o.session_closed).length;
  return (
    <Card className="p-4">
      <SectionTitle>Offerte da validare ({queue.length})</SectionTitle>
      {queue.length === 0 ? (
        <div className="mt-2 text-sm text-slate-500">Nessuna offerta in attesa.</div>
      ) : (
        <>
          {fromClosed > 0 && (
            <div className="mt-1 text-xs text-amber-600">
              {fromClosed === queue.length ? (fromClosed === 1 ? 'Arriva' : 'Arrivano') : `${fromClosed} arrivano`}
              {' '}da una sessione già chiusa: restano da decidere, e finché non decidi le rose non cambiano.
            </div>
          )}
          <div className="mt-2 divide-y divide-slate-100">
            {queue.map((o) => (
              <QueueRow key={o.offer_id} o={o} busy={busy}
                onAccept={() => onAccept(o.offer_id)} onReject={() => onReject(o.offer_id)} />
            ))}
          </div>
        </>
      )}
    </Card>
  );
}

function QueueRow({ o, busy, onAccept, onReject }: { o: MarketOfferRow; busy: boolean; onAccept: () => void; onReject: () => void }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
      <div>
        <Badge tone="blue">{o.role}</Badge>{' '}
        <b>{o.target_name}</b> <span className="text-slate-500">← {o.team_name} svincola {o.release_name}</span>
        {' · '}<b>{o.amount}</b> cr <span className="text-slate-400">(recupero {o.recovery})</span>
      </div>
      <div className="flex gap-2">
        <Button size="sm" disabled={busy} onClick={onAccept}>Accetta (applica rose)</Button>
        <Button size="sm" variant="danger" disabled={busy} onClick={onReject}>Rifiuta</Button>
      </div>
    </div>
  );
}

function LeadingRow({ f, nowMs, closesAt, busy, onCancel }: {
  f: MarketFreeAgent; nowMs: number; closesAt: string | null | undefined; busy: boolean; onCancel: () => void;
}) {
  const l = f.leading!;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
      <div>
        <Badge tone="blue">{f.role}</Badge>{' '}
        <b>{f.name}</b> <span className="text-slate-500">· {l.team_name} a <b>{l.amount}</b> ·{' '}
          <OfferDeadline deadlineAt={l.deadline_at} sessionClosesAt={closesAt} nowMs={nowMs} /></span>
      </div>
      <Button size="sm" variant="ghost" disabled={busy} onClick={onCancel}>Annulla</Button>
    </div>
  );
}

function CreateSessionCard({
  busy, onCreate,
}: {
  busy: boolean;
  onCreate: (opts: { name?: string; credit_recovery_mode: MarketRecoveryMode; fixed_recovery_amount?: number; closes_at?: string | null }) => void;
}) {
  const [mode, setMode] = useState<MarketRecoveryMode>('frac50');
  const [fixed, setFixed] = useState(1);
  const [name, setName] = useState('Mercato di riparazione');
  const [closesAt, setClosesAt] = useState('');
  const [scheduled, setScheduled] = useState(false);

  return (
    <Card className="p-4">
      <SectionTitle>Apri una sessione di mercato</SectionTitle>
      <div className="mt-1 text-sm text-slate-600">
        Nessuna sessione aperta. Apri una finestra di offerte sugli svincolati; una sola sessione viva per lega.
      </div>
      <div className="mt-4 space-y-3 border-t border-slate-100 pt-4">
        <label className="block text-sm">
          <span className="text-slate-600">Nome</span>
          <input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Recupero crediti dallo svincolo</span>
          <select className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" value={mode} onChange={(e) => setMode(e.target.value as MarketRecoveryMode)}>
            <option value="fixed">Credito fisso</option>
            <option value="frac30">30% del prezzo pagato (arrotondato per eccesso)</option>
            <option value="frac50">50% del prezzo pagato (arrotondato per eccesso)</option>
            <option value="frac75">75% del prezzo pagato (arrotondato per eccesso)</option>
          </select>
        </label>
        {mode === 'fixed' && (
          <label className="block text-sm">
            <span className="text-slate-600">Crediti fissi recuperati</span>
            <input type="number" min={0} className="mt-1 w-32 rounded-xl border border-slate-200 px-3 py-2 text-sm" value={fixed} onChange={(e) => setFixed(Math.max(0, Number(e.target.value)))} />
          </label>
        )}
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={scheduled} onChange={(e) => setScheduled(e.target.checked)} />
          Chiusura programmata (altrimenti indefinita, la chiudi a mano)
        </label>
        {scheduled && (
          <label className="block text-sm">
            <span className="text-slate-600">Data/ora di chiusura</span>
            <input type="datetime-local" className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" value={closesAt} onChange={(e) => setClosesAt(e.target.value)} />
            <span className="mt-1 block text-xs text-slate-500">
              Alla chiusura ogni offerta ancora in testa passa in validazione, anche se
              non ha compiuto le sue 24 ore: aspettarsi rilanci sul filo è normale.
            </span>
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
    </Card>
  );
}
