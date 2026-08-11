import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import {
  acceptAllLeagueDecisions,
  consultLeagueDecision,
  getLeagueDecisions,
  resolveLeagueDecision,
  voteLeagueDecision,
} from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { DECISIONS_CHANGED } from '../league/useDecisionAlerts';
import type { LeagueDecision, LeagueDecisionsResponse } from '../types/decisions';

/** Five minutes. See the poll effect for why it is minutes and not seconds. */
const POLL_MS = 5 * 60 * 1000;

/** The league's open questions.
 *
 * Two audiences on one page. The admin sees everything he has to sign off and
 * can clear the routine ones in a single click; a member sees only what he has
 * been asked about, because someone else's backlog is not a to-do list for him.
 */
export default function DecisionsPage() {
  const { selectedLeague } = useLeagueContext();
  const leagueId = selectedLeague?.league_id ?? null;
  const [data, setData] = useState<LeagueDecisionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | 'all' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showResolved, setShowResolved] = useState(false);
  // Read by the poll without making it a dependency: the interval must not be
  // torn down and rebuilt every time a button starts or stops working.
  const busyRef = useRef(busy);
  busyRef.current = busy;

  const load = useCallback(async () => {
    if (leagueId == null) return;
    setLoading(true);
    try {
      setData(await getLeagueDecisions(leagueId, showResolved ? 'all' : 'open'));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Errore nel caricamento.');
    } finally {
      setLoading(false);
    }
  }, [leagueId, showResolved]);

  useEffect(() => {
    void load();
  }, [load]);

  // A slow poll, deliberately. The only thing that opens decisions on its own is
  // the Transfermarkt import, and it runs twice a day — outside the Serie A
  // windows it usually finds nothing at all. This is not here to be prompt: it is
  // here so a tab left open on Monday is not still showing Monday's queue on
  // Wednesday. Hence minutes, not the twenty seconds the market pages use.
  useEffect(() => {
    if (leagueId == null) return;
    const poll = window.setInterval(() => {
      // Not mid-action, and not on a tab nobody is looking at: a reload landing
      // between a vote and its own refresh would redraw the list under the click
      // that is still resolving.
      if (busyRef.current == null && !document.hidden) void load();
    }, POLL_MS);
    return () => window.clearInterval(poll);
  }, [leagueId, load]);

  const act = async (key: number | 'all', fn: () => Promise<unknown>) => {
    setBusy(key);
    try {
      await fn();
      await load();
      // Il numerino sulla voce di menu vive in un altro albero (la navigazione),
      // e si rinfrescava solo per push, per ritorno in primo piano o al giro di
      // sondaggio: chi decideva qui vedeva la coda svuotarsi e il badge restare
      // a 17. Questo e' l'unico posto che sa che e' cambiata.
      window.dispatchEvent(new CustomEvent(DECISIONS_CHANGED, { detail: { leagueId } }));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Operazione non riuscita.');
    } finally {
      setBusy(null);
    }
  };

  const open = useMemo(() => data?.decisions.filter((d) => d.status === 'open') ?? [], [data]);
  const resolved = useMemo(() => data?.decisions.filter((d) => d.status !== 'open') ?? [], [data]);

  if (leagueId == null) return <div className="text-sm text-ink-faint">Seleziona una lega.</div>;
  if (loading && !data) return <div className="text-sm text-ink-faint">Caricamento decisioni…</div>;

  return (
    <div className="space-y-4">
      {data?.blocked_reason ? (
        <Card className="border-l-4 border-warn bg-warn-bg p-4">
          {/* Not "market blocked": the market is open, these players are not. */}
          <div className="text-sm font-bold text-warn">Giocatori in attesa di un ruolo</div>
          <div className="mt-1 text-sm text-warn">{data.blocked_reason}</div>
          {data.is_admin ? (
            <Button
              size="sm"
              variant="primary"
              className="mt-3"
              disabled={busy === 'all'}
              onClick={() => void act('all', () => acceptAllLeagueDecisions(leagueId))}
            >
              {busy === 'all' ? 'Applico…' : 'Accetta tutte le proposte'}
            </Button>
          ) : (
            <div className="mt-2 text-xs text-warn">
              Le disambiguazioni spettano all'amministratore della lega.
            </div>
          )}
        </Card>
      ) : null}

      {error ? (
        <div className="rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">{error}</div>
      ) : null}

      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <SectionTitle>Decisioni aperte</SectionTitle>
          <div className="flex flex-wrap items-center gap-3">
            {/* There was a "Controlla il mercato reale" button here. It re-ran the
                listone snapshot on demand, but every input to that snapshot —
                stints, TM role seeds, the inference — is written by the
                Transfermarkt import alone, and the import already snapshots every
                classic league on the season in the same run. So between two
                imports it recomputed the same answer from the same data: a button
                that promised to go and look, and looked at nothing. The one input
                that can move without an import is `compute_classic_roles`, a
                manual command, and whoever runs it has `manage.py
                freeze_league_listone --league N` on the same shell. */}
            <label className="flex items-center gap-2 text-xs text-ink-faint">
              <input
                type="checkbox"
                checked={showResolved}
                onChange={(e) => setShowResolved(e.target.checked)}
              />
              mostra anche quelle chiuse
            </label>
          </div>
        </div>
        {open.length === 0 ? (
          <div className="mt-3 text-sm text-ink-faint">
            Nessuna decisione in sospeso.
          </div>
        ) : (
          <div className="mt-3 divide-y">
            {open.map((d) => (
              <DecisionRow
                key={d.id}
                d={d}
                isAdmin={!!data?.is_admin}
                busy={busy === d.id}
                onVote={(o) => act(d.id, () => voteLeagueDecision(leagueId, d.id, o))}
                onResolve={(o) => act(d.id, () => resolveLeagueDecision(leagueId, d.id, o))}
                onConsult={(v) => act(d.id, () => consultLeagueDecision(leagueId, d.id, v))}
              />
            ))}
          </div>
        )}
      </Card>

      {showResolved && resolved.length > 0 ? (
        <Card className="p-4">
          <SectionTitle>Già decise</SectionTitle>
          <div className="mt-2 divide-y text-sm">
            {resolved.map((d) => (
              <div key={d.id} className="flex items-center justify-between py-2">
                <span className="text-ink-soft">{d.title}</span>
                <Badge tone="slate">
                  {d.options.find((o) => o.value === d.outcome)?.label ?? d.outcome}
                </Badge>
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  );
}

function DecisionRow({
  d,
  isAdmin,
  busy,
  onVote,
  onResolve,
  onConsult,
}: {
  d: LeagueDecision;
  isAdmin: boolean;
  busy: boolean;
  onVote: (option: string) => void;
  onResolve: (option: string) => void;
  onConsult: (open: boolean) => void;
}) {
  const [choice, setChoice] = useState(d.proposed || d.my_vote || '');
  return (
    <div className="py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-ink">{d.title}</span>
        {/* Per PLAYER, not per league — same wording as the banner above, which
            says in as many words that the market is open and he is not. */}
        {d.blocks_market ? <Badge tone="amber">non acquistabile</Badge> : null}
        {d.consultation_open ? <Badge tone="green">consultazione aperta</Badge> : null}
      </div>
      {d.question ? <div className="mt-0.5 text-sm text-ink-soft">{d.question}</div> : null}
      {/* Why we are asking. A queue that says "decide" without saying why reads as
          an obstacle rather than as a question. */}
      {d.rationale ? <div className="mt-1 text-xs text-ink-faint">{d.rationale}</div> : null}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {d.options.map((o) => {
          const selected = choice === o.value;
          const votes = d.tally[o.value] ?? 0;
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => setChoice(o.value)}
              className={`rounded-xl border px-3 py-1.5 text-sm font-semibold ${
                selected
                  ? 'border-line bg-ink text-paper'
                  : 'border-line bg-surface text-ink-soft hover:bg-surface-2'
              }`}
            >
              {o.label}
              {o.value === d.proposed ? <span className="ml-1 text-[10px] opacity-70">proposto</span> : null}
              {votes > 0 ? (
                <span className="ml-1 text-[10px] font-bold opacity-90">
                  · {votes} {votes === 1 ? 'voto' : 'voti'}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {d.consultation_open ? (
          <Button size="sm" variant="secondary" disabled={busy || !choice} onClick={() => onVote(choice)}>
            {d.my_vote ? 'Cambia il mio parere' : 'Dai il tuo parere'}
          </Button>
        ) : null}
        {isAdmin ? (
          <>
            <Button size="sm" variant="primary" disabled={busy || !choice} onClick={() => onResolve(choice)}>
              Decidi
            </Button>
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => onConsult(!d.consultation_open)}>
              {d.consultation_open ? 'Chiudi la consultazione' : 'Chiedi alla lega'}
            </Button>
          </>
        ) : null}
        {d.votes_total > 0 ? (
          <span className="text-xs text-ink-faint">
            {d.votes_total} {d.votes_total === 1 ? 'parere' : 'pareri'} · non vincolanti, decide
            l'amministratore
          </span>
        ) : null}
      </div>
    </div>
  );
}
