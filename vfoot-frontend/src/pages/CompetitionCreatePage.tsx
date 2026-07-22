import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  addCompetitionRule,
  buildDefaultCompetitionStages,
  createCompetitionTemplate,
  getCompetitions,
  getCompetitionStages,
  getLeagueDetail,
  getRealSeasons,
  scheduleCompetition,
  setLeagueReferenceSeason,
  updateCompetition,
} from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type {
  CompetitionItem,
  CompetitionStageItem,
  LeagueDetail,
  RealSeasonItem,
  ReferenceSeason,
} from '../types/league';

type TemplateKind = 'round_robin' | 'knockout';
type ParticipantsSource = 'manual' | 'rule';
type RuleMode = 'table_range' | 'winner' | 'loser';

// ---- preview math (mirrors backend generators, purely for instant feedback) ----

function floorPow2(n: number): number {
  let p = 1;
  while (p * 2 <= n) p *= 2;
  return p;
}

function roundRobinPreview(n: number, double: boolean) {
  if (n < 2) return null;
  const baseRounds = n % 2 === 0 ? n - 1 : n;
  const baseMatches = (n * (n - 1)) / 2;
  return { rounds: baseRounds * (double ? 2 : 1), matches: baseMatches * (double ? 2 : 1) };
}

function knockoutPreview(n: number) {
  if (n < 2) return null;
  const base = floorPow2(n);
  const eliminate = n - base; // play-in matches needed to reach a power of two
  const stages: string[] = [];
  if (eliminate > 0) stages.push(`Turno preliminare · ${eliminate} ${eliminate === 1 ? 'spareggio' : 'spareggi'}`);
  let size = base;
  while (size >= 2) {
    const label =
      size === 2 ? 'Finale' : size === 4 ? 'Semifinali' : size === 8 ? 'Quarti' : size === 16 ? 'Ottavi' : `Round of ${size}`;
    stages.push(`${label} · ${size / 2} ${size / 2 === 1 ? 'gara' : 'gare'}`);
    size = Math.floor(size / 2);
  }
  return { base, eliminate, stages };
}

// ---- small UI atoms ----

function StepDots({ step }: { step: number }) {
  const labels = ['Template', 'Configura', 'Rivedi'];
  return (
    <div className="flex items-center gap-2">
      {labels.map((label, i) => {
        const n = i + 1;
        const active = n === step;
        const done = n < step;
        return (
          <div key={label} className="flex items-center gap-2">
            <div
              className={
                'flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ' +
                (active ? 'bg-slate-900 text-white' : done ? 'bg-green-500 text-white' : 'bg-slate-200 text-slate-500')
              }
            >
              {done ? '✓' : n}
            </div>
            <span className={'text-sm ' + (active ? 'font-semibold text-slate-900' : 'text-slate-400')}>{label}</span>
            {n < labels.length ? <span className="mx-1 text-slate-300">→</span> : null}
          </div>
        );
      })}
    </div>
  );
}

function TemplateCard({
  active,
  emoji,
  title,
  blurb,
  onClick,
}: {
  active: boolean;
  emoji: string;
  title: string;
  blurb: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        'flex w-full flex-col items-start gap-2 rounded-2xl border-2 p-5 text-left transition ' +
        (active ? 'border-slate-900 bg-slate-50 shadow-card' : 'border-slate-200 bg-white hover:border-slate-400')
      }
    >
      <span className="text-3xl">{emoji}</span>
      <span className="text-base font-bold text-slate-900">{title}</span>
      <span className="text-sm text-slate-500">{blurb}</span>
    </button>
  );
}

// ---- structure visualization (the "see what you created" graph) ----

function StageFlow({ stages }: { stages: CompetitionStageItem[] }) {
  const sorted = [...stages].sort((a, b) => a.order_index - b.order_index);
  if (!sorted.length) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">
        Nessuno stage ancora: i partecipanti verranno qualificati da un'altra competizione e la struttura sarà generata
        quando quella competizione raggiungerà la giornata indicata.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      {sorted.map((s, i) => (
        <div key={s.stage_id}>
          <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-3">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-xs font-bold text-white">
                {s.order_index}
              </div>
              <div>
                <div className="text-sm font-semibold text-slate-900">{s.name}</div>
                <div className="mt-0.5 flex items-center gap-1.5">
                  <Badge tone={s.stage_type === 'knockout' ? 'amber' : 'blue'}>
                    {s.stage_type === 'knockout' ? 'Eliminazione' : 'Round-robin'}
                  </Badge>
                  {s.double_round ? <Badge tone="slate">Andata/Ritorno</Badge> : null}
                </div>
              </div>
            </div>
            <div className="text-right text-xs text-slate-500">
              <div>{s.participants.length} squadre</div>
              <div>{s.fixtures.total} gare</div>
            </div>
          </div>
          {i < sorted.length - 1 ? <div className="py-0.5 text-center text-slate-300">↓</div> : null}
        </div>
      ))}
    </div>
  );
}

