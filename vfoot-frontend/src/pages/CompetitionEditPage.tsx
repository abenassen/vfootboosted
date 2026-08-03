import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  createCompetitionPrize,
  deleteCompetition,
  deleteCompetitionPrize,
  getCompetitions,
  getCompetitionStages,
  previewCompetitionSchedule,
  scheduleCompetition,
  updateCompetition,
} from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { competitionFormatLabel } from '../league/competitionFormat';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type {
  CompetitionItem,
  CompetitionSchedulePreview,
  CompetitionStageItem,
} from '../types/league';
import { DEFAULT_RECORD, PRIZE_RECORDS, recordByValue } from '../utils/prizes';

const PRIZE_ICONS = ['🏆', '🥇', '🥈', '🥉', '🛡️', '⭐', '👑', '🎖️', '🐐', '💩'];
const inputCls = 'w-full rounded-xl border border-slate-200 px-3 py-2 text-sm';

/**
 * Editing, kept apart from creating.
 *
 * Most of a competition is decided once and then stops being a question: the
 * shape, the field, the formula. What genuinely stays open afterwards is where
 * its rounds fall on the real calendar, what is at stake, and whether it is over.
 * That is all this page offers — and once a result exists it says so, rather than
 * letting a redraw quietly erase games that have been played.
 */
