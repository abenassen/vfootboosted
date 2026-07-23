import { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import {
  acceptAllLeagueDecisions,
  consultLeagueDecision,
  getLeagueDecisions,
  resolveLeagueDecision,
  voteLeagueDecision,
} from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import type { LeagueDecision, LeagueDecisionsResponse } from '../types/decisions';

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

  const act = async (key: number | 'all', fn: () => Promise<unknown>) => {
    setBusy(key);
    try {
      await fn();
      await load();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Operazione non riuscita.');
    } finally {
      setBusy(null);
    }
  };

  const open = useMemo(() => data?.decisions.filter((d) => d.status === 'open') ?? [], [data]);
  const resolved = useMemo(() => data?.decisions.filter((d) => d.status !== 'open') ?? [], [data]);

  if (leagueId == null) return <div className="text-sm text-slate-500">Seleziona una lega.</div>;
  if (loading && !data) return <div className="text-sm text-slate-500">Caricamento decisioni…</div>;

  return (
    <div className="space-y-4">
      {data?.blocked_reason ? (
        <Card className="border-l-4 border-amber-500 bg-amber-50 p-4">
          {/* Not "market blocked": the market is open, these players are not. */}
          <div className="text-sm font-bold text-amber-900">Giocatori in attesa di un ruolo</div>
          <div className="mt-1 text-sm text-amber-800">{data.blocked_reason}</div>
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
            <div className="mt-2 text-xs text-amber-700">
              Le disambiguazioni spettano all'amministratore della lega.
            </div>
          )}
        </Card>
      ) : null}

      {error ? (
        <div className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>
      ) : null}

      <Card className="p-4">
        <div className="flex items-center justify-between">
          <SectionTitle>Decisioni aperte</SectionTitle>
          <label className="flex items-center gap-2 text-xs text-slate-500">
            <input
              type="checkbox"
              checked={showResolved}
              onChange={(e) => setShowResolved(e.target.checked)}
            />
            mostra anche quelle chiuse
          </label>
        </div>
        {open.length === 0 ? (
          <div className="mt-3 text-sm text-slate-500">
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
                <span className="text-slate-700">{d.title}</span>
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
        <span className="font-semibold text-slate-800">{d.title}</span>
        {d.blocks_market ? <Badge tone="amber">blocca il mercato</Badge> : null}
        {d.consultation_open ? <Badge tone="green">consultazione aperta</Badge> : null}
      </div>
      {d.question ? <div className="mt-0.5 text-sm text-slate-600">{d.question}</div> : null}
      {/* Why we are asking. A queue that says "decide" without saying why reads as
          an obstacle rather than as a question. */}
      {d.rationale ? <div className="mt-1 text-xs text-slate-500">{d.rationale}</div> : null}

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
                  ? 'border-slate-900 bg-slate-900 text-white'
                  : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
              }`}
            >
              {o.label}
              {o.value === d.proposed ? <span className="ml-1 text-[10px] opacity-70">proposto</span> : null}
              {votes > 0 ? <span className="ml-1 text-[10px] font-bold opacity-90">· {votes} voti</span> : null}
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
          <span className="text-xs text-slate-500">
            {d.votes_total} pareri · non vincolanti, decide l'amministratore
          </span>
        ) : null}
      </div>
    </div>
  );
}