export default function CompetitionCreatePage() {
  const { selectedLeagueId, selectedLeague } = useLeagueContext();
  const navigate = useNavigate();

  const [detail, setDetail] = useState<LeagueDetail | null>(null);
  const [competitions, setCompetitions] = useState<CompetitionItem[]>([]);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  // real-season reference (league-level) + per-competition matchday span
  const [realSeasons, setRealSeasons] = useState<RealSeasonItem[]>([]);
  const [refSeason, setRefSeason] = useState<ReferenceSeason | null>(null);
  const [savingSeason, setSavingSeason] = useState(false);
  const [startMd, setStartMd] = useState('1');
  const [endMd, setEndMd] = useState('');

  const [step, setStep] = useState(1);
  const [template, setTemplate] = useState<TemplateKind | null>(null);
  const [name, setName] = useState('');

  // participants
  const [source, setSource] = useState<ParticipantsSource>('manual');
  const [selectedTeamIds, setSelectedTeamIds] = useState<number[]>([]);

  // round-robin format
  const [doubleRound, setDoubleRound] = useState(false);
  const [pointsWin, setPointsWin] = useState(3);
  const [pointsDraw, setPointsDraw] = useState(1);
  const [pointsLoss, setPointsLoss] = useState(0);

  // qualification rule (rule-fed)
  const [ruleSourceCompId, setRuleSourceCompId] = useState<number | null>(null);
  const [ruleMode, setRuleMode] = useState<RuleMode>('table_range');
  const [ruleRankFrom, setRuleRankFrom] = useState('1');
  const [ruleRankTo, setRuleRankTo] = useState('4');
  const [ruleUseRound, setRuleUseRound] = useState(false);
  const [ruleSourceRound, setRuleSourceRound] = useState('19');

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{
    compId: number;
    stages: CompetitionStageItem[];
    ruleFed: boolean;
    scheduledRounds?: number;
  } | null>(null);

  const isAdmin = selectedLeague?.role === 'admin';

  useEffect(() => {
    setDetail(null);
    setCompetitions([]);
    setLoadErr(null);
    if (!selectedLeagueId) return;
    let alive = true;
    void (async () => {
      try {
        const [d, comps, seasons] = await Promise.all([
          getLeagueDetail(selectedLeagueId),
          getCompetitions(selectedLeagueId),
          getRealSeasons(),
        ]);
        if (!alive) return;
        setDetail(d);
        setCompetitions(comps);
        setRealSeasons(seasons);
        setRefSeason(d.reference_season);
        setSelectedTeamIds(d.teams.map((t) => t.team_id)); // default: all teams
      } catch (e) {
        if (alive) setLoadErr(e instanceof Error ? e.message : 'Errore di caricamento.');
      }
    })();
    return () => {
      alive = false;
    };
  }, [selectedLeagueId]);

  const teams = detail?.teams ?? [];
  const nTeams = source === 'manual' ? selectedTeamIds.length : 0;

  const preview = useMemo(() => {
    if (template === 'round_robin') return roundRobinPreview(nTeams, doubleRound);
    if (template === 'knockout') return knockoutPreview(nTeams);
    return null;
  }, [template, nTeams, doubleRound]);

  function toggleTeam(id: number) {
    setSelectedTeamIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function applyReferenceSeason(seasonId: number | null) {
    if (!selectedLeagueId) return;
    setSavingSeason(true);
    setError(null);
    try {
      const r = await setLeagueReferenceSeason(selectedLeagueId, seasonId);
      setRefSeason(r.reference_season);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Errore nel salvataggio della stagione.');
    } finally {
      setSavingSeason(false);
    }
  }

  const canCreate =
    !!template &&
    name.trim().length > 0 &&
    (source === 'manual' ? selectedTeamIds.length >= 2 : ruleSourceCompId != null);

  async function handleCreate() {
    if (!selectedLeagueId || !template || !canCreate) return;
    setBusy(true);
    setError(null);
    try {
      const res = await createCompetitionTemplate(selectedLeagueId, {
        name: name.trim(),
        competition_type: template,
        team_ids: source === 'manual' ? selectedTeamIds : undefined,
        container_only: source === 'rule',
      });
      const compId: number = res.competition_id;

      if (template === 'round_robin' && (pointsWin !== 3 || pointsDraw !== 1 || pointsLoss !== 0)) {
        await updateCompetition(compId, { points_win: pointsWin, points_draw: pointsDraw, points_loss: pointsLoss });
      }

      let ruleFed = false;
      let scheduledRounds: number | undefined;
      const span = {
        start_matchday: Number(startMd) || 1,
        end_matchday: endMd ? Number(endMd) : null,
      };
      if (source === 'manual') {
        await buildDefaultCompetitionStages(compId, false, 42, template === 'round_robin' ? doubleRound : false);
        // Auto-map the competition rounds onto the league's reference-season
        // real matchdays within the chosen span.
        if (refSeason) {
          const r = await scheduleCompetition(compId, span);
          scheduledRounds = r.rounds;
        }
      } else if (ruleSourceCompId != null) {
        ruleFed = true;
        await addCompetitionRule(compId, {
          source_competition_id: ruleSourceCompId,
          source_stage: 'final',
          source_round: ruleUseRound ? Number(ruleSourceRound) || null : null,
          mode: ruleMode,
          rank_from: ruleMode === 'table_range' ? Number(ruleRankFrom) || 1 : undefined,
          rank_to: ruleMode === 'table_range' ? Number(ruleRankTo) || Number(ruleRankFrom) || 1 : undefined,
        });
        // No fixtures yet — just remember the span for when participants resolve.
        if (refSeason) await updateCompetition(compId, span);
      }

      const stages = await getCompetitionStages(compId);
      setCreated({ compId, stages, ruleFed, scheduledRounds });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Creazione fallita.');
    } finally {
      setBusy(false);
    }
  }

  function resetForm() {
    setCreated(null);
    setStep(1);
    setTemplate(null);
    setName('');
    setSource('manual');
    setSelectedTeamIds(teams.map((t) => t.team_id));
    setDoubleRound(false);
    setRuleSourceCompId(null);
  }

  // ---- guards ----
  if (!selectedLeagueId) {
    return <div className="p-6 text-sm text-slate-500">Seleziona una lega per creare una competizione.</div>;
  }
  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <Card className="p-6 text-sm text-slate-600">
          Solo gli admin della lega possono creare competizioni.
        </Card>
      </div>
    );
  }
  if (loadErr) {
    return <div className="p-6 text-sm text-red-600">{loadErr}</div>;
  }

  // ---- success screen ----
  if (created) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
        <Card className="p-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-green-500 text-lg text-white">✓</div>
            <div>
              <div className="text-lg font-bold text-slate-900">Competizione creata</div>
              <div className="text-sm text-slate-500">{name}</div>
            </div>
          </div>
          <div className="mt-5">
            <SectionTitle>Struttura</SectionTitle>
            <div className="mt-2">
              <StageFlow stages={created.stages} />
            </div>
          </div>
          {created.ruleFed ? (
            <div className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">
              I partecipanti saranno determinati dalla regola di qualificazione: la struttura completa comparirà appena la
              competizione sorgente raggiunge il punto indicato.
            </div>
          ) : created.scheduledRounds ? (
            <div className="mt-4 rounded-xl bg-green-50 p-3 text-sm text-green-800">
              {created.scheduledRounds} giornate agganciate alle giornate reali di {refSeason?.competition} {refSeason?.season}.
            </div>
          ) : null}
          <div className="mt-6 flex flex-wrap gap-2">
            <Button onClick={() => navigate(`/competitions/${created.compId}`)}>Apri competizione</Button>
            <Button variant="secondary" onClick={resetForm}>
              Creane un'altra
            </Button>
            <Button variant="ghost" onClick={() => navigate('/league-admin')}>
              Torna all'admin
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  // ---- wizard ----
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Nuova competizione</h1>
          <p className="text-sm text-slate-500">{selectedLeague?.name}</p>
        </div>
        <Link to="/league-admin" className="text-sm text-slate-500 hover:text-slate-900">
          ✕ Annulla
        </Link>
      </div>

      <Card className="p-4">
        <StepDots step={step} />
      </Card>

      {/* STEP 1 — template */}
      {step === 1 ? (
        <Card className="p-5">
          <SectionTitle>Scegli un formato</SectionTitle>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <TemplateCard
              active={template === 'round_robin'}
              emoji="🏆"
              title="Campionato"
              blurb="Tutti contro tutti. Classifica a punti, con andata/ritorno opzionale."
              onClick={() => setTemplate('round_robin')}
            />
            <TemplateCard
              active={template === 'knockout'}
              emoji="🥇"
              title="Coppa"
              blurb="Eliminazione diretta a tabellone. Turno preliminare automatico se le squadre non sono potenza di 2."
              onClick={() => setTemplate('knockout')}
            />
          </div>
          <div className="mt-5 flex justify-end">
            <Button disabled={!template} onClick={() => setStep(2)}>
              Continua
            </Button>
          </div>
        </Card>
      ) : null}

      {/* STEP 2 — configure */}
      {step === 2 && template ? (
        <div className="space-y-4">
          <Card className="p-5">
            <SectionTitle>Nome *</SectionTitle>
            <input
              className={
                'mt-2 w-full rounded-xl border px-3 py-2 text-sm ' +
                (name.trim() ? 'border-slate-200' : 'border-amber-300')
              }
              placeholder={template === 'round_robin' ? 'es. Campionato Lega' : 'es. Coppa Lega'}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Card>

          <Card className="p-5">
            <SectionTitle>Partecipanti</SectionTitle>
            <div className="mt-2 inline-flex rounded-xl bg-slate-100 p-1">
              <button
                type="button"
                onClick={() => setSource('manual')}
                className={'rounded-lg px-3 py-1.5 text-sm font-semibold ' + (source === 'manual' ? 'bg-white shadow-card' : 'text-slate-500')}
              >
                Squadre della lega
              </button>
              <button
                type="button"
                onClick={() => setSource('rule')}
                disabled={competitions.length === 0}
                className={
                  'rounded-lg px-3 py-1.5 text-sm font-semibold disabled:opacity-40 ' +
                  (source === 'rule' ? 'bg-white shadow-card' : 'text-slate-500')
                }
              >
                Qualificate da un'altra competizione
              </button>
            </div>

            {source === 'manual' ? (
              <div className="mt-3">
                <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
                  <span>{selectedTeamIds.length} di {teams.length} selezionate</span>
                  <div className="flex gap-2">
                    <button className="hover:text-slate-900" onClick={() => setSelectedTeamIds(teams.map((t) => t.team_id))}>
                      Tutte
                    </button>
                    <button className="hover:text-slate-900" onClick={() => setSelectedTeamIds([])}>
                      Nessuna
                    </button>
                  </div>
                </div>
                <div className="grid max-h-56 grid-cols-2 gap-1.5 overflow-auto sm:grid-cols-3">
                  {teams.map((t) => {
                    const on = selectedTeamIds.includes(t.team_id);
                    return (
                      <button
                        key={t.team_id}
                        type="button"
                        onClick={() => toggleTeam(t.team_id)}
                        className={
                          'truncate rounded-lg border px-2 py-1.5 text-left text-xs ' +
                          (on ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-200 bg-white text-slate-600')
                        }
                        title={t.name}
                      >
                        {t.name}
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="mt-3 space-y-3">
                <p className="text-xs text-slate-500">
                  I partecipanti verranno presi dai risultati di un'altra competizione — è così che costruisci, ad esempio,
                  una coppa alimentata dal campionato.
                </p>
                <div>
                  <label className="text-xs font-semibold text-slate-500">Competizione sorgente</label>
                  <select
                    className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                    value={ruleSourceCompId ?? ''}
                    onChange={(e) => setRuleSourceCompId(e.target.value ? Number(e.target.value) : null)}
                  >
                    <option value="">Seleziona…</option>
                    {competitions.map((c) => (
                      <option key={c.competition_id} value={c.competition_id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-semibold text-slate-500">Criterio</label>
                    <select
                      className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                      value={ruleMode}
                      onChange={(e) => setRuleMode(e.target.value as RuleMode)}
                    >
                      <option value="table_range">Posizione in classifica</option>
                      <option value="winner">Vincitore</option>
                      <option value="loser">Ultimo</option>
                    </select>
                  </div>
                  {ruleMode === 'table_range' ? (
                    <div className="flex items-end gap-2">
                      <div>
                        <label className="text-xs font-semibold text-slate-500">Da</label>
                        <input
                          className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                          value={ruleRankFrom}
                          onChange={(e) => setRuleRankFrom(e.target.value)}
                        />
                      </div>
                      <div>
                        <label className="text-xs font-semibold text-slate-500">A</label>
                        <input
                          className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                          value={ruleRankTo}
                          onChange={(e) => setRuleRankTo(e.target.value)}
                        />
                      </div>
                    </div>
                  ) : null}
                </div>
                <label className="flex items-center gap-2 text-sm text-slate-600">
                  <input type="checkbox" checked={ruleUseRound} onChange={(e) => setRuleUseRound(e.target.checked)} />
                  Fotografa la classifica dopo un round specifico
                </label>
                {ruleUseRound ? (
                  <div>
                    <label className="text-xs font-semibold text-slate-500">Dopo il round n.</label>
                    <input
                      className="mt-1 w-32 rounded-xl border border-slate-200 px-3 py-2 text-sm"
                      value={ruleSourceRound}
                      onChange={(e) => setRuleSourceRound(e.target.value)}
                    />
                  </div>
                ) : (
                  <p className="text-xs text-slate-400">Se non specificato, si usa la classifica finale della sorgente.</p>
                )}
              </div>
            )}
          </Card>

          {/* format options */}
          {template === 'round_robin' ? (
            <Card className="p-5">
              <SectionTitle>Formato campionato</SectionTitle>
              <label className="mt-3 flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" checked={doubleRound} onChange={(e) => setDoubleRound(e.target.checked)} />
                Andata e ritorno (ogni accoppiamento giocato due volte)
              </label>
              <div className="mt-4 grid grid-cols-3 gap-3">
                {([['Vittoria', pointsWin, setPointsWin], ['Pareggio', pointsDraw, setPointsDraw], ['Sconfitta', pointsLoss, setPointsLoss]] as const).map(
                  ([label, val, setter]) => (
                    <div key={label}>
                      <label className="text-xs font-semibold text-slate-500">{label}</label>
                      <input
                        type="number"
                        className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                        value={val}
                        onChange={(e) => setter(Number(e.target.value))}
                      />
                    </div>
                  )
                )}
              </div>
            </Card>
          ) : null}

          {/* real-season calendar */}
          <Card className="p-5">
            <SectionTitle>Calendario reale</SectionTitle>
            {refSeason ? (
              <div className="mt-2 space-y-3">
                <div className="flex items-center justify-between rounded-xl bg-slate-50 p-3">
                  <div className="flex items-center gap-2 text-sm">
                    <Badge tone="green">{refSeason.competition}</Badge>
                    <span className="font-semibold text-slate-900">{refSeason.season}</span>
                    <span className="text-slate-400">· stagione di riferimento della lega</span>
                  </div>
                  <button
                    className="text-xs text-slate-500 hover:text-slate-900"
                    disabled={savingSeason}
                    onClick={() => applyReferenceSeason(null)}
                  >
                    Cambia
                  </button>
                </div>
                <p className="text-xs text-slate-500">
                  Le giornate della competizione si agganciano automaticamente a quelle reali, distribuite nell'intervallo
                  scelto. Potrai correggerle a mano dopo, se serve.
                </p>
                <div className="flex items-end gap-3">
                  <div>
                    <label className="text-xs font-semibold text-slate-500">Dalla giornata reale</label>
                    <input
                      className="mt-1 w-28 rounded-xl border border-slate-200 px-3 py-2 text-sm"
                      value={startMd}
                      onChange={(e) => setStartMd(e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-slate-500">Alla giornata reale</label>
                    <input
                      className="mt-1 w-28 rounded-xl border border-slate-200 px-3 py-2 text-sm"
                      placeholder="ultima"
                      value={endMd}
                      onChange={(e) => setEndMd(e.target.value)}
                    />
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-2 space-y-2">
                <p className="text-sm text-slate-600">
                  Questa lega non ha ancora una stagione reale di riferimento. Sceglila una volta: vale per tutta la lega.
                </p>
                <select
                  className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                  disabled={savingSeason}
                  value=""
                  onChange={(e) => e.target.value && applyReferenceSeason(Number(e.target.value))}
                >
                  <option value="">Seleziona stagione reale…</option>
                  {realSeasons.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.competition} {s.season} · {s.matchdays} giornate
                    </option>
                  ))}
                </select>
                <p className="text-xs text-slate-400">
                  Senza stagione di riferimento puoi comunque creare la competizione, ma le giornate non verranno mappate.
                </p>
              </div>
            )}
          </Card>

          {/* live preview */}
          {source === 'manual' && preview ? (
            <Card className="border border-slate-200 bg-slate-50 p-5">
              <SectionTitle>Anteprima</SectionTitle>
              {template === 'round_robin' && 'matches' in preview ? (
                <p className="mt-2 text-sm text-slate-700">
                  {nTeams} squadre → <b>{preview.rounds} giornate</b>, <b>{preview.matches} partite</b>
                  {doubleRound ? ' (andata/ritorno)' : ''}.
                </p>
              ) : null}
              {template === 'knockout' && 'stages' in preview ? (
                <div className="mt-2 space-y-1 text-sm text-slate-700">
                  <p>{nTeams} squadre → tabellone:</p>
                  <ul className="ml-4 list-disc text-slate-600">
                    {preview.stages.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </Card>
          ) : null}

          {(() => {
            const issues: string[] = [];
            if (!name.trim()) issues.push('inserisci un nome');
            if (source === 'manual' && selectedTeamIds.length < 2) issues.push('seleziona almeno 2 squadre');
            if (source === 'rule' && ruleSourceCompId == null) issues.push('scegli la competizione sorgente');
            return (
              <div className="flex items-center justify-between">
                <Button variant="ghost" onClick={() => setStep(1)}>
                  ← Indietro
                </Button>
                <div className="flex items-center gap-3">
                  {issues.length ? (
                    <span className="text-xs text-amber-600">Per continuare: {issues.join(', ')}.</span>
                  ) : null}
                  <Button disabled={issues.length > 0} onClick={() => setStep(3)}>
                    Continua
                  </Button>
                </div>
              </div>
            );
          })()}
        </div>
      ) : null}

      {/* STEP 3 — review */}
      {step === 3 && template ? (
        <Card className="p-5">
          <SectionTitle>Riepilogo</SectionTitle>
          <dl className="mt-3 divide-y divide-slate-100 text-sm">
            <div className="flex justify-between py-2">
              <dt className="text-slate-500">Nome</dt>
              <dd className="font-semibold text-slate-900">{name}</dd>
            </div>
            <div className="flex justify-between py-2">
              <dt className="text-slate-500">Formato</dt>
              <dd className="font-semibold text-slate-900">{template === 'round_robin' ? 'Campionato' : 'Coppa'}</dd>
            </div>
            <div className="flex justify-between py-2">
              <dt className="text-slate-500">Partecipanti</dt>
              <dd className="text-right font-semibold text-slate-900">
                {source === 'manual'
                  ? `${selectedTeamIds.length} squadre selezionate`
                  : `Qualificate da ${competitions.find((c) => c.competition_id === ruleSourceCompId)?.name ?? '—'}`}
              </dd>
            </div>
            {source === 'rule' ? (
              <div className="flex justify-between py-2">
                <dt className="text-slate-500">Regola</dt>
                <dd className="text-right font-semibold text-slate-900">
                  {ruleMode === 'table_range'
                    ? `Posizioni ${ruleRankFrom}–${ruleRankTo}`
                    : ruleMode === 'winner'
                    ? 'Vincitore'
                    : 'Ultimo'}
                  {ruleUseRound ? ` · dopo round ${ruleSourceRound}` : ' · classifica finale'}
                </dd>
              </div>
            ) : null}
            {template === 'round_robin' ? (
              <div className="flex justify-between py-2">
                <dt className="text-slate-500">Formato gare</dt>
                <dd className="font-semibold text-slate-900">
                  {doubleRound ? 'Andata/Ritorno' : 'Sola andata'} · {pointsWin}/{pointsDraw}/{pointsLoss}
                </dd>
              </div>
            ) : null}
          </dl>

          {error ? <div className="mt-3 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}

          <div className="mt-5 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(2)} disabled={busy}>
              ← Indietro
            </Button>
            <Button onClick={handleCreate} disabled={!canCreate || busy}>
              {busy ? 'Creazione…' : 'Crea competizione'}
            </Button>
          </div>
        </Card>
      ) : null}
    </div>
  );
}
