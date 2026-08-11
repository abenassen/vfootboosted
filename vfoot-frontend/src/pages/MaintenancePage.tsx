import { useCallback, useEffect, useState } from 'react';
import { Button, Card, SectionTitle } from '../components/ui';
import {
  ApiError,
  decideMaintenanceProposal,
  getMaintenanceProposal,
  getMaintenanceState,
} from '../api/backend';
import type {
  MaintenanceCheck,
  MaintenanceState,
  ProposalBrief,
  ProposalDetail,
} from '../types/maintenance';

/** Manutenzione del sito — riservata a chi lo gestisce.
 *
 *  Questa pagina fa UNA cosa: mostra com'è messo il server e raccoglie il sì o il
 *  no su ciò che l'agente ha proposto. Non esegue niente: approvare mette la
 *  proposta in coda, e a farla è un esecutore su timer (entro cinque minuti) —
 *  perché l'approvazione arriva ore dopo la proposta, quando il processo
 *  dell'agente è morto da un pezzo.
 *
 *  Non è l'unica via: le stesse decisioni si prendono da terminale con
 *  `manage.py maintenance_review`. È voluto — questa pagina la serve la stessa
 *  applicazione che l'agente sta cercando di riparare, quindi quando il guasto è
 *  l'app, restano la mail e il terminale. */

const VERDICT: Record<string, { label: string; box: string }> = {
  ok: { label: 'Tutto a posto', box: 'bg-good-bg text-good' },
  warn: { label: 'Regge, ma qualcosa va guardato', box: 'bg-warn-bg text-warn' },
  alarm: { label: "Qualcosa è rotto", box: 'bg-bad-bg text-bad' },
};

const KIND_LABEL: Record<string, string> = {
  restart_unit: 'Riavvia un servizio',
  rerun_command: 'Rilancia un comando',
  clear_cache_file: 'Cancella un file di cache',
  apply_patch: 'Applica una patch',
  none: 'Nessuna azione',
};

function errMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Operazione non riuscita.';
}

function CheckLine({ check }: { check: MaintenanceCheck }) {
  const tone =
    check.level === 'alarm'
      ? 'border-bad/40 bg-bad-bg text-bad'
      : check.level === 'warn'
        ? 'border-warn/40 bg-warn-bg text-warn'
        : 'border-line bg-surface text-ink-soft';
  return <li className={`rounded-xl border px-3 py-2 text-sm ${tone}`}>{check.message}</li>;
}

/** Il dettaglio, aperto in linea: su un telefono una seconda schermata per due
 *  bottoni è una schermata di troppo. */
