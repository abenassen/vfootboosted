import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ApiError,
  getMarketActive,
  getMarketSessions,
  placeMarketOffer,
  serverNow,
} from '../api/backend';
import { getActiveAuction } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { foldedMatch } from '../utils/text';
// `amount` sotto alias: in questa pagina `amount` e' gia' lo stato del campo
// offerta, e un import con lo stesso nome sarebbe ombreggiato a meta' file.
import {
  CURRENCY_NAME_PLURAL,
  CURRENCY_SYMBOL,
  amount as inWords,
  price,
} from '../utils/currency';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import { OfferDeadline } from '../components/OfferDeadline';
import {
  OFFER_LABEL,
  OFFER_TONE,
  ROLE_LABEL,
  ROLE_ORDER,
  SESSION_LABEL,
  SESSION_TONE,
  countdown,
  recoveryText,
  sessionPhase,
  stamp,
} from '../utils/market';
import type {
  MarketActive,
  MarketFreeAgent,
  MarketOfferRow,
  MarketSessionHistory,
  MarketSessionPhase,
} from '../types/market';
import type { ActiveAuctionInfo } from '../types/league';

export default function MarketPage() {
  const { selectedLeagueId } = useLeagueContext();
  const [data, setData] = useState<MarketActive | null>(null);
  const [history, setHistory] = useState<MarketSessionHistory[]>([]);
  const [auction, setAuction] = useState<ActiveAuctionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [nowMs, setNowMs] = useState(() => serverNow());
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
    const t = window.setInterval(() => setNowMs(serverNow()), 1000);
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

  // Lo stato che conta a schermo: `open` con l'apertura ancora da venire e'
  // "programmata". Si ricalcola a ogni secondo, quindi allo scadere del conto
  // alla rovescia la pagina si apre da se'.
  const phase = data?.session ? sessionPhase(data.session, nowMs) : null;
  const wasPhase = useRef<MarketSessionPhase | null>(null);
  useEffect(() => {
    const before = wasPhase.current;
    wasPhase.current = phase;
    // All'apertura i dati a schermo sono ancora quelli dell'attesa: un giro
    // subito, invece di restare fino a venti secondi davanti a un mercato aperto
    // con l'elenco di prima.
    if (before === 'scheduled' && phase === 'open') void refresh();
  }, [phase, refresh]);

  if (!selectedLeagueId) return <div className="text-sm text-ink-faint">Seleziona una lega per vedere il mercato.</div>;

  const session = data?.session ?? null;
  const isClassic = (data?.mode ?? auction?.mode) === 'classic';
  const isAdmin = !!data?.is_admin;
  const canOffer = phase === 'open' && data?.my_team_id != null;

  return (
    <div className="space-y-4">
      {error && <Card className="border border-bad/40 bg-bad-bg p-3 text-sm text-bad">{error}</Card>}

      {!isClassic ? (
        <Card className="p-4">
          <SectionTitle>Mercato</SectionTitle>
          <div className="mt-2 text-sm text-ink-soft">
            Il mercato a offerte è disponibile solo per le leghe in <b>modalità classic</b>.
          </div>
        </Card>
      ) : !session ? (
        <NoSessionCard isAdmin={isAdmin} auction={auction} />
      ) : (
        <>
          <SessionHeader data={data!} isAdmin={isAdmin} nowMs={nowMs} />

          {canOffer ? (
            <OfferPanel data={data!} nowMs={nowMs} busy={busy}
              targetId={targetId} onPick={pickTarget} onClearTarget={() => setTargetId(null)}
              onOffer={(t, r, a) => act(async () => { await placeMarketOffer(selectedLeagueId, t, r, a); setTargetId(null); })} />
          ) : (
            // Senza squadra, o a sessione sospesa, la ricerca resta ma da sola:
            // dentro "Fai un'offerta" non avrebbe nessuna offerta da fare.
            <FreeAgentSearchCard data={data!} nowMs={nowMs} onPick={pickTarget} />
          )}

          <MyOffersCard offers={data?.my_offers ?? []} nowMs={nowMs} closesAt={session.closes_at} />

          {/* Prima dell'apertura non puo' esistere nessuna offerta: la card
              direbbe solo "nessuna", e inviterebbe ad aprirne una che il server
              rifiuterebbe. */}
          {phase !== 'scheduled' && <LiveContestsCard data={data!} nowMs={nowMs} onPick={pickTarget} />}

          <ClosedOffersCard offers={closedThisSession} />
        </>
      )}

      {pastSessions.length > 0 && (
        <Card className="p-4">
          <button className="flex w-full items-center justify-between" onClick={() => setShowHistory((v) => !v)}>
            <SectionTitle>Storico sessioni ({pastSessions.length})</SectionTitle>
            <span className="text-xs text-ink-faint">{showHistory ? 'nascondi' : 'mostra'}</span>
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
      <div className="mt-2 text-sm text-ink-soft">
        Nessuna sessione di mercato aperta.{' '}
        {liveAuction && (
          <>C’è un’asta in corso: <Link to="/auction" className="font-semibold text-ink underline">entra nella sala asta →</Link></>
        )}
      </div>
      <div className="mt-2 text-sm text-ink-faint">
        {isAdmin
          ? <>Apri una sessione dalla scheda <b>Mercato</b> in <Link to="/league-admin?tab=market" className="underline">Gestione lega</Link>.</>
          : 'Quando l’admin apre una sessione potrai fare offerte sugli svincolati.'}
      </div>
    </Card>
  );
}

function SessionHeader({ data, isAdmin, nowMs }: { data: MarketActive; isAdmin: boolean; nowMs: number }) {
  const s = data.session!;
  const phase = sessionPhase(s, nowMs);
  // Sotto il giorno la data non dice piu' nulla di utile: da li' in giu' conta
  // quanto manca, perche' e' meno del tempo che serve a un'offerta per maturare.
  const closeMs = s.closes_at ? new Date(s.closes_at).getTime() - nowMs : null;
  const closingSoon = closeMs !== null && closeMs < 24 * 3_600_000;
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <SectionTitle>{s.name}</SectionTitle>
            <Badge tone={SESSION_TONE[phase]}>{SESSION_LABEL[phase]}</Badge>
          </div>
          {phase === 'scheduled' && <OpeningCountdown opensAt={s.opens_at} nowMs={nowMs} />}
          <div className="mt-1 text-sm text-ink-soft">
            {/* L'apertura VERA, non quella annunciata: una sessione programmata
                che apre in ritardo (nessuno ha toccato la pagina) non e' aperta
                dall'ora sul calendario, ma da quando lo e' diventata davvero. */}
            {phase !== 'scheduled' && (s.opened_at ?? s.opens_at) && (
              <>Aperta il {stamp(s.opened_at ?? s.opens_at)}{' · '}</>
            )}
            Recupero: <b>{recoveryText(s.credit_recovery_mode, s.fixed_recovery_amount)}</b>
            {' · '}
            {!s.closes_at ? 'chiusura indefinita'
              : closingSoon ? (
                <b className="text-warn">
                  chiude tra <span className="tabular-nums">{countdown(s.closes_at, nowMs)}</span>
                </b>
              ) : `chiude il ${stamp(s.closes_at)}`}
          </div>
          {s.closes_at && (
            // La regola che rende sensato rilanciare sul filo: va detta, o la
            // scopre solo chi per caso e' collegato al momento giusto.
            <div className="mt-1 text-xs text-ink-faint">
              Alla chiusura chi è in testa passa in validazione, anche senza aver compiuto 24 ore.
            </div>
          )}
          {phase === 'scheduled' && (
            <div className="mt-1 text-xs text-ink-faint">
              Puoi già vedere chi sarà svincolato e preparare le mosse: le offerte
              si aprono all’ora fissata, non prima.
            </div>
          )}
          {data.my_budget && (
            <>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-soft">
                <span>Hai <b>{inWords(data.my_budget.remaining)}</b></span>
                <span className="text-ink-faint">
                  impegnati in offerte: {price(data.my_budget.reserved)}
                </span>
                <span>disponibili: <b>{price(data.my_budget.available)}</b></span>
              </div>
              {/* Dove si spende è l'unico posto in cui vale la pena presentare la
                  moneta: qui la si vede per la prima volta, e da qui in poi il
                  simbolo accanto ai numeri si spiega da sé. */}
              <div className="mt-1 text-xs text-ink-faint">
                I crediti della lega si chiamano <b>{CURRENCY_NAME_PLURAL}</b> e si scrivono{' '}
                <b className="font-mono">{CURRENCY_SYMBOL}</b> — <b className="font-mono">{price(25)}</b>{' '}
                sono venticinque {CURRENCY_NAME_PLURAL}.
              </div>
            </>
          )}
        </div>
        {/* Alla scheda MERCATO, non alla pagina: `tab=market` apre quella scheda e
            la porta davanti agli occhi (vedi LeagueAdminPage). Prima portava a
            `tab=league`, cioè in cima alle impostazioni della lega, con la
            sessione da gestire due schermate più in basso. */}
        {isAdmin && (
          <Link to="/league-admin?tab=market" className="text-xs text-ink-faint underline">Gestisci sessione →</Link>
        )}
      </div>
      {s.status === 'suspended' && (
        <div className="mt-2 text-sm text-warn">Sessione sospesa: le offerte sono temporaneamente bloccate.</div>
      )}
    </Card>
  );
}

/** Il conto alla rovescia dell'apertura.
 *
 *  E' la ragione per cui l'ora si programma: l'admin la annuncia alla lega, e
 *  chi passa dalla pagina prima del via deve trovare quanto manca — non solo un
 *  bottone spento. Sopra le 48 ore il conto passa ai giorni (vedi `countdown`). */
function OpeningCountdown({ opensAt, nowMs }: { opensAt: string | null; nowMs: number }) {
  return (
    <div className="mt-2 inline-block rounded-xl border border-line bg-surface-2 px-3 py-2">
      <div className="text-xs uppercase tracking-wide text-ink-faint">Il mercato apre tra</div>
      <div className="text-2xl font-semibold tabular-nums">
        {/* A zero non c'e' nulla da validare: manca solo il giro di dati che
            apre la pagina, ed e' questione di un istante. */}
        {countdown(opensAt, nowMs, 'un istante')}
      </div>
      <div className="mt-0.5 text-xs text-ink-faint">{stamp(opensAt)}</div>
    </div>
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
              <span className="text-ink-faint">
                · in testa {target.leading.team_name} a <b>{price(target.leading.amount)}</b>
                {target.leading.release_name && <> svincolando <b>{target.leading.release_name}</b></>} ·{' '}
                <OfferDeadline deadlineAt={target.leading.deadline_at} sessionClosesAt={data.session?.closes_at} nowMs={nowMs} />
              </span>
            )}
            {target.locked && <Badge tone="amber">in definizione</Badge>}
            <button className="text-xs text-ink-faint underline" onClick={onClearTarget}>cambia giocatore</button>
          </div>
          <label className="block text-sm">
            <span className="text-ink-soft">Svincola (stesso ruolo)</span>
            <select className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-sm"
              value={releaseId ?? ''} onChange={(e) => setReleaseId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">— scegli —</option>
              {releaseOptions.map((p) => (
                <option key={p.player_id} value={p.player_id}>
                  {p.name} (pagato {price(p.price)} → recuperi {price(p.recovery)})
                </option>
              ))}
            </select>
            {releaseOptions.length === 0 && (
              <span className="mt-1 block text-xs text-warn">Nessun {target.role} svincolabile nella tua rosa.</span>
            )}
          </label>
          <div className="flex flex-wrap items-end gap-3">
            <label className="block text-sm">
              <span className="text-ink-soft">Offerta (in {CURRENCY_NAME_PLURAL})</span>
              <input type="number" min={minAmount} max={maxAmount}
                className="mt-1 w-32 rounded-xl border border-line px-3 py-2 text-sm"
                value={amount} onChange={(e) => setAmount(Number(e.target.value))} />
            </label>
            <div className="text-sm text-ink-soft">
              Tetto: <b>{release ? price(maxAmount) : '—'}</b>
              {release && <span className="text-ink-faint"> ({available} disponibili + {release.recovery} di recupero)</span>}
              {target.leading && <span className="text-ink-faint"> · minimo rilancio {price(minAmount)}</span>}
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

/** Un'offerta ancora in gioco: o e' in testa, o ha gia' vinto e aspetta la
 *  validazione dell'admin. Tutte le altre sono cronaca della sessione. */
const offerLive = (o: MarketOfferRow) => o.status === 'leading' || o.status === 'accepted';

function MyOffersCard({ offers, nowMs, closesAt }: {
  offers: MarketOfferRow[]; nowMs: number; closesAt: string | null | undefined;
}) {
  // Filtrata di default: bastano due rilanci perche' le superate siano piu'
  // delle vive, e la lista si allunga proprio con le righe su cui non c'e'
  // piu' niente da fare.
  const [onlyLive, setOnlyLive] = useState(true);
  const live = useMemo(() => offers.filter(offerLive), [offers]);
  if (offers.length === 0) return null;
  const past = offers.length - live.length;
  const shown = onlyLive ? live : offers;
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SectionTitle>Le mie offerte ({shown.length})</SectionTitle>
        {/* Senza niente da nascondere la casella non deciderebbe nulla. */}
        {past > 0 && (
          <label className="flex items-center gap-1.5 rounded-lg bg-surface-2 px-2.5 py-1 text-xs font-semibold text-ink-soft">
            <input type="checkbox" checked={onlyLive} onChange={(e) => setOnlyLive(e.target.checked)} />
            Solo attive
            {onlyLive && (
              <span className="font-normal text-ink-faint">
                ({past} {past === 1 ? 'nascosta' : 'nascoste'})
              </span>
            )}
          </label>
        )}
      </div>
      {shown.length === 0 ? (
        <div className="mt-2 text-sm text-ink-faint">Nessuna offerta ancora in gioco.</div>
      ) : (
        <div className="mt-2 divide-y divide-line">
          {shown.map((o) => (
            <div key={o.offer_id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
              <div>
                <Badge tone="blue">{o.role}</Badge>{' '}
                <b>{o.target_name}</b> <span className="text-ink-faint">← svincoli {o.release_name}</span>
              </div>
              <div className="flex items-center gap-3">
                <span>{price(o.amount)} <span className="text-ink-faint">(recupero {o.recovery})</span></span>
                {o.status === 'leading' && (
                  <span className="text-ink-faint">
                    <OfferDeadline deadlineAt={o.deadline_at} sessionClosesAt={closesAt} nowMs={nowMs} />
                  </span>
                )}
                <Badge tone={OFFER_TONE[o.status]}>{OFFER_LABEL[o.status]}</Badge>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

/** Una riga di svincolato: nome, ruolo, chi e' in testa, e il bottone per offrire. */
function FreeAgentRow({
  f, nowMs, closesAt, canOffer, onPick,
}: {
  f: MarketFreeAgent;
  nowMs: number;
  closesAt: string | null | undefined;
  canOffer: boolean;
  onPick: (playerId: number) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
      <div className="min-w-0">
        <Badge tone="blue">{f.role}</Badge> <b>{f.name}</b>
        {f.leading && (
          <span className="ml-2 text-ink-faint">
            in testa {f.leading.mine ? <b className="text-good">tu</b> : f.leading.team_name} a <b>{price(f.leading.amount)}</b>
            {f.leading.release_name && <> svincolando <b>{f.leading.release_name}</b></>}
            {' · '}<OfferDeadline deadlineAt={f.leading.deadline_at} sessionClosesAt={closesAt} nowMs={nowMs} />
          </span>
        )}
        {f.locked && (
          <span className="ml-2">
            <Badge tone="amber">in validazione</Badge>
            {f.pending && (
              <span className="text-ink-faint"> · vinto da {f.pending.mine ? <b className="text-good">te</b> : f.pending.team_name} a <b>{price(f.pending.amount)}</b>
                {f.pending.release_name && <> svincolando <b>{f.pending.release_name}</b></>}</span>
            )}
          </span>
        )}
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
  const canOffer = !!data.session
    && sessionPhase(data.session, nowMs) === 'open' && data.my_team_id != null;
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
        {mine > 0 && <span className="text-xs text-ink-faint">sei in testa su {mine}</span>}
      </div>
      {contests.length === 0 ? (
        <div className="mt-2 text-sm text-ink-faint">
          Nessuna offerta aperta. Cerca uno svincolato qui sotto per aprire la prima.
        </div>
      ) : (
        <div className="mt-2 divide-y divide-line">
          {contests.map((f) => (
            <FreeAgentRow key={f.player_id} f={f} nowMs={nowMs} closesAt={data.session?.closes_at}
                    canOffer={canOffer} onPick={onPick} />
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
        <span className="text-xs text-ink-faint">
          {settled.length} acquisti{offers.length > 5 && (open ? ' · mostra meno' : ' · mostra tutte')}
        </span>
      </button>
      <div className="mt-2 divide-y divide-line">
        {shown.map((o) => (
          <div key={o.offer_id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <div className="min-w-0">
              <Badge tone="blue">{o.role}</Badge> <b>{o.target_name}</b>
              <span className="ml-2 text-ink-faint">
                {o.status === 'settled' ? 'a' : 'offerto da'} {o.team_name}
                <span className="text-ink-faint"> · svincolato {o.release_name}</span>
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span>{price(o.amount)}</span>
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
  const canOffer = !!data.session
    && sessionPhase(data.session, nowMs) === 'open' && data.my_team_id != null;
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
          className="min-w-0 flex-1 rounded-xl border border-line px-3 py-2 text-sm"
          value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="rounded-xl border border-line px-2 py-2 text-sm"
          value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
          <option value="">Tutti i ruoli</option>
          {ROLE_ORDER.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
        </select>
        {searching && (
          <Button variant="ghost" size="sm" onClick={() => { setQ(''); setRoleFilter(''); }}>Pulisci</Button>
        )}
      </div>

      {!searching ? (
        <div className="mt-3 text-sm text-ink-faint">
          {freeAgents.length} svincolati disponibili. {emptyHint}
        </div>
      ) : filtered.length === 0 ? (
        <div className="mt-3 text-sm text-ink-faint">
          Nessuno svincolato corrisponde. Chi è già in una rosa non compare qui.
        </div>
      ) : (
        <div className="mt-3 space-y-4">
          <div className="text-xs text-ink-faint">{filtered.length} risultati</div>
          {ROLE_ORDER.filter((r) => byRole.has(r)).map((r) => (
            <div key={r}>
              <div className="text-xs font-semibold uppercase tracking-wide text-ink-faint">{ROLE_LABEL[r]}</div>
              <div className="mt-1 divide-y divide-line">
                {byRole.get(r)!.slice(0, 30).map((f) => (
                  <FreeAgentRow key={f.player_id} f={f} nowMs={nowMs} closesAt={data.session?.closes_at}
                    canOffer={canOffer} onPick={onPick} />
                ))}
                {byRole.get(r)!.length > 30 && (
                  <div className="py-2 text-xs text-ink-faint">…e altri {byRole.get(r)!.length - 30}. Affina la ricerca.</div>
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

/** Da quando a quando e' durata. La fine e' quella VERA (`closed_at`): una
 *  sessione chiusa a mano finisce prima della scadenza annunciata, e mostrare
 *  quest'ultima racconterebbe una durata mai esistita. Se manca, ripiega sulla
 *  scadenza prevista e lo dice. */
function sessionSpan(s: MarketSessionHistory): string {
  // Una sessione programmata e poi annullata non e' mai stata aperta: dire "dal
  // <data annunciata>" le attribuirebbe giorni che non ha avuto.
  if (!s.opened_at && s.status === 'closed') {
    const at = stamp(s.opens_at);
    return at ? `annullata prima di aprire (era per il ${at})` : 'annullata prima di aprire';
  }
  const from = stamp(s.opened_at ?? s.opens_at);
  const to = stamp(s.closed_at);
  const planned = stamp(s.closes_at);
  const start = from ? `dal ${from}` : 'inizio non registrato';
  if (to) return `${start} · al ${to}`;
  if (planned) return `${start} · chiusura prevista ${planned}`;
  return `${start} · ancora aperta`;
}

/** Ogni sessione passata e' una riga sola finche' non la si apre.
 *
 *  Prima erano tutte srotolate una dietro l'altra: una sessione con cento
 *  offerte spingeva le precedenti fuori dallo schermo, e chi cercava un mercato
 *  di sei mesi fa doveva scorrere tutto quello venuto dopo. Chiuse, ci stanno
 *  tutte insieme e si sceglie quale guardare. */
function HistoryList({ sessions }: { sessions: MarketSessionHistory[] }) {
  return (
    <div className="mt-3 space-y-2">
      {sessions.map((s) => <HistorySession key={s.id} s={s} />)}
    </div>
  );
}

function HistorySession({ s }: { s: MarketSessionHistory }) {
  const [open, setOpen] = useState(false);
  const settled = s.offers.filter((o) => o.status === 'settled');
  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-center justify-between gap-x-3 gap-y-1 px-3 py-2 text-left hover:bg-surface-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <b>{s.name}</b>
            <Badge tone={SESSION_TONE[s.status]}>{SESSION_LABEL[s.status]}</Badge>
          </div>
          <div className="mt-0.5 text-xs text-ink-faint">{sessionSpan(s)}</div>
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs text-ink-faint">
          <span>{s.offers.length} offerte · <b className="text-ink-soft">{settled.length}</b> acquisti</span>
          <span aria-hidden className="text-ink-faint">{open ? '▾' : '▸'}</span>
        </div>
      </button>
      {open && (
        <div className="border-t border-line px-3 py-2">
          <div className="text-xs text-ink-faint">
            Recupero: {recoveryText(s.credit_recovery_mode, s.fixed_recovery_amount)}
          </div>
          {s.offers.length === 0 ? (
            <div className="mt-1 text-xs text-ink-faint">Nessuna offerta in questa sessione.</div>
          ) : (
            <div className="mt-1 divide-y divide-line">
              {s.offers.map((o) => (
                <div key={o.offer_id} className="flex flex-wrap items-center justify-between gap-2 py-1.5 text-xs">
                  <span>
                    <b>{o.target_name}</b> <span className="text-ink-faint">← {o.team_name} / {o.release_name}</span>
                  </span>
                  <span className="flex items-center gap-2">
                    {price(o.amount)} <Badge tone={OFFER_TONE[o.status]}>{OFFER_LABEL[o.status]}</Badge>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
