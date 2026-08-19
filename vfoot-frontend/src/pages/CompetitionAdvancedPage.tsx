import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  addCompetitionStageRule,
  createCompetitionStage,
  createCompetitionTemplate,
  deleteCompetitionStage,
  getCompetitions,
  getCompetitionStages,
  getLeagueDetail,
} from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type { CompetitionItem, CompetitionRoundRow, CompetitionStageItem, LeagueDetail } from '../types/league';

const inputCls = 'w-full rounded-xl border border-line px-3 py-2 text-sm';

/**
 * The manual builder, for shapes the three templates do not cover.
 *
 * It used to live inside the league-admin page, side by side with the guided
 * flow, so people filled it in without ever noticing there was an easier way —
 * and the same form did creating and editing at once. Here it is its own place,
 * reached on purpose, and it does exactly one thing: assemble a competition out
 * of turns. Calendar and prizes belong to the competition's own page afterwards.
 */
export default function CompetitionAdvancedPage() {
  const { selectedLeagueId, selectedLeague } = useLeagueContext();
  const navigate = useNavigate();

  const [league, setLeague] = useState<LeagueDetail | null>(null);
  const [competitions, setCompetitions] = useState<CompetitionItem[]>([]);
  const [compId, setCompId] = useState<number | null>(null);
  const [stages, setStages] = useState<CompetitionStageItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // new competition
  const [newName, setNewName] = useState('');

  // new stage
  const [stageName, setStageName] = useState('');
  const [stageType, setStageType] = useState<'round_robin' | 'knockout'>('round_robin');
  const [stageOrder, setStageOrder] = useState(1);
  const [stageLegs, setStageLegs] = useState(1);
  const [stageSource, setStageSource] = useState<'teams' | 'derived'>('teams');
  const [stageTeamIds, setStageTeamIds] = useState<number[]>([]);
  const [stageExpected, setStageExpected] = useState(4);

  // rule on an existing stage
  const [ruleTargetId, setRuleTargetId] = useState<number | null>(null);
  const [ruleSource, setRuleSource] = useState<string>(''); // "stageId:roundNo" or "stageId:"
  const [ruleMode, setRuleMode] = useState<'table_range' | 'winners' | 'losers'>('table_range');
  const [ruleRankFrom, setRuleRankFrom] = useState(1);
  const [ruleRankTo, setRuleRankTo] = useState(2);

  const isAdmin = selectedLeague?.role === 'admin';
  const comp = useMemo(() => competitions.find((c) => c.competition_id === compId) ?? null, [competitions, compId]);

  const reload = useCallback(async () => {
    if (!selectedLeagueId) return;
    const [d, comps] = await Promise.all([getLeagueDetail(selectedLeagueId), getCompetitions(selectedLeagueId)]);
    setLeague(d);
    setCompetitions(comps);
    setStageTeamIds((prev) => (prev.length ? prev : d.teams.map((t) => t.team_id)));
  }, [selectedLeagueId]);

  useEffect(() => {
    void reload().catch((e) => setError(e instanceof Error ? e.message : 'Errore di caricamento.'));
  }, [reload]);

  useEffect(() => {
    if (compId == null) {
      setStages([]);
      return;
    }
    void getCompetitionStages(compId)
      .then(setStages)
      .catch(() => setStages([]));
  }, [compId, competitions]);

  useEffect(() => {
    setStageOrder((stages.reduce((mx, s) => Math.max(mx, s.order_index), 0) || 0) + 1);
  }, [stages]);

  /** Every round of every competition of the league: the qualification sources. */
  const sourceRounds = useMemo(() => {
    const out: { key: string; label: string }[] = [];
    for (const c of competitions) {
      const byStage = new Map<number, CompetitionRoundRow[]>();
      for (const row of c.rounds ?? []) {
        if (row.stage_id == null) continue;
        byStage.set(row.stage_id, [...(byStage.get(row.stage_id) ?? []), row]);
      }
      for (const [stageId, rows] of byStage) {
        const last = rows[rows.length - 1];
        out.push({ key: `${stageId}:`, label: `${c.name} — ${last.stage_name} (classifica finale)` });
        if (rows.length > 1) {
          for (const row of rows) {
            out.push({
              key: `${stageId}:${row.round_no}`,
              label: `${c.name} — ${row.label}${row.real_matchday ? ` · reale ${row.real_matchday}` : ''}`,
            });
          }
        }
      }
    }
    return out;
  }, [competitions]);

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

  if (!selectedLeagueId) return <div className="p-6 text-sm text-ink-faint">Seleziona una lega.</div>;
  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <Card className="p-6 text-sm text-ink-soft">Solo gli admin della lega possono costruire competizioni.</Card>
      </div>
    );
  }

  const teams = league?.teams ?? [];

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 pb-24 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-bold text-ink">Costruzione avanzata</h1>
          <p className="text-sm text-ink-faint">Per formule che i tre formati guidati non coprono.</p>
        </div>
        <Link to="/league-admin?tab=league" className="shrink-0 text-sm text-ink-faint hover:text-ink">
          ← Competizioni
        </Link>
      </div>

      <Card className="border border-line bg-surface-2 p-4 text-xs text-ink-soft">
        Qui si assembla una competizione turno per turno: crei il contenitore, poi ogni turno, poi da dove ne arrivano i
        partecipanti. Calendario e premi si sistemano dopo, dalla pagina della competizione. Se ti serve un campionato,
        una coppa o un girone con playoff, il{' '}
        <Link to="/league-admin/competitions/new" className="font-semibold underline">
          percorso guidato
        </Link>{' '}
        fa tutto in una volta.
      </Card>

      {msg ? <div className="rounded-xl bg-surface-2 px-3 py-2 text-sm text-ink-soft">{msg}</div> : null}
      {error ? <div className="rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">{error}</div> : null}

      {/* 1. the container */}
      <Card className="p-4 sm:p-5">
        <SectionTitle>1 · La competizione</SectionTitle>
        <div className="mt-3 space-y-2">
          <select className={inputCls} value={compId ?? ''} onChange={(e) => setCompId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">— scegli una competizione da comporre —</option>
            {competitions.map((c) => (
              <option key={c.competition_id} value={c.competition_id}>
                {c.name}
              </option>
            ))}
          </select>
          <div className="flex gap-2">
            <input
              className={inputCls}
              placeholder="…oppure creane una nuova, vuota"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <Button
              size="sm"
              disabled={busy || !newName.trim()}
              onClick={() =>
                void run(async () => {
                  const res = await createCompetitionTemplate(selectedLeagueId, {
                    name: newName.trim(),
                    competition_type: 'round_robin',
                    container_only: true,
                  });
                  setNewName('');
                  await reload();
                  setCompId(res.competition_id);
                }, 'Competizione creata: ora aggiungi i turni.')
              }
            >
              Crea
            </Button>
          </div>
        </div>
      </Card>

      {comp ? (
        <>
          {/* 2. the stages */}
          <Card className="p-4 sm:p-5">
            <SectionTitle>2 · I turni di «{comp.name}»</SectionTitle>
            <div className="mt-2 space-y-1.5">
              {stages.map((s) => (
                <div key={s.stage_id} className="flex items-start justify-between gap-2 rounded-xl border border-line p-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-ink">
                      #{s.order_index} {s.name}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <Badge tone={s.stage_type === 'knockout' ? 'amber' : 'blue'}>
                        {s.stage_type === 'knockout' ? 'Eliminazione diretta' : 'Tutti contro tutti'}
                      </Badge>
                      {s.legs > 1 ? <Badge tone="slate">{s.legs} tornate</Badge> : null}
                      <span className="text-[11px] text-ink-faint">
                        giornate {s.round_offset + 1}–{s.round_offset + s.planned_rounds}
                      </span>
                    </div>
                    {s.rules_in.length ? (
                      <div className="mt-1 text-[11px] text-ink-faint">
                        da:{' '}
                        {s.rules_in
                          .map(
                            (r) =>
                              `${
                                r.mode === 'table_range'
                                  ? `posizioni ${r.rank_from}–${r.rank_to ?? r.rank_from}`
                                  : r.mode === 'winners'
                                    ? 'vincitori'
                                    : 'perdenti'
                              } di ${r.source_competition_name ? `${r.source_competition_name} / ` : ''}${r.source_stage_name}${
                                r.source_round ? ` dopo la giornata ${r.source_round}` : ''
                              }`
                          )
                          .join('; ')}
                      </div>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <span className="text-[11px] text-ink-faint">
                      {s.participants.length || s.expected_participants} sq.
                    </span>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          if (!window.confirm(`Eliminare il turno «${s.name}»?`)) return;
                          await deleteCompetitionStage(s.stage_id);
                          setStages(await getCompetitionStages(comp.competition_id));
                          await reload();
                        }, 'Turno eliminato.')
                      }
                    >
                      Elimina
                    </Button>
                  </div>
                </div>
              ))}
              {!stages.length ? <div className="text-sm text-ink-faint">Nessun turno: aggiungine uno qui sotto.</div> : null}
            </div>

            <div className="mt-4 space-y-3 rounded-xl border border-dashed border-line p-3">
              <div className="text-xs font-semibold text-ink-faint">Nuovo turno</div>
              <input
                className={inputCls}
                placeholder="Nome del turno (es. Girone A, Semifinali)"
                value={stageName}
                onChange={(e) => setStageName(e.target.value)}
              />
              <div className="grid grid-cols-2 gap-2">
                <select className={inputCls} value={stageType} onChange={(e) => setStageType(e.target.value as typeof stageType)}>
                  <option value="round_robin">Tutti contro tutti</option>
                  <option value="knockout">Eliminazione diretta</option>
                </select>
                <input
                  type="number"
                  min={1}
                  className={inputCls}
                  value={stageOrder}
                  onChange={(e) => setStageOrder(Math.max(1, Number(e.target.value) || 1))}
                />
              </div>
              <div className="text-[11px] text-ink-faint">
                Turni con lo stesso ordine si giocano in parallelo (gironi affiancati) e condividono le giornate; un
                ordine più alto viene dopo.
              </div>
              {stageType === 'round_robin' ? (
                <div>
                  <div className="text-xs font-semibold text-ink-faint">Tornate</div>
                  <div className="mt-1 grid grid-cols-5 gap-1.5">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <button
                        key={n}
                        type="button"
                        onClick={() => setStageLegs(n)}
                        className={
                          'rounded-xl border px-2 py-2 text-sm font-semibold ' +
                          (stageLegs === n
                            ? 'border-line bg-ink text-paper'
                            : 'border-line bg-surface text-ink-soft')
                        }
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="inline-flex rounded-xl bg-surface-2 p-1">
                <button
                  type="button"
                  onClick={() => setStageSource('teams')}
                  className={
                    stageSource === 'teams'
                      ? 'rounded-lg bg-surface px-3 py-1.5 text-xs font-semibold'
                      : 'px-3 py-1.5 text-xs font-semibold text-ink-soft'
                  }
                >
                  Squadre scelte
                </button>
                <button
                  type="button"
                  onClick={() => setStageSource('derived')}
                  className={
                    stageSource === 'derived'
                      ? 'rounded-lg bg-surface px-3 py-1.5 text-xs font-semibold'
                      : 'px-3 py-1.5 text-xs font-semibold text-ink-soft'
                  }
                >
                  Qualificate
                </button>
              </div>

              {stageSource === 'teams' ? (
                <div className="grid max-h-40 grid-cols-2 gap-1.5 overflow-auto sm:grid-cols-3">
                  {teams.map((t) => {
                    const on = stageTeamIds.includes(t.team_id);
                    return (
                      <button
                        key={t.team_id}
                        type="button"
                        onClick={() =>
                          setStageTeamIds((prev) =>
                            prev.includes(t.team_id) ? prev.filter((x) => x !== t.team_id) : [...prev, t.team_id]
                          )
                        }
                        className={
                          'truncate rounded-lg border px-2 py-1.5 text-left text-xs ' +
                          (on ? 'border-line bg-ink text-paper' : 'border-line bg-surface text-ink-soft')
                        }
                      >
                        {t.name}
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div>
                  <span className="text-xs font-semibold text-ink-faint">Quante squadre attese</span>
                  <input
                    type="number"
                    min={2}
                    className={inputCls + ' mt-1'}
                    value={stageExpected}
                    onChange={(e) => setStageExpected(Math.max(2, Number(e.target.value) || 2))}
                  />
                  <div className="mt-1 text-[11px] text-ink-faint">
                    Serve a calcolare le giornate — e quindi il calendario — prima ancora di sapere chi ci giocherà. Le
                    regole di qualificazione si aggiungono al passo 3.
                  </div>
                </div>
              )}

              <Button
                size="sm"
                disabled={busy || !stageName.trim() || (stageSource === 'teams' && stageTeamIds.length < 2)}
                onClick={() =>
                  void run(async () => {
                    await createCompetitionStage(comp.competition_id, {
                      name: stageName.trim(),
                      stage_type: stageType,
                      order_index: stageOrder,
                      legs: stageLegs,
                      team_ids: stageSource === 'teams' ? stageTeamIds : [],
                      expected_participants: stageSource === 'derived' ? stageExpected : undefined,
                    });
                    setStageName('');
                    setStages(await getCompetitionStages(comp.competition_id));
                    await reload();
                  }, 'Turno aggiunto.')
                }
              >
                Aggiungi turno
              </Button>
            </div>
          </Card>

          {/* 3. qualification rules */}
          <Card className="p-4 sm:p-5">
            <SectionTitle>3 · Da dove arrivano i partecipanti</SectionTitle>
            <div className="mt-1 text-xs text-ink-faint">
              Un turno può essere alimentato dalla classifica o dai risultati di un altro turno, anche di un'altra
              competizione della lega.
            </div>
            <div className="mt-3 space-y-2">
              <div>
                <span className="text-xs font-semibold text-ink-faint">Turno da riempire</span>
                <select
                  className={inputCls + ' mt-1'}
                  value={ruleTargetId ?? ''}
                  onChange={(e) => setRuleTargetId(e.target.value ? Number(e.target.value) : null)}
                >
                  <option value="">Seleziona…</option>
                  {stages.map((s) => (
                    <option key={s.stage_id} value={s.stage_id}>
                      #{s.order_index} {s.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <span className="text-xs font-semibold text-ink-faint">Sorgente</span>
                <select className={inputCls + ' mt-1'} value={ruleSource} onChange={(e) => setRuleSource(e.target.value)}>
                  <option value="">Seleziona…</option>
                  {sourceRounds.map((r) => (
                    <option key={r.key} value={r.key}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <span className="text-xs font-semibold text-ink-faint">Criterio</span>
                <select className={inputCls + ' mt-1'} value={ruleMode} onChange={(e) => setRuleMode(e.target.value as typeof ruleMode)}>
                  <option value="table_range">Posizione in classifica</option>
                  <option value="winners">Chi vince</option>
                  <option value="losers">Chi perde</option>
                </select>
              </div>
              {ruleMode === 'table_range' ? (
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <span className="text-xs font-semibold text-ink-faint">Dalla posizione</span>
                    <input
                      type="number"
                      min={1}
                      className={inputCls + ' mt-1'}
                      value={ruleRankFrom}
                      onChange={(e) => setRuleRankFrom(Math.max(1, Number(e.target.value) || 1))}
                    />
                  </div>
                  <div>
                    <span className="text-xs font-semibold text-ink-faint">Alla posizione</span>
                    <input
                      type="number"
                      min={1}
                      className={inputCls + ' mt-1'}
                      value={ruleRankTo}
                      onChange={(e) => setRuleRankTo(Math.max(1, Number(e.target.value) || 1))}
                    />
                  </div>
                </div>
              ) : null}
              <Button
                size="sm"
                disabled={busy || ruleTargetId == null || !ruleSource}
                onClick={() =>
                  void run(async () => {
                    if (ruleTargetId == null) return;
                    const [sid, rno] = ruleSource.split(':');
                    const res = await addCompetitionStageRule(ruleTargetId, {
                      source_stage_id: Number(sid),
                      mode: ruleMode,
                      source_round: rno ? Number(rno) : null,
                      rank_from: ruleMode === 'table_range' ? ruleRankFrom : undefined,
                      rank_to: ruleMode === 'table_range' ? ruleRankTo : undefined,
                    });
                    setStages(await getCompetitionStages(comp.competition_id));
                    await reload();
                    setMsg(
                      res.resolve?.fixtures_created
                        ? 'Regola aggiunta: il turno è già stato compilato.'
                        : 'Regola aggiunta. Il turno si riempirà quando la sorgente avrà giocato.'
                    );
                  })
                }
              >
                Aggiungi regola
              </Button>
            </div>
          </Card>

          <Card className="p-4 sm:p-5">
            <SectionTitle>4 · Calendario e premi</SectionTitle>
            <div className="mt-1 text-xs text-ink-faint">
              Quando la struttura ti soddisfa, le giornate e i premi si sistemano nella pagina della competizione.
            </div>
            <div className="mt-3">
              <Button onClick={() => navigate(`/league-admin/competitions/${comp.competition_id}`)}>
                Apri «{comp.name}»
              </Button>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  );
}