function ProposalCard({
  brief,
  onDecided,
}: {
  brief: ProposalBrief;
  onDecided: () => void;
}) {
  const [detail, setDetail] = useState<ProposalDetail | null>(null);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [why, setWhy] = useState('');

  const expand = async () => {
    setOpen((v) => !v);
    if (detail || open) return;
    try {
      setDetail(await getMaintenanceProposal(brief.id));
    } catch (err) {
      setError(errMessage(err));
    }
  };

  const decide = async (decision: 'approve' | 'reject') => {
    setPending(true);
    setError(null);
    try {
      await decideMaintenanceProposal(brief.id, decision, why.trim() || undefined);
      onDecided();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setPending(false);
    }
  };

  const isPatch = brief.kind === 'apply_patch';

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold">{KIND_LABEL[brief.kind] ?? brief.kind}</p>
          <p className="truncate text-xs text-ink-soft">{JSON.stringify(brief.payload)}</p>
        </div>
        {isPatch && (
          // Detto sulla scheda e non solo nel dettaglio: una patch è l'unica cosa
          // qui che tocca il codice in produzione, e non deve poter essere
          // approvata scambiandola per un riavvio.
          <span className="shrink-0 rounded-full bg-warn-bg px-2 py-0.5 text-[11px] font-semibold text-warn">
            tocca il codice
          </span>
        )}
      </div>

      {brief.summary && <p className="text-sm">{brief.summary}</p>}
      {brief.rationale && <p className="text-sm text-ink-soft">{brief.rationale}</p>}

      <button type="button" onClick={expand} className="text-left text-xs font-medium text-accent underline">
        {open ? 'Nascondi il dettaglio' : 'Vedi il dettaglio'}
      </button>

      {open && (
        <div className="space-y-2 rounded-xl border border-line bg-surface p-3 text-xs">
          {!detail && <p className="text-ink-soft">Carico…</p>}
          {detail?.diagnosis && <p className="whitespace-pre-wrap">{detail.diagnosis}</p>}
          {detail?.agent_cmd && <p className="text-ink-soft">Agente: {detail.agent_cmd}</p>}
          {detail?.evidence && Object.keys(detail.evidence).length > 0 && (
            <div>
              <p className="font-semibold">
                Prove dichiarate dall’agente — non sono una prova: i test li rigira
                l’esecutore prima di applicare.
              </p>
              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words">
                {JSON.stringify(detail.evidence, null, 2)}
              </pre>
            </div>
          )}
          {detail?.diff && (
            <div>
              <p className="font-semibold">Diff</p>
              {/* Scorre dentro il suo contenitore: il corpo della pagina non deve
                  mai scorrere in orizzontale su un telefono. */}
              <pre className="mt-1 max-h-80 overflow-auto rounded-lg bg-surface-2 p-2 font-mono text-[11px] leading-snug">
                {detail.diff}
              </pre>
            </div>
          )}
        </div>
      )}

      <input
        type="text"
        value={why}
        onChange={(e) => setWhy(e.target.value)}
        placeholder="Perché (facoltativo, ma torna all’agente)"
        className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm"
      />

      {error && <p className="rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">{error}</p>}

      <div className="flex gap-2">
        <Button onClick={() => decide('approve')} disabled={pending} className="flex-1">
          Approva
        </Button>
        <Button variant="secondary" onClick={() => decide('reject')} disabled={pending} className="flex-1">
          Rifiuta
        </Button>
      </div>
      <p className="text-[11px] text-ink-soft">
        Approvare non esegue: la proposta va in coda e la applica l’esecutore entro cinque minuti.
      </p>
    </Card>
  );
}

export default function MaintenancePage() {
  const [state, setState] = useState<MaintenanceState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setState(await getMaintenanceState());
      setError(null);
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <p className="p-4 text-sm text-ink-soft">Carico…</p>;

  if (error) {
    return (
      <div className="space-y-3 p-4">
        <SectionTitle>Manutenzione</SectionTitle>
        <p className="rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">{error}</p>
        <p className="text-sm text-ink-soft">
          Se questa pagina non risponde, la sorveglianza continua lo stesso: il controllo delle 07:30
          manda la mail senza passare da qui.
        </p>
      </div>
    );
  }
  if (!state) return null;

  const verdict = VERDICT[state.verdict] ?? VERDICT.warn;
  const problems = state.checks.filter((c) => c.level !== 'info');

  return (
    <div className="space-y-4 p-4">
      <SectionTitle>Manutenzione</SectionTitle>

      <div className={`rounded-2xl px-4 py-3 text-sm font-semibold ${verdict.box}`}>{verdict.label}</div>

      {problems.length > 0 && (
        <ul className="space-y-2">
          {problems.map((c) => (
            <CheckLine key={c.code} check={c} />
          ))}
        </ul>
      )}

      {state.pending.length > 0 ? (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold">
            {state.pending.length === 1 ? 'Una proposta aspetta un sì' : `${state.pending.length} proposte aspettano un sì`}
          </h2>
          {state.pending.map((p) => (
            <ProposalCard key={p.id} brief={p} onDecided={load} />
          ))}
        </section>
      ) : (
        <p className="text-sm text-ink-soft">Niente da decidere.</p>
      )}

      {!state.auto_enabled && (
        // Lo stato del livello automatico è scritto, non lasciato indovinare:
        // con l'automatico spento, «approvata» vuol dire che l'hai approvata tu.
        <p className="text-xs text-ink-soft">
          Livello automatico spento: ogni proposta passa da qui. Le patch non entrano
          nell’automatico a nessuna impostazione.
        </p>
      )}

      {state.runs.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Ultime passate</h2>
          <ul className="space-y-1 text-xs text-ink-soft">
            {state.runs.map((r) => (
              <li key={r.id} className="flex gap-2">
                <span className="shrink-0">{new Date(r.started_at).toLocaleString('it-IT')}</span>
                <span className="min-w-0 flex-1 truncate">{r.error || r.summary || '—'}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
