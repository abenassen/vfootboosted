import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ApiError,
  adminMarketOffer,
  controlMarketSession,
  createMarketSession,
  getMarketActive,
  getMarketDiscardPreview,
  serverNow,
} from '../api/backend';
import { Badge, Button, Card, SectionTitle } from './ui';
import { OfferDeadline } from './OfferDeadline';
import { CURRENCY_NAME_PLURAL, price } from '../utils/currency';
import {
  SESSION_LABEL,
  SESSION_TONE,
  countdown,
  elapsedSince,
  recoveryText,
  sessionPhase,
  stamp,
} from '../utils/market';
import type {
  MarketActive, MarketDiscardPreview, MarketFreeAgent, MarketOfferRow, MarketRecoveryMode,
} from '../types/market';

/** Che fare dell'offerta che quella tolta di mezzo aveva superato. `undefined`
 *  quando non c'era nessun rilancio e non c'e' niente da decidere. */
type Discard = { offerId: number; action: 'cancel' | 'reject'; restore?: boolean };

/** Admin-side management of the repair market: open/suspend/close a session and
 *  validate the offers that reach it. Self-contained (own data + polling) so it
 *  drops into Gestione lega as a single card. */
export default function MarketAdminPanel({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<MarketActive | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [nowMs, setNowMs] = useState(() => serverNow());

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
    const t = window.setInterval(() => setNowMs(serverNow()), 1000);
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

  // Togliere di mezzo un'offerta (annullarla o rifiutarla) passa sempre di qui,
  // con la decisione gia' presa sull'offerta che c'era sotto: senza, il server
  // risponde 409 e non tocca niente.
  const discard = useCallback(({ offerId, action, restore }: Discard) => act(
    () => adminMarketOffer(leagueId, offerId, action, restore),
  ), [act, leagueId]);

  const session = data?.session ?? null;
  // "aperta" con l'ora di apertura ancora da venire vuol dire programmata: e'
  // lo stato che l'admin deve vedere, ed e' quello che decide i bottoni.
  const phase = session ? sessionPhase(session, nowMs) : null;
  const isClassic = data?.mode === 'classic';
  const queue = data?.admin_queue ?? [];
  // La giornata vera, non il registro della lega. Non spegne piu' niente:
  // validare mentre si gioca e' ammesso, e serve a dire all'admin che cosa
  // succedera' alle formazioni (niente, fino al turno dopo).
  const frozen = !!data?.matchday_in_progress;
  const playingMd = data?.playing_matchday ?? null;
  const leadingOffers = useMemo(
    () => (data?.free_agents ?? []).filter((f) => f.leading).sort((a, b) => (a.leading!.deadline_at ?? '').localeCompare(b.leading!.deadline_at ?? '')),
    [data?.free_agents],
  );

  if (data && !isClassic) {
    return (
      <Card className="p-4">
        <SectionTitle>Mercato di riparazione</SectionTitle>
        <div className="mt-2 text-sm text-ink-soft">Disponibile solo per le leghe in <b>modalità classic</b>.</div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {error && <Card className="border border-bad/40 bg-bad-bg p-3 text-sm text-bad">{error}</Card>}

      {session && (
        <>
          <Card className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <SectionTitle>{session.name}</SectionTitle>
                  <Badge tone={SESSION_TONE[phase!]}>{SESSION_LABEL[phase!]}</Badge>
                </div>
                <div className="mt-1 text-sm text-ink-soft">
                  {phase === 'scheduled' && (
                    <>
                      Apre il <b>{stamp(session.opens_at)}</b>{' '}
                      <span className="text-ink-faint">
                        (tra <span className="tabular-nums">{countdown(session.opens_at, nowMs, 'un istante')}</span>)
                      </span>
                      {' · '}
                    </>
                  )}
                  Recupero: <b>{recoveryText(session.credit_recovery_mode, session.fixed_recovery_amount)}</b>
                  {' · '}
                  {session.closes_at ? `chiude il ${stamp(session.closes_at)}` : 'chiusura indefinita'}
                </div>
              </div>
              {session.status !== 'closed' && (
                <div className="flex gap-2">
                  {/* Niente "Sospendi" su una sessione che non e' ancora cominciata:
                      non c'e' nulla da fermare, e l'unica cosa sensata da farne e'
                      disdirla. */}
                  {phase !== 'scheduled' && (session.status === 'open' ? (
                    <Button size="sm" variant="secondary" disabled={busy} onClick={() => act(() => controlMarketSession(leagueId, session.id, 'suspend'))}>Sospendi</Button>
                  ) : (
                    <Button size="sm" variant="secondary" disabled={busy} onClick={() => act(() => controlMarketSession(leagueId, session.id, 'resume'))}>Riattiva</Button>
                  ))}
                  <Button size="sm" variant="danger" disabled={busy}
                    onClick={() => {
                      const ask = phase === 'scheduled'
                        ? 'Annullare il mercato programmato? La lega smetterà di vederlo in arrivo, e potrai riprogrammarlo quando vuoi.'
                        : 'Chiudere la sessione? Ogni offerta ancora in testa passa in validazione, anche se non ha compiuto 24 ore: le troverai qui sotto da accettare o rifiutare.';
                      if (window.confirm(ask)) void act(() => controlMarketSession(leagueId, session.id, 'close'));
                    }}>
                    {phase === 'scheduled' ? 'Annulla' : 'Chiudi'}
                  </Button>
                </div>
              )}
            </div>
            <div className="mt-3 text-xs text-ink-faint">
              {phase === 'scheduled' ? (
                <>La lega la vede già in arrivo, col conto alla rovescia: puoi annunciarla adesso.
                  Fino all’ora fissata si guardano gli svincolati, ma non si offre.</>
              ) : (
                <>Le offerte che restano in testa 24h senza rilanci passano in “da validare”. Applicando l’offerta
                  il giocatore svincolato lascia la rosa e quello acquistato entra al prezzo offerto.</>
              )}
            </div>
          </Card>
        </>
      )}

      {/* Fuori dal ramo "c'e' una sessione": la coda le sopravvive. */}
      {/* `sessionLive` decide se la card resta a vuoto: prima dell'apertura non
          c'e' nessuna coda da questa sessione, e se ne arriva una da quella
          precedente e' `queue` a tenerla in piedi. */}
      <QueueCard queue={queue} sessionLive={!!session && phase !== 'scheduled'} busy={busy}
        leagueId={leagueId} nowMs={nowMs} frozen={frozen} playingMd={playingMd}
        onAccept={(id) => act(() => adminMarketOffer(leagueId, id, 'accept'))}
        onDiscard={discard} />

      {/* Prima dell'apertura non ci sono offerte da guardare: la card direbbe
          soltanto "nessuna", ogni volta. */}
      {session && phase !== 'scheduled' && (
        <>
          <Card className="p-4">
            <SectionTitle>Offerte in testa ({leadingOffers.length})</SectionTitle>
            {leadingOffers.length === 0 ? (
              <div className="mt-2 text-sm text-ink-faint">Nessuna offerta attiva al momento.</div>
            ) : (
              <div className="mt-2 divide-y divide-line">
                {leadingOffers.map((f) => (
                  <LeadingRow key={f.player_id} f={f} nowMs={nowMs} busy={busy} closesAt={data?.session?.closes_at}
                    leagueId={leagueId} onDiscard={discard} />
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
function QueueCard({ queue, sessionLive, busy, leagueId, nowMs, frozen, playingMd, onAccept, onDiscard }: {
  queue: MarketOfferRow[];
  sessionLive: boolean;
  busy: boolean;
  leagueId: number;
  nowMs: number;
  frozen: boolean;
  playingMd: number | null;
  onAccept: (offerId: number) => void;
  onDiscard: (d: Discard) => void;
}) {
  // Senza sessione e senza coda non c'e' niente da dire: la card sparisce e
  // resta solo l'invito ad aprire una sessione.
  if (!sessionLive && queue.length === 0) return null;
  const fromClosed = queue.filter((o) => o.session_closed).length;
  return (
    <Card className="p-4">
      <SectionTitle>Offerte da validare ({queue.length})</SectionTitle>
      {queue.length === 0 ? (
        <div className="mt-2 text-sm text-ink-faint">Nessuna offerta in attesa.</div>
      ) : (
        <>
          {fromClosed > 0 && (
            <div className="mt-1 text-xs text-warn">
              {fromClosed === queue.length ? (fromClosed === 1 ? 'Arriva' : 'Arrivano') : `${fromClosed} arrivano`}
              {' '}da una sessione già chiusa: restano da decidere, e finché non decidi le rose non cambiano.
            </div>
          )}
          {frozen && (
            <div className="mt-1 text-xs text-ink-soft">
              {playingMd ? <>Giornata <b>{playingMd}</b> in corso</> : <>Giornata in corso</>}: puoi
              validare. Le formazioni di questa giornata non cambiano — vale la rosa che ogni
              squadra aveva al primo calcio d'inizio, e chi arriva ora entra dalla prossima.
            </div>
          )}
          <div className="mt-2 divide-y divide-line">
            {queue.map((o) => (
              <QueueRow key={o.offer_id} o={o} busy={busy} leagueId={leagueId} nowMs={nowMs}
                onAccept={() => onAccept(o.offer_id)} onDiscard={onDiscard} />
            ))}
          </div>
        </>
      )}
    </Card>
  );
}

function QueueRow({ o, busy, leagueId, nowMs, onAccept, onDiscard }: {
  o: MarketOfferRow; busy: boolean; leagueId: number; nowMs: number;
  onAccept: () => void; onDiscard: (d: Discard) => void;
}) {
  const [asking, setAsking] = useState(false);
  return (
    <div className="py-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Badge tone="blue">{o.role}</Badge>{' '}
          <b>{o.target_name}</b> <span className="text-ink-faint">← {o.team_name} svincola {o.release_name}</span>
          {' · '}<b>{price(o.amount)}</b> <span className="text-ink-faint">(recupero {o.recovery})</span>
        </div>
        <div className="flex gap-2">
          {/* Il bottone non si spegne piu' a giornata in corso: validare mentre si
              gioca e' ammesso, e le formazioni gia' schierate le protegge la rosa
              congelata al primo calcio d'inizio, non il divieto di validare. */}
          <Button size="sm" disabled={busy || asking} onClick={onAccept}>
            Accetta (applica rose)
          </Button>
          <Button size="sm" variant="danger" disabled={busy || asking} onClick={() => setAsking(true)}>Rifiuta</Button>
        </div>
      </div>
      {asking && (
        <DiscardBox leagueId={leagueId} offerId={o.offer_id} action="reject" nowMs={nowMs} busy={busy}
          onClose={() => setAsking(false)}
          onConfirm={(restore) => { setAsking(false); onDiscard({ offerId: o.offer_id, action: 'reject', restore }); }} />
      )}
    </div>
  );
}

function LeadingRow({ f, nowMs, closesAt, busy, leagueId, onDiscard }: {
  f: MarketFreeAgent; nowMs: number; closesAt: string | null | undefined; busy: boolean;
  leagueId: number; onDiscard: (d: Discard) => void;
}) {
  const l = f.leading!;
  const [asking, setAsking] = useState(false);
  return (
    <div className="py-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Badge tone="blue">{f.role}</Badge>{' '}
          <b>{f.name}</b> <span className="text-ink-faint">· {l.team_name} a <b>{price(l.amount)}</b>
            {l.release_name && <> svincolando <b>{l.release_name}</b></>} ·{' '}
            <OfferDeadline deadlineAt={l.deadline_at} sessionClosesAt={closesAt} nowMs={nowMs} /></span>
        </div>
        <Button size="sm" variant="ghost" disabled={busy || asking} onClick={() => setAsking(true)}>Annulla</Button>
      </div>
      {asking && (
        <DiscardBox leagueId={leagueId} offerId={l.offer_id} action="cancel" nowMs={nowMs} busy={busy}
          onClose={() => setAsking(false)}
          onConfirm={(restore) => { setAsking(false); onDiscard({ offerId: l.offer_id, action: 'cancel', restore }); }} />
      )}
    </div>
  );
}

/** Il riquadro che si apre quando l'admin sta per togliere di mezzo un'offerta.
 *
 *  Era una riga di `window.confirm` («Annullare l'offerta in testa?»), e per
 *  un'offerta sola bastava. Ma un'offerta puo' essere un RILANCIO, e allora
 *  sotto c'e' qualcuno che era in testa prima: quella NON torna in piedi da sola
 *  — resta superata per sempre, il giocatore torna offribile dal minimo (il
 *  rilancio minimo si legge dall'offerta in testa, e non ce n'e' piu' una) e
 *  nessuno avvisa chi era stato scavalcato. Il server sa dire cosa c'e' sotto e
 *  se regge ancora ai conti di oggi; qui lo si legge PRIMA di decidere.
 *
 *  Non sceglie la pagina e non sceglie il server: la scelta e' dell'admin, ed e'
 *  fra due cose entrambe legittime — ripristinare, o lasciare il giocatore
 *  libero, che e' come si e' sempre comportato il mercato. */
function DiscardBox({ leagueId, offerId, action, nowMs, busy, onClose, onConfirm }: {
  leagueId: number;
  offerId: number;
  action: 'cancel' | 'reject';
  nowMs: number;
  busy: boolean;
  onClose: () => void;
  onConfirm: (restore?: boolean) => void;
}) {
  const [pv, setPv] = useState<MarketDiscardPreview | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getMarketDiscardPreview(leagueId, offerId, action)
      .then((p) => { if (alive) setPv(p); })
      .catch((e) => {
        if (alive) setErr(e instanceof ApiError ? e.message : 'Non riesco a leggere la situazione.');
      });
    return () => { alive = false; };
  }, [leagueId, offerId, action]);

  const verb = action === 'cancel' ? 'Annulla' : 'Rifiuta';
  const verbing = action === 'cancel' ? 'Annullando' : 'Rifiutando';

  if (err) {
    return (
      <div className="mt-2 rounded-xl border border-bad/40 bg-bad-bg p-3 text-sm text-bad">
        {err} <Button size="sm" variant="ghost" onClick={onClose}>Chiudi</Button>
      </div>
    );
  }
  if (!pv) {
    return (
      <div className="mt-2 rounded-xl border border-line bg-surface-2 p-3 text-sm text-ink-faint">
        Controllo cosa c’è sotto…
      </div>
    );
  }

  const prev = pv.previous;
  return (
    <div className="mt-2 rounded-xl border border-warn/40 bg-warn-bg p-3 text-sm">
      {!prev ? (
        <div>
          Nessun’altra offerta sotto: <b>{pv.target_name}</b> torna offribile da tutti,
          dal minimo.
        </div>
      ) : (
        <>
          <div>
            Questa offerta era un <b>rilancio</b>. Sotto c’è quella di <b>{prev.team_name}</b> a{' '}
            <b>{price(prev.amount)}</b>
            {prev.release_name && <> svincolando <b>{prev.release_name}</b></>}, e{' '}
            <b>non torna in testa da sola</b>.
          </div>
          <div className="mt-2 text-ink-soft">
            {!prev.restorable ? (
              <>Non è più ripristinabile: {prev.blocker}.</>
            ) : prev.would_queue ? (
              <>
                Ripristinandola non torna in testa: {prev.expired ? (
                  <>il suo tempo era già finito da{' '}
                    <span className="tabular-nums">{elapsedSince(prev.deadline_at, nowMs)}</span></>
                ) : (
                  <>la sessione è chiusa</>
                )}, quindi va <b>subito in validazione</b>, qui sopra.
              </>
            ) : (
              <>
                Ripristinandola torna in testa <b>col suo orologio di allora</b>, non con
                24 ore nuove: le restano{' '}
                <span className="tabular-nums">{countdown(prev.deadline_at, nowMs)}</span>.
              </>
            )}
          </div>
          <div className="mt-2 text-ink-soft">
            {verbing} e basta, <b>{pv.target_name}</b> torna offribile dal minimo e{' '}
            {prev.team_name} non riceve alcun avviso.
          </div>
        </>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="ghost" disabled={busy} onClick={onClose}>Torna indietro</Button>
        {!prev ? (
          <Button size="sm" variant="danger" disabled={busy} onClick={() => onConfirm()}>
            {verb} l’offerta
          </Button>
        ) : (
          <>
            <Button size="sm" variant="danger" disabled={busy} onClick={() => onConfirm(false)}>
              {verb} soltanto
            </Button>
            {prev.restorable && (
              <Button size="sm" disabled={busy} onClick={() => onConfirm(true)}>
                {verb} e ripristina {prev.team_name}
              </Button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function CreateSessionCard({
  busy, onCreate,
}: {
  busy: boolean;
  onCreate: (opts: { name?: string; credit_recovery_mode: MarketRecoveryMode; fixed_recovery_amount?: number; opens_at?: string | null; closes_at?: string | null }) => void;
}) {
  const [mode, setMode] = useState<MarketRecoveryMode>('frac50');
  const [fixed, setFixed] = useState(1);
  const [name, setName] = useState('Mercato di riparazione');
  const [opensAt, setOpensAt] = useState('');
  const [deferred, setDeferred] = useState(false);
  const [closesAt, setClosesAt] = useState('');
  const [scheduled, setScheduled] = useState(false);

  // Una finestra che si chiude prima di aprirsi: il server la rifiuta, ma dirlo
  // qui evita di scoprirlo dopo aver compilato tutto.
  const backwards = deferred && scheduled && !!opensAt && !!closesAt
    && new Date(closesAt).getTime() <= new Date(opensAt).getTime();
  const incomplete = (deferred && !opensAt) || (scheduled && !closesAt);

  return (
    <Card className="p-4">
      <SectionTitle>Apri una sessione di mercato</SectionTitle>
      <div className="mt-1 text-sm text-ink-soft">
        Nessuna sessione aperta. Apri una finestra di offerte sugli svincolati — subito
        o a una data fissata, così puoi annunciarla alla lega in anticipo; una sola
        sessione viva per lega.
      </div>
      <div className="mt-4 space-y-3 border-t border-line pt-4">
        <label className="block text-sm">
          <span className="text-ink-soft">Nome</span>
          <input className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-sm" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="block text-sm">
          <span className="text-ink-soft">Recupero {CURRENCY_NAME_PLURAL} dallo svincolo</span>
          <select className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-sm" value={mode} onChange={(e) => setMode(e.target.value as MarketRecoveryMode)}>
            <option value="fixed">Cifra fissa</option>
            <option value="frac30">30% del prezzo pagato (arrotondato per eccesso)</option>
            <option value="frac50">50% del prezzo pagato (arrotondato per eccesso)</option>
            <option value="frac75">75% del prezzo pagato (arrotondato per eccesso)</option>
          </select>
        </label>
        {mode === 'fixed' && (
          <label className="block text-sm">
            <span className="text-ink-soft">Quanti {CURRENCY_NAME_PLURAL} si recuperano</span>
            <input type="number" min={0} className="mt-1 w-32 rounded-xl border border-line px-3 py-2 text-sm" value={fixed} onChange={(e) => setFixed(Math.max(0, Number(e.target.value)))} />
          </label>
        )}
        {/* L'apertura viene prima della chiusura anche nel modulo: si programma
            per poterla annunciare, e l'annuncio si scrive prima che cominci. */}
        <label className="flex items-center gap-2 text-sm text-ink-soft">
          <input type="checkbox" checked={deferred} onChange={(e) => setDeferred(e.target.checked)} />
          Apertura programmata (altrimenti apre subito)
        </label>
        {deferred && (
          <label className="block text-sm">
            <span className="text-ink-soft">Data/ora di apertura</span>
            <input type="datetime-local" className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-sm" value={opensAt} onChange={(e) => setOpensAt(e.target.value)} />
            <span className="mt-1 block text-xs text-ink-faint">
              Fino a quel momento la lega vede il mercato in arrivo, col conto alla
              rovescia, e può studiare gli svincolati: le offerte si aprono all’ora fissata.
            </span>
          </label>
        )}
        <label className="flex items-center gap-2 text-sm text-ink-soft">
          <input type="checkbox" checked={scheduled} onChange={(e) => setScheduled(e.target.checked)} />
          Chiusura programmata (altrimenti indefinita, la chiudi a mano)
        </label>
        {scheduled && (
          <label className="block text-sm">
            <span className="text-ink-soft">Data/ora di chiusura</span>
            <input type="datetime-local" className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-sm" value={closesAt} onChange={(e) => setClosesAt(e.target.value)} />
            <span className="mt-1 block text-xs text-ink-faint">
              Alla chiusura ogni offerta ancora in testa passa in validazione, anche se
              non ha compiuto le sue 24 ore: aspettarsi rilanci sul filo è normale.
            </span>
          </label>
        )}
        {backwards && (
          <div className="text-xs text-bad">La chiusura deve venire dopo l’apertura.</div>
        )}
        <Button disabled={busy || incomplete || backwards}
          onClick={() => onCreate({
            name: name.trim() || undefined,
            credit_recovery_mode: mode,
            fixed_recovery_amount: mode === 'fixed' ? fixed : undefined,
            opens_at: deferred && opensAt ? new Date(opensAt).toISOString() : null,
            closes_at: scheduled && closesAt ? new Date(closesAt).toISOString() : null,
          })}>
          {deferred ? 'Programma sessione' : 'Apri sessione'}
        </Button>
      </div>
    </Card>
  );
}