export default function CompetitionEditPage() {
  const { competitionId } = useParams();
  const compId = Number(competitionId);
  const { selectedLeagueId, selectedLeague } = useLeagueContext();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const justCreated = searchParams.get('created') === '1';

  const [comp, setComp] = useState<CompetitionItem | null>(null);
  const [stages, setStages] = useState<CompetitionStageItem[]>([]);
  const [schedule, setSchedule] = useState<CompetitionSchedulePreview | null>(null);
  const [draft, setDraft] = useState<Record<string, number>>({});
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [prizeName, setPrizeName] = useState('');
  const [prizeIcon, setPrizeIcon] = useState('🏆');
  const [prizeCondition, setPrizeCondition] = useState<'winner' | 'runner_up' | 'rank' | 'stat'>('winner');
  const [prizeRankFrom, setPrizeRankFrom] = useState(1);
  const [prizeRecord, setPrizeRecord] = useState(DEFAULT_RECORD.value);

  const isAdmin = selectedLeague?.role === 'admin';

  const reload = useCallback(async () => {
    if (!selectedLeagueId || !Number.isFinite(compId)) return;
    const [comps, sts] = await Promise.all([getCompetitions(selectedLeagueId), getCompetitionStages(compId)]);
    const found = comps.find((c) => c.competition_id === compId) ?? null;
    setComp(found);
    setName(found?.name ?? '');
    setStages(sts);
    const preview = await previewCompetitionSchedule(compId, {});
    setSchedule(preview);
    setDraft({ ...preview.current_mapping });
  }, [selectedLeagueId, compId]);

  useEffect(() => {
    setError(null);
    void reload().catch((e) => setError(e instanceof Error ? e.message : 'Errore di caricamento.'));
  }, [reload]);

  async function run(action: () => Promise<void>, okMsg?: string) {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      await action();
      if (okMsg) setMsg(okMsg);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Operazione fallita.');
    } finally {
      setBusy(false);
    }
  }

  const roundRows = useMemo(() => comp?.rounds ?? [], [comp]);
  const locked = comp?.structure_locked ?? false;

  if (!selectedLeagueId) return <div className="p-6 text-sm text-slate-500">Seleziona una lega.</div>;
  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <Card className="p-6 text-sm text-slate-600">Solo gli admin della lega possono modificare le competizioni.</Card>
      </div>
    );
  }
  if (error && !comp) return <div className="p-6 text-sm text-red-600">{error}</div>;
  if (!comp) return <div className="p-6 text-sm text-slate-500">Caricamento…</div>;

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 pb-24 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-xl font-bold text-slate-900">{comp.name}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <Badge tone="slate">{competitionFormatLabel(comp)}</Badge>
            <Badge tone={comp.status === 'done' ? 'green' : comp.status === 'active' ? 'amber' : 'slate'}>
              {comp.status === 'done' ? 'conclusa' : comp.status === 'active' ? 'in corso' : 'bozza'}
            </Badge>
            <span className="text-xs text-slate-500">
              {comp.fixtures.finished}/{comp.fixtures.total} gare giocate
            </span>
          </div>
        </div>
        <Link to="/league-admin?tab=league" className="shrink-0 text-sm text-slate-500 hover:text-slate-900">
          ✕ Chiudi
        </Link>
      </div>

      {justCreated ? (
        <Card className="border border-green-200 bg-green-50 p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-green-500 text-white">✓</div>
            <div className="text-sm text-green-900">
              Competizione creata.
              {comp.dependencies.length
                ? ' I partecipanti compariranno quando la competizione da cui si qualificano avrà giocato.'
                : ' Il calendario è già agganciato alle giornate reali: qui sotto puoi ritoccarlo.'}
            </div>
          </div>
          <div className="mt-3">
            <Button size="sm" onClick={() => navigate(`/competitions/${comp.competition_id}`)}>
              Vai alla competizione
            </Button>
          </div>
        </Card>
      ) : null}

      {msg ? <div className="rounded-xl bg-slate-100 px-3 py-2 text-sm text-slate-700">{msg}</div> : null}
      {error ? <div className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}

      {/* structure — read only, with the reason */}
      <Card className="p-4 sm:p-5">
        <SectionTitle>Struttura</SectionTitle>
        <div className="mt-2 space-y-1.5">
          {stages.map((s) => (
            <div key={s.stage_id} className="rounded-xl border border-slate-200 p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-900">{s.name}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <Badge tone={s.stage_type === 'knockout' ? 'amber' : 'blue'}>
                      {s.stage_type === 'knockout' ? 'Eliminazione diretta' : 'Tutti contro tutti'}
                    </Badge>
                    {s.stage_type === 'round_robin' && s.legs > 1 ? (
                      <Badge tone="slate">{s.legs} tornate</Badge>
                    ) : null}
                  </div>
                  {s.rules_in.length ? (
                    <div className="mt-1.5 text-[11px] text-slate-500">
                      Partecipanti da:{' '}
                      {s.rules_in
                        .map((r) => {
                          // Naming this competition inside its own stage graph
                          // ("chi vince di Coppa / Semifinali") reads as a
                          // different competition; only say it when it IS one.
                          const external =
                            r.source_competition_id != null && r.source_competition_id !== comp.competition_id;
                          const where = external ? `${r.source_competition_name} · ` : '';
                          const when = r.source_round ? ` dopo la giornata ${r.source_round}` : '';
                          const who =
                            r.mode === 'table_range'
                              ? `posizioni ${r.rank_from}–${r.rank_to ?? r.rank_from} della classifica`
                              : r.mode === 'winners'
                                ? 'chi vince'
                                : 'chi perde';
                          return `${who} di «${where}${r.source_stage_name}»${when}`;
                        })
                        .join('; ')}
                    </div>
                  ) : null}
                </div>
                <div className="shrink-0 text-right text-[11px] text-slate-500">
                  <div>
                    {s.participants.length || s.expected_participants} squadre
                    {s.participants.length ? '' : ' (attese)'}
                  </div>
                  <div>
                    {s.planned_rounds} {s.planned_rounds === 1 ? 'giornata' : 'giornate'}
                  </div>
                  {s.first_matchday ? (
                    <div>
                      reali {s.first_matchday}
                      {s.last_matchday && s.last_matchday !== s.first_matchday ? `–${s.last_matchday}` : ''}
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          ))}
          {!stages.length ? <div className="text-sm text-slate-500">Nessun turno definito.</div> : null}
        </div>
        <div className="mt-3 rounded-xl bg-slate-50 p-3 text-[11px] text-slate-500">
          {locked
            ? 'Ci sono già risultati: la struttura è congelata. Per cambiarla, elimina la competizione e ricreala.'
            : 'La struttura si decide alla creazione. Per cambiarla, elimina la competizione e ricreala — oppure usa la costruzione avanzata.'}
          {' '}
          <Link to="/league-admin/competitions/advanced" className="underline">
            Costruzione avanzata
          </Link>
        </div>
      </Card>

      {/* calendar fine-tuning */}
      <Card className="p-4 sm:p-5">
        <SectionTitle>Calendario</SectionTitle>
        <div className="mt-1 text-xs text-slate-500">
          Ogni turno della competizione si gioca su una giornata di Serie A. La distribuzione è automatica; qui la
          correggi. Un turno non può precedere quello prima di lui.
        </div>
        {schedule?.constraints?.length ? (
          <div className="mt-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
            {schedule.constraints.map((c, i) => (
              <div key={i}>{c}</div>
            ))}
          </div>
        ) : null}

        <div className="mt-3 space-y-1.5">
          {roundRows.map((row) => (
            <div
              key={row.round_no}
              className="grid items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 sm:grid-cols-[1fr_140px]"
            >
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-slate-800">{row.label}</div>
                <div className="text-[11px] text-slate-400">giornata {row.round_no} della competizione</div>
              </div>
              <select
                className="rounded-lg border border-slate-200 px-2 py-1.5 text-sm"
                value={draft[String(row.round_no)] ?? ''}
                onChange={(e) =>
                  setDraft((prev) => ({ ...prev, [String(row.round_no)]: Number(e.target.value) }))
                }
              >
                <option value="">non assegnata</option>
                {(schedule?.available_real_matchdays ?? []).map((md) => (
                  <option key={md} value={md}>
                    Giornata {md}
                  </option>
                ))}
              </select>
            </div>
          ))}
          {!roundRows.length ? (
            <div className="text-sm text-slate-500">
              Nessuna giornata ancora: la struttura nascerà quando i partecipanti saranno decisi.
            </div>
          ) : null}
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={busy || !roundRows.length}
            onClick={() =>
              void run(async () => {
                const mapping: Record<string, number> = {};
                Object.entries(draft).forEach(([k, v]) => {
                  if (Number.isFinite(v) && v > 0) mapping[k] = Number(v);
                });
                const res = await scheduleCompetition(compId, { round_mapping: mapping });
                await reload();
                setMsg(
                  res.warnings?.length
                    ? `Calendario salvato. ${res.warnings.join(' · ')}`
                    : 'Calendario salvato.'
                );
              })
            }
          >
            Salva calendario
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy || !schedule}
            onClick={() => setDraft({ ...(schedule?.proposed_mapping ?? {}) })}
          >
            Ridistribuisci in automatico
          </Button>
        </div>
      </Card>

      {/* prizes */}
      <Card className="p-4 sm:p-5">
        <SectionTitle>Premi</SectionTitle>
        <div className="mt-2 space-y-1.5">
          {comp.prizes.map((p) => (
            <div key={p.prize_id} className="flex items-center justify-between gap-2 rounded-xl border border-slate-200 px-3 py-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className="text-xl leading-none">{p.icon}</span>
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-900">{p.name}</div>
                  <div className="truncate text-[11px] text-slate-500">{p.condition_label}</div>
                  {p.winner_team_names.length ? (
                    <div className="truncate text-[11px] font-semibold text-green-700">
                      → {p.winner_team_names.join(', ')}
                    </div>
                  ) : null}
                </div>
              </div>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await deleteCompetitionPrize(p.prize_id);
                    await reload();
                  }, 'Premio rimosso.')
                }
              >
                Togli
              </Button>
            </div>
          ))}
          {!comp.prizes.length ? <div className="text-sm text-slate-500">Nessun premio configurato.</div> : null}
        </div>

        <div className="mt-3 space-y-2 rounded-xl border border-dashed border-slate-300 p-3">
          <input
            className={inputCls}
            placeholder="Nome del premio (es. Scudetto)"
            value={prizeName}
            onChange={(e) => setPrizeName(e.target.value)}
          />
          <div className="flex flex-wrap gap-1">
            {PRIZE_ICONS.map((icon) => (
              <button
                key={icon}
                type="button"
                onClick={() => setPrizeIcon(icon)}
                className={
                  'h-9 w-9 rounded-lg border text-lg ' +
                  (prizeIcon === icon ? 'border-slate-900 bg-slate-100' : 'border-slate-200')
                }
              >
                {icon}
              </button>
            ))}
          </div>
          <select
            className={inputCls}
            value={prizeCondition}
            onChange={(e) => setPrizeCondition(e.target.value as typeof prizeCondition)}
          >
            <option value="winner">{comp.format === 'league' ? 'Chi arriva primo' : "Chi vince l'ultimo turno"}</option>
            <option value="runner_up">
              {comp.format === 'league' ? 'Chi arriva secondo' : "Chi perde l'ultimo turno"}
            </option>
            <option value="rank">Una posizione in classifica</option>
            <option value="stat">Un primato (media, attacco, difesa…)</option>
          </select>
          {prizeCondition === 'rank' ? (
            <input
              type="number"
              min={1}
              className={inputCls}
              value={prizeRankFrom}
              onChange={(e) => setPrizeRankFrom(Math.max(1, Number(e.target.value) || 1))}
            />
          ) : null}
          {prizeCondition === 'stat' ? (
            <select className={inputCls} value={prizeRecord} onChange={(e) => setPrizeRecord(e.target.value)}>
              {PRIZE_RECORDS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          ) : null}
          <Button
            size="sm"
            disabled={busy || !prizeName.trim()}
            onClick={() =>
              void run(async () => {
                const lastStage = stages.length ? stages[stages.length - 1] : null;
                const isKnockoutEnd = comp.format === 'cup' || comp.format === 'groups_knockout';
                if (prizeCondition === 'stat') {
                  // A record is read off the whole competition, so there is no
                  // stage to point at and no shape to special-case.
                  const record = recordByValue(prizeRecord);
                  await createCompetitionPrize(compId, {
                    name: prizeName.trim(),
                    icon: prizeIcon,
                    condition_type: record.direction === 'top' ? 'stat_top' : 'stat_bottom',
                    stat: record.stat,
                  });
                } else if (prizeCondition === 'rank') {
                  await createCompetitionPrize(compId, {
                    name: prizeName.trim(),
                    icon: prizeIcon,
                    condition_type: 'final_table_range',
                    rank_from: prizeRankFrom,
                    rank_to: prizeRankFrom,
                  });
                } else if (isKnockoutEnd && lastStage) {
                  await createCompetitionPrize(compId, {
                    name: prizeName.trim(),
                    icon: prizeIcon,
                    condition_type: prizeCondition === 'winner' ? 'stage_winner' : 'stage_loser',
                    source_stage_id: lastStage.stage_id,
                  });
                } else {
                  await createCompetitionPrize(compId, {
                    name: prizeName.trim(),
                    icon: prizeIcon,
                    condition_type: 'final_table_range',
                    rank_from: prizeCondition === 'winner' ? 1 : 2,
                    rank_to: prizeCondition === 'winner' ? 1 : 2,
                  });
                }
                setPrizeName('');
                await reload();
              }, 'Premio aggiunto.')
            }
          >
            Aggiungi premio
          </Button>
        </div>
      </Card>

      {/* identity + lifecycle */}
      <Card className="p-4 sm:p-5">
        <SectionTitle>Impostazioni</SectionTitle>
        <div className="mt-3 space-y-3">
          <div>
            <span className="text-xs font-semibold text-slate-500">Nome</span>
            <div className="mt-1 flex gap-2">
              <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
              <Button
                size="sm"
                variant="secondary"
                disabled={busy || !name.trim() || name === comp.name}
                onClick={() =>
                  void run(async () => {
                    await updateCompetition(compId, { name: name.trim() });
                    await reload();
                  }, 'Nome aggiornato.')
                }
              >
                Salva
              </Button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t pt-3">
            <span className="text-xs font-semibold text-slate-500">Stato:</span>
            {(['draft', 'active', 'done'] as const).map((st) => (
              <Button
                key={st}
                size="sm"
                variant={comp.status === st ? 'primary' : 'secondary'}
                disabled={busy || comp.status === st}
                onClick={() =>
                  void run(async () => {
                    await updateCompetition(compId, { status: st });
                    await reload();
                  }, 'Stato aggiornato.')
                }
              >
                {st === 'draft' ? 'Bozza' : st === 'active' ? 'In corso' : 'Conclusa'}
              </Button>
            ))}
          </div>

          <div className="border-t pt-3">
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  if (!window.confirm(`Eliminare «${comp.name}»? Operazione irreversibile.`)) return;
                  await deleteCompetition(compId);
                  navigate('/league-admin?tab=league');
                })
              }
            >
              Elimina competizione
            </Button>
            <div className="mt-1 text-[11px] text-slate-400">
              Se un'altra competizione si qualifica da questa, va eliminata prima quella.
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
