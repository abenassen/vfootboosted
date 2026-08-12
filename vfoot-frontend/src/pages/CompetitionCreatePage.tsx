import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  createCompetitionGuided,
  getCompetitions,
  getLeagueDetail,
  getRealSeasons,
  previewCompetitionPlan,
  setLeagueReferenceSeason,
} from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { useCompetitionContext } from '../league/CompetitionContext';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type {
  CompetitionItem,
  CompetitionRoundRow,
  CompetitionWizardPlan,
  LeagueDetail,
  RealSeasonItem,
  ReferenceSeason,
  WizardPrizeSpec,
} from '../types/league';
import { DEFAULT_RECORD, PRIZE_RECORDS, recordByValue } from '../utils/prizes';

type Format = 'league' | 'cup' | 'groups_knockout';
type ParticipantsSource = 'teams' | 'qualified';

const PRIZE_ICONS = ['🏆', '🥇', '🥈', '🥉', '🛡️', '⭐', '👑', '🎖️', '🐐', '💩'];

const FORMATS: { id: Format; emoji: string; title: string; blurb: string }[] = [
  {
    id: 'league',
    emoji: '🛡️',
    title: 'Campionato',
    blurb: 'Tutti contro tutti, classifica a punti. Scegli quante volte girare.',
  },
  {
    id: 'cup',
    emoji: '🏆',
    title: 'Coppa',
    blurb: 'Eliminazione diretta. Turno preliminare automatico se non siete potenza di 2.',
  },
  {
    id: 'groups_knockout',
    emoji: '🌍',
    title: 'Gironi + playoff',
    // The draw is real: build_groups_knockout_graph shuffles the teams before
    // splitting them. Worth saying, because a group stage whose composition is
    // never explained reads as if someone chose it.
    blurb: 'Le squadre vengono sorteggiate nei gironi, poi le migliori si giocano il titolo agli scontri diretti.',
  },
];

const LEG_LABELS: Record<number, string> = {
  1: 'Sola andata',
  2: 'Andata e ritorno',
  3: 'Tre tornate',
  4: 'Quattro tornate',
  5: 'Cinque tornate',
};

// Mirrors MAX_LEGS in vfoot/services/competition_stages.py, where it is the point
// past which a round-robin calendar has nowhere left to go (5 giri di 8 squadre
// sono già 35 giornate). The buttons stop there because the server does.
const MAX_LEGS = 5;
const LEG_CHOICES = Array.from({ length: MAX_LEGS }, (_, i) => i + 1);

// ---- small UI atoms ----

function StepDots({ step, labels }: { step: number; labels: string[] }) {
  return (
    <div className="flex items-center gap-1.5 overflow-x-auto">
      {labels.map((label, i) => {
        const n = i + 1;
        const active = n === step;
        const done = n < step;
        return (
          <div key={label} className="flex shrink-0 items-center gap-1.5">
            <div
              className={
                'flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold ' +
                (active ? 'bg-ink text-paper' : done ? 'bg-good text-paper' : 'bg-surface-2 text-ink-faint')
              }
            >
              {done ? '✓' : n}
            </div>
            <span className={'text-xs ' + (active ? 'font-semibold text-ink' : 'text-ink-faint')}>{label}</span>
            {n < labels.length ? <span className="text-ink-faint">→</span> : null}
          </div>
        );
      })}
    </div>
  );
}

function ChoiceCard({
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
    // La scelta fatta e quella non fatta avevano lo stesso bordo e due bianchi
    // che differiscono del due per cento: sul telefono, dopo aver toccato
    // «Campionato», niente diceva che fosse stato toccato. Bordo di marca e una
    // spunta — e aria-pressed, che e' come lo dice a chi non guarda lo schermo.
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={
        'flex w-full items-start gap-3 rounded-2xl border-2 p-4 text-left transition ' +
        (active
          ? 'border-brand bg-brand/10 shadow-card'
          : 'border-line bg-surface hover:border-brand/40')
      }
    >
      <span className="text-2xl leading-none">{emoji}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-bold text-ink">{title}</span>
        <span className="mt-0.5 block text-xs text-ink-faint">{blurb}</span>
      </span>
      {active ? <span className="text-sm font-bold text-brand-strong">✓</span> : null}
    </button>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs font-semibold text-ink-faint">{label}</span>
      <div className="mt-1">{children}</div>
      {hint ? <span className="mt-1 block text-[11px] text-ink-faint">{hint}</span> : null}
    </label>
  );
}

const inputCls = 'w-full rounded-xl border border-line px-3 py-2 text-sm';

/** The shape the wizard is about to build, said in rounds and matches. */
function PlanSummary({ plan }: { plan: CompetitionWizardPlan }) {
  return (
    <div className="space-y-1.5">
      {plan.stages.map((s, i) => (
        <div key={`${s.name}-${i}`} className="flex items-center justify-between rounded-xl border border-line bg-surface px-3 py-2">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-ink">{s.name}</div>
            <div className="mt-0.5">
              <Badge tone={s.type === 'knockout' ? 'amber' : 'blue'}>
                {s.type === 'knockout' ? 'Eliminazione diretta' : 'Tutti contro tutti'}
              </Badge>
            </div>
          </div>
          <div className="shrink-0 text-right text-[11px] text-ink-faint">
            <div>{s.teams} squadre</div>
            <div>
              {s.rounds} {s.rounds === 1 ? 'turno' : 'turni'} · {s.matches} {s.matches === 1 ? 'gara' : 'gare'}
            </div>
          </div>
        </div>
      ))}
      <div className="pt-1 text-xs text-ink-faint">
        In tutto <b className="text-ink">{plan.total_rounds}</b>{' '}
        {plan.total_rounds === 1 ? 'turno' : 'turni'} da collocare sul calendario reale.
      </div>
    </div>
  );
}

export default function CompetitionCreatePage() {
  const { selectedLeagueId, selectedLeague } = useLeagueContext();
  const navigate = useNavigate();

  const [detail, setDetail] = useState<LeagueDetail | null>(null);
  const [competitions, setCompetitions] = useState<CompetitionItem[]>([]);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  const [realSeasons, setRealSeasons] = useState<RealSeasonItem[]>([]);
  const [refSeason, setRefSeason] = useState<ReferenceSeason | null>(null);
  const [savingSeason, setSavingSeason] = useState(false);

  const [step, setStep] = useState(1);
  const [format, setFormat] = useState<Format | null>(null);
  const [name, setName] = useState('');

  // participants
  const [source, setSource] = useState<ParticipantsSource>('teams');
  const [selectedTeamIds, setSelectedTeamIds] = useState<number[]>([]);

  // format options
  const [legs, setLegs] = useState(1);
  // Turni a eliminazione: gara secca o andata e ritorno. Separato da `legs`, che
  // è quante volte gira un girone: sono due domande diverse e una competizione a
  // gironi + finali le fa entrambe.
  const [knockoutLegs, setKnockoutLegs] = useState(1);
  const [finalSingle, setFinalSingle] = useState(true);
  // Shown only after a click on Continua, so the form does not greet you in red.
  const [showStep1Errors, setShowStep1Errors] = useState(false);

  const [groups, setGroups] = useState(1);
  const [advance, setAdvance] = useState(2);
  const [pointsWin, setPointsWin] = useState(3);
  const [pointsDraw, setPointsDraw] = useState(1);
  const [pointsLoss, setPointsLoss] = useState(0);

  // qualification
  const [qualStageId, setQualStageId] = useState<number | null>(null);
  const [qualRound, setQualRound] = useState<number | null>(null);
  const [qualRankFrom, setQualRankFrom] = useState(1);
  const [qualRankTo, setQualRankTo] = useState(4);

  // calendar + prizes
  const [startMd, setStartMd] = useState<number | null>(null);
  const [endMd, setEndMd] = useState<number | null>(null);
  const [prizes, setPrizes] = useState<WizardPrizeSpec[]>([]);

  const [plan, setPlan] = useState<CompetitionWizardPlan | null>(null);
  const [planErr, setPlanErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { refreshCompetitions } = useCompetitionContext();
  const isAdmin = selectedLeague?.role === 'admin';
  const teams = detail?.teams ?? [];

  // The real season's own bounds. season_real_matchdays is the list of matchdays
  // that exist, so its ends are the only values the two inputs may take — typing
  // 39 into a 38-matchday season used to be accepted and only failed later.
  const seasonMatchdays = plan?.season_real_matchdays ?? [];
  const seasonFirstMd = seasonMatchdays.length ? seasonMatchdays[0] : null;
  const seasonLastMd = seasonMatchdays.length ? seasonMatchdays[seasonMatchdays.length - 1] : null;
  const minStartMd = plan?.min_start_matchday ?? seasonFirstMd ?? 1;

  /** Keep a typed matchday inside the season, so the range cannot be impossible. */
  function clampMd(raw: string, floor: number): number | null {
    if (!raw) return null;
    const n = Number(raw);
    if (!Number.isFinite(n)) return null;
    const hi = seasonLastMd ?? n;
    return Math.max(floor, Math.min(hi, Math.round(n)));
  }

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
          // Solo i campionati in corso: qui si assegna la stagione a una lega che
          // non ce l'ha (ripiego per le leghe vecchie), e vale la stessa regola
          // della creazione — una conclusa il server la rifiuta.
          getRealSeasons(true),
        ]);
        if (!alive) return;
        setDetail(d);
        setCompetitions(comps);
        setRealSeasons(seasons);
        setRefSeason(d.reference_season);
        setSelectedTeamIds(d.teams.map((t) => t.team_id));
      } catch (e) {
        if (alive) setLoadErr(e instanceof Error ? e.message : 'Errore di caricamento.');
      }
    })();
    return () => {
      alive = false;
    };
  }, [selectedLeagueId]);

  /** Every round of every existing competition, as a qualification source. */
  const qualifiableRounds = useMemo(() => {
    const out: { compName: string; row: CompetitionRoundRow }[] = [];
    for (const c of competitions) {
      for (const row of c.rounds ?? []) {
        if (row.stage_id == null) continue;
        out.push({ compName: c.name, row });
      }
    }
    return out;
  }, [competitions]);

  const selectedQualRound = useMemo(
    () => qualifiableRounds.find((r) => r.row.stage_id === qualStageId && r.row.round_no === qualRound) ?? null,
    [qualifiableRounds, qualStageId, qualRound]
  );

  const qualification = useMemo(() => {
    if (source !== 'qualified' || qualStageId == null) return null;
    return {
      source_stage_id: qualStageId,
      mode: 'table_range' as const,
      source_round: qualRound,
      rank_from: qualRankFrom,
      rank_to: qualRankTo,
    };
  }, [source, qualStageId, qualRound, qualRankFrom, qualRankTo]);

  const qualifiedCount = Math.max(0, qualRankTo - qualRankFrom + 1);
  const teamCount = source === 'teams' ? selectedTeamIds.length : qualifiedCount;

  // Ask the backend what this spec produces: the same arithmetic that will build it.
  const refreshPlan = useCallback(async () => {
    if (!selectedLeagueId || !format) return;
    if (source === 'teams' && selectedTeamIds.length < 2) {
      setPlan(null);
      return;
    }
    if (source === 'qualified' && qualStageId == null) {
      setPlan(null);
      return;
    }
    setPlanErr(null);
    try {
      const p = await previewCompetitionPlan(selectedLeagueId, {
        format,
        team_ids: source === 'teams' ? selectedTeamIds : undefined,
        qualification,
        legs,
        knockout_legs: knockoutLegs,
        final_legs: knockoutLegs === 2 && finalSingle ? 1 : undefined,
        groups,
        advance_per_group: advance,
      });
      setPlan(p);
      setStartMd((cur) => {
        const floor = p.min_start_matchday ?? 1;
        if (cur == null || cur < floor) return floor;
        return cur;
      });
    } catch (e) {
      setPlan(null);
      setPlanErr(e instanceof Error ? e.message : 'Anteprima non disponibile.');
    }
  }, [selectedLeagueId, format, source, selectedTeamIds, qualification, legs, knockoutLegs, finalSingle, groups, advance, qualStageId]);

  useEffect(() => {
    void refreshPlan();
  }, [refreshPlan]);

  // Prizes are proposed the moment a format is chosen; the user edits or drops them.
  useEffect(() => {
    if (!format) return;
    setPrizes(
      format === 'league'
        ? [{ name: 'Scudetto', icon: '🏆', condition: 'winner' }]
        : [{ name: 'Coppa', icon: '🏆', condition: 'winner' }]
    );
  }, [format]);

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

  const issues = useMemo(() => {
    const out: string[] = [];
    if (!name.trim()) out.push('dai un nome alla competizione');
    if (source === 'teams' && selectedTeamIds.length < 2) out.push('scegli almeno 2 squadre');
    if (source === 'qualified' && qualStageId == null) out.push("scegli da dove arrivano i partecipanti");
    if (source === 'qualified' && qualifiedCount < 2) out.push('devono qualificarsi almeno 2 squadre');
    if (planErr) out.push(planErr.toLowerCase());
    return out;
  }, [name, source, selectedTeamIds, qualStageId, qualifiedCount, planErr]);

  async function handleCreate() {
    if (!selectedLeagueId || !format) return;
    setBusy(true);
    setError(null);
    try {
      const res = await createCompetitionGuided(selectedLeagueId, {
        name: name.trim(),
        format,
        team_ids: source === 'teams' ? selectedTeamIds : undefined,
        qualification,
        legs,
        knockout_legs: knockoutLegs,
        final_legs: knockoutLegs === 2 && finalSingle ? 1 : undefined,
        groups,
        advance_per_group: advance,
        points: { win: pointsWin, draw: pointsDraw, loss: pointsLoss },
        start_matchday: startMd,
        end_matchday: endMd,
        prizes: prizes.filter((p) => p.name.trim()),
      });
      // The competition list feeds the switcher in the top bar and decides which
      // menu entries exist (Partite and Classifica appear only once a competition
      // does). Without this the app still believes the league has none until a
      // reload, and the brand-new competition is unreachable from the menu.
      await refreshCompetitions();
      navigate(`/league-admin/competitions/${res.competition.competition_id}?created=1`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Creazione fallita.');
      setBusy(false);
    }
  }

  // ---- guards ----
  if (!selectedLeagueId) {
    return <div className="p-6 text-sm text-ink-faint">Seleziona una lega per creare una competizione.</div>;
  }
  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <Card className="p-6 text-sm text-ink-soft">Solo gli admin della lega possono creare competizioni.</Card>
      </div>
    );
  }
  if (loadErr) return <div className="p-6 text-sm text-bad">{loadErr}</div>;

  const stepLabels = ['Formato', 'Chi gioca', 'Quando', 'Premi'];

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 pb-24 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-bold text-ink">Nuova competizione</h1>
          <p className="truncate text-sm text-ink-faint">{selectedLeague?.name}</p>
        </div>
        <Link to="/league-admin?tab=league" className="shrink-0 text-sm text-ink-faint hover:text-ink">
          ✕ Annulla
        </Link>
      </div>

      <Card className="p-3">
        <StepDots step={step} labels={stepLabels} />
      </Card>

      {/* STEP 1 — format */}
      {step === 1 ? (
        <Card className="p-4 sm:p-5">
          <SectionTitle>Che competizione è</SectionTitle>
          <div className="mt-3 space-y-2">
            {FORMATS.map((f) => (
              <ChoiceCard
                key={f.id}
                active={format === f.id}
                emoji={f.emoji}
                title={f.title}
                blurb={f.blurb}
                onClick={() => setFormat(f.id)}
              />
            ))}
          </div>
          {showStep1Errors && !format ? (
            <div className="mt-2 text-xs font-semibold text-bad">Scegli che competizione è.</div>
          ) : null}
          <div className="mt-4">
            <Field label="Nome *">
              <input
                className={
                  inputCls + (showStep1Errors && !name.trim() ? ' border-bad bg-bad-bg' : '')
                }
                aria-invalid={showStep1Errors && !name.trim()}
                placeholder={format === 'league' ? 'es. Campionato' : 'es. Coppa dei Campioni'}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              {showStep1Errors && !name.trim() ? (
                <div className="mt-1 text-xs font-semibold text-bad">Dai un nome alla competizione.</div>
              ) : null}
            </Field>
          </div>
          <div className="mt-4 flex justify-end">
            {/* Not disabled: a dead button says nothing about WHY it will not go
                on, and there is nowhere to click to find out. It accepts the
                click and points at what is missing. */}
            <Button
              onClick={() => {
                if (!format || !name.trim()) {
                  setShowStep1Errors(true);
                  return;
                }
                setShowStep1Errors(false);
                setStep(2);
              }}
            >
              Continua
            </Button>
          </div>
        </Card>
      ) : null}

      {/* STEP 2 — participants + format options */}
      {step === 2 && format ? (
        <div className="space-y-4">
          <Card className="p-4 sm:p-5">
            <SectionTitle>Chi partecipa</SectionTitle>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <ChoiceCard
                active={source === 'teams'}
                emoji="👥"
                title="Le squadre della lega"
                blurb="Scegli tu chi iscrivere."
                onClick={() => setSource('teams')}
              />
              <ChoiceCard
                active={source === 'qualified'}
                emoji="🎟️"
                title="Chi si qualifica"
                blurb={
                  qualifiableRounds.length
                    ? 'In base alla classifica di un’altra competizione.'
                    : 'Serve prima un’altra competizione.'
                }
                onClick={() => qualifiableRounds.length && setSource('qualified')}
              />
            </div>

            {source === 'teams' ? (
              <div className="mt-4">
                <div className="mb-2 flex items-center justify-between text-xs text-ink-faint">
                  <span>
                    {selectedTeamIds.length} di {teams.length} selezionate
                  </span>
                  <div className="flex gap-3">
                    <button className="hover:text-ink" onClick={() => setSelectedTeamIds(teams.map((t) => t.team_id))}>
                      Tutte
                    </button>
                    <button className="hover:text-ink" onClick={() => setSelectedTeamIds([])}>
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
                          'truncate rounded-lg border px-2 py-2 text-left text-xs ' +
                          (on ? 'border-line bg-ink text-paper' : 'border-line bg-surface text-ink-soft')
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
              <div className="mt-4 space-y-3">
                <Field
                  label="Si qualificano dalla classifica di…"
                  hint="La coppa non potrà iniziare prima di questo momento: il calendario si sposta da solo."
                >
                  <select
                    className={inputCls}
                    value={qualStageId != null && qualRound != null ? `${qualStageId}:${qualRound}` : ''}
                    onChange={(e) => {
                      if (!e.target.value) {
                        setQualStageId(null);
                        setQualRound(null);
                        return;
                      }
                      const [sid, rno] = e.target.value.split(':').map(Number);
                      setQualStageId(sid);
                      setQualRound(rno);
                    }}
                  >
                    <option value="">Seleziona…</option>
                    {qualifiableRounds.map(({ compName, row }) => (
                      <option key={`${row.stage_id}:${row.round_no}`} value={`${row.stage_id}:${row.round_no}`}>
                        {compName} — {row.label}
                        {row.real_matchday ? ` (giornata ${row.real_matchday})` : ''}
                      </option>
                    ))}
                  </select>
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Dalla posizione">
                    <input
                      type="number"
                      min={1}
                      className={inputCls}
                      value={qualRankFrom}
                      onChange={(e) => setQualRankFrom(Math.max(1, Number(e.target.value) || 1))}
                    />
                  </Field>
                  <Field label="Alla posizione">
                    <input
                      type="number"
                      min={1}
                      className={inputCls}
                      value={qualRankTo}
                      onChange={(e) => setQualRankTo(Math.max(1, Number(e.target.value) || 1))}
                    />
                  </Field>
                </div>
                <div className="rounded-xl bg-surface-2 p-3 text-xs text-ink-soft">
                  {qualifiedCount >= 2 ? (
                    <>
                      <b>{qualifiedCount} squadre</b> qualificate
                      {selectedQualRound ? (
                        <>
                          {' '}
                          dalla classifica di «{selectedQualRound.compName}» ({selectedQualRound.row.label})
                        </>
                      ) : null}
                      . I nomi si sapranno quando quella giornata sarà giocata.
                    </>
                  ) : (
                    'Devono qualificarsi almeno 2 squadre.'
                  )}
                </div>
              </div>
            )}
          </Card>

          {/* knockout options: valgono per la coppa e per i gironi+finali */}
          {format !== 'league' ? (
            <Card className="p-4 sm:p-5">
              <SectionTitle>Turni a eliminazione</SectionTitle>
              <div className="mt-3 space-y-3">
                <Field
                  label="Come si gioca ogni turno"
                  hint="Andata e ritorno occupa due giornate per turno, e in quel caso il fattore campo della lega (se attivo) vale in entrambe."
                >
                  <div className="grid grid-cols-2 gap-1.5">
                    {[1, 2].map((n) => (
                      <button
                        key={n}
                        type="button"
                        onClick={() => setKnockoutLegs(n)}
                        className={
                          'rounded-xl border px-2 py-2 text-sm font-semibold ' +
                          (knockoutLegs === n
                            ? 'border-line bg-ink text-paper'
                            : 'border-line bg-surface text-ink-soft')
                        }
                      >
                        {n === 1 ? 'Gara secca' : 'Andata e ritorno'}
                      </button>
                    ))}
                  </div>
                </Field>
                {knockoutLegs === 2 ? (
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={finalSingle}
                      onChange={(e) => setFinalSingle(e.target.checked)}
                    />
                    <span>Finale in gara unica</span>
                    <span className="text-[11px] text-ink-faint">(come quasi tutte le coppe vere)</span>
                  </label>
                ) : null}
              </div>
            </Card>
          ) : null}

          {/* format options */}
          {format !== 'cup' ? (
            <Card className="p-4 sm:p-5">
              <SectionTitle>{format === 'league' ? 'Formula del campionato' : 'Formula dei gironi'}</SectionTitle>
              <div className="mt-3 space-y-3">
                <Field
                  label="Quante volte si affrontano tutti"
                  hint={
                    plan
                      ? `${teamCount} squadre × ${legs} ${legs === 1 ? 'tornata' : 'tornate'} = ${
                          plan.stages.find((s) => s.type === 'round_robin')?.rounds ?? 0
                        } giornate. Nelle tornate pari il campo si inverte. Si possono cambiare finché non si gioca la prima partita.`
                      : 'Ogni tornata è un giro completo di tutti contro tutti.'
                  }
                >
                  <div className="grid grid-cols-5 gap-1.5">
                    {LEG_CHOICES.map((n) => (
                      <button
                        key={n}
                        type="button"
                        onClick={() => setLegs(n)}
                        className={
                          'rounded-xl border px-2 py-2 text-sm font-semibold ' +
                          (legs === n ? 'border-line bg-ink text-paper' : 'border-line bg-surface text-ink-soft')
                        }
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                  <div className="mt-1.5 text-[11px] font-semibold text-ink-soft">
                    {LEG_LABELS[legs]}
                    {/* 5 is not "the last button we drew", it is MAX_LEGS in
                        services/competition_stages.py: oltre, il calendario non
                        ha più dove stare. */}
                    {legs === MAX_LEGS ? (
                      <span className="ml-1 font-normal text-ink-faint">
                        · è il massimo consentito
                      </span>
                    ) : null}
                  </div>
                </Field>

                {format === 'groups_knockout' ? (
                  <div className="grid grid-cols-2 gap-3">
                    <Field
                      label="Gironi"
                      hint={source === 'qualified' ? 'Con i qualificati si gioca un girone unico.' : undefined}
                    >
                      <input
                        type="number"
                        min={1}
                        max={4}
                        disabled={source === 'qualified'}
                        className={inputCls + ' disabled:bg-surface-2'}
                        value={source === 'qualified' ? 1 : groups}
                        onChange={(e) => setGroups(Math.max(1, Math.min(4, Number(e.target.value) || 1)))}
                      />
                    </Field>
                    <Field label="Passano (per girone)">
                      <input
                        type="number"
                        min={1}
                        max={4}
                        className={inputCls}
                        value={advance}
                        onChange={(e) => setAdvance(Math.max(1, Math.min(4, Number(e.target.value) || 1)))}
                      />
                    </Field>
                  </div>
                ) : null}

                <div>
                  <div className="text-xs font-semibold text-ink-faint">Punti per vittoria / pareggio / sconfitta</div>
                  <div className="mt-1 grid grid-cols-3 gap-2">
                    {(
                      [
                        [pointsWin, setPointsWin],
                        [pointsDraw, setPointsDraw],
                        [pointsLoss, setPointsLoss],
                      ] as const
                    ).map(([val, setter], i) => (
                      <input
                        key={i}
                        type="number"
                        className={inputCls}
                        value={val}
                        onChange={(e) => setter(Number(e.target.value))}
                      />
                    ))}
                  </div>
                </div>
              </div>
            </Card>
          ) : null}

          {plan ? (
            <Card className="border border-line bg-surface-2 p-4 sm:p-5">
              <SectionTitle>Com'è fatta</SectionTitle>
              <div className="mt-2">
                <PlanSummary plan={plan} />
              </div>
            </Card>
          ) : planErr ? (
            <Card className="border border-warn/40 bg-warn-bg p-4 text-sm text-warn">{planErr}</Card>
          ) : null}

          <div className="flex items-center justify-between">
            <Button variant="ghost" onClick={() => setStep(1)}>
              ← Indietro
            </Button>
            <Button disabled={issues.length > 0} onClick={() => setStep(3)}>
              Continua
            </Button>
          </div>
          {issues.length ? <div className="text-right text-xs text-warn">Per continuare: {issues.join(', ')}.</div> : null}
        </div>
      ) : null}

      {/* STEP 3 — calendar */}
      {step === 3 && format ? (
        <div className="space-y-4">
          <Card className="p-4 sm:p-5">
            <SectionTitle>Quando si gioca</SectionTitle>
            {refSeason ? (
              <div className="mt-3 space-y-3">
                <div className="flex flex-wrap items-center gap-2 rounded-xl bg-surface-2 p-3 text-sm">
                  <Badge tone="green">{refSeason.competition}</Badge>
                  <span className="font-semibold text-ink">{refSeason.season}</span>
                  <span className="text-ink-faint">· campionato di riferimento</span>
                </div>
                {plan?.constraint ? (
                  <div className="rounded-xl border border-warn/40 bg-warn-bg p-3 text-xs text-warn">
                    {plan.constraint}: non può cominciare prima della{' '}
                    <b>{plan.min_start_matchday}ª giornata</b>.
                  </div>
                ) : null}
                {/* How long the season actually is, said once: without it the two
                    inputs are unbounded boxes and there is no way to know that 38
                    is the end and 39 does not exist. */}
                {seasonFirstMd != null && seasonLastMd != null ? (
                  <div className="text-xs text-ink-faint">
                    {refSeason.competition} {refSeason.season} ha{' '}
                    <b>{plan?.season_real_matchdays.length ?? 0} giornate</b>, dalla {seasonFirstMd}ª
                    alla {seasonLastMd}ª.
                  </div>
                ) : null}
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Dalla giornata">
                    <div className="flex gap-1.5">
                      <input
                        type="number"
                        min={minStartMd}
                        max={seasonLastMd ?? undefined}
                        className={inputCls}
                        value={startMd ?? ''}
                        onChange={(e) => setStartMd(clampMd(e.target.value, minStartMd))}
                      />
                      <button
                        type="button"
                        onClick={() => setStartMd(minStartMd)}
                        className="shrink-0 rounded-xl border border-line px-2 text-xs font-semibold text-ink-soft hover:bg-surface-2"
                      >
                        Prima
                      </button>
                    </div>
                  </Field>
                  <Field label="Alla giornata" hint="Vuoto = uno dopo l'altro, senza soste.">
                    <div className="flex gap-1.5">
                      <input
                        type="number"
                        min={startMd ?? minStartMd}
                        max={seasonLastMd ?? undefined}
                        className={inputCls}
                        placeholder="di fila"
                        value={endMd ?? ''}
                        onChange={(e) => setEndMd(clampMd(e.target.value, minStartMd))}
                      />
                      <button
                        type="button"
                        onClick={() => setEndMd(seasonLastMd)}
                        className="shrink-0 rounded-xl border border-line px-2 text-xs font-semibold text-ink-soft hover:bg-surface-2"
                      >
                        Ultima
                      </button>
                    </div>
                  </Field>
                </div>
                {plan ? (
                  <div className="text-xs text-ink-faint">
                    {endMd == null ? (
                      <>
                        Le {plan.total_rounds} giornate si giocheranno di fila, dalla {startMd ?? 1}ª alla{' '}
                        {(startMd ?? 1) + plan.total_rounds - 1}ª giornata reale. Indica una giornata di fine per
                        distanziarle e coprire tutto l'intervallo.
                      </>
                    ) : (
                      <>
                        Le {plan.total_rounds} giornate verranno distribuite su questo intervallo, una per giornata
                        reale.
                      </>
                    )}{' '}
                    Potrai correggerle a mano dalla pagina della competizione.
                  </div>
                ) : null}
                {plan && startMd != null
                  ? (() => {
                      const room = plan.season_real_matchdays.filter(
                        (md) => md >= startMd && (endMd == null || md <= endMd)
                      ).length;
                      if (room >= plan.total_rounds) return null;
                      return (
                        <div className="rounded-xl border border-warn/40 bg-warn-bg p-3 text-xs text-warn">
                          Servono {plan.total_rounds} giornate reali, in questo intervallo ce ne sono {room}. Allarga
                          l'intervallo o riduci le tornate.
                        </div>
                      );
                    })()
                  : null}
              </div>
            ) : (
              <div className="mt-3 space-y-2">
                <p className="text-sm text-ink-soft">
                  Questa lega non ha ancora un campionato reale di riferimento. Sceglilo una volta: vale per tutta la lega.
                </p>
                <select
                  className={inputCls}
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
              </div>
            )}
          </Card>

          <div className="flex items-center justify-between">
            <Button variant="ghost" onClick={() => setStep(2)}>
              ← Indietro
            </Button>
            <Button onClick={() => setStep(4)}>Continua</Button>
          </div>
        </div>
      ) : null}

      {/* STEP 4 — prizes + confirm */}
      {step === 4 && format ? (
        <div className="space-y-4">
          <Card className="p-4 sm:p-5">
            <SectionTitle>Cosa si vince</SectionTitle>
            <div className="mt-1 text-xs text-ink-faint">
              Un premio è un nome, un'icona e la condizione che lo assegna. Verrà consegnato da solo quando la condizione
              si realizza.
            </div>
            <div className="mt-3 space-y-3">
              {prizes.map((prize, idx) => (
                <div key={idx} className="rounded-xl border border-line p-3">
                  <div className="flex items-center gap-2">
                    <input
                      className={inputCls}
                      placeholder="Nome del premio"
                      value={prize.name}
                      onChange={(e) =>
                        setPrizes((prev) => prev.map((p, i) => (i === idx ? { ...p, name: e.target.value } : p)))
                      }
                    />
                    <button
                      type="button"
                      className="shrink-0 rounded-lg px-2 py-2 text-ink-faint hover:text-bad"
                      onClick={() => setPrizes((prev) => prev.filter((_, i) => i !== idx))}
                      aria-label="Togli premio"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {PRIZE_ICONS.map((icon) => (
                      <button
                        key={icon}
                        type="button"
                        onClick={() => setPrizes((prev) => prev.map((p, i) => (i === idx ? { ...p, icon } : p)))}
                        className={
                          'h-9 w-9 rounded-lg border text-lg ' +
                          (prize.icon === icon ? 'border-line bg-surface-2' : 'border-line')
                        }
                      >
                        {icon}
                      </button>
                    ))}
                  </div>
                  <div className="mt-2">
                    <select
                      className={inputCls}
                      value={prize.condition}
                      onChange={(e) =>
                        setPrizes((prev) =>
                          prev.map((p, i) =>
                            i === idx ? { ...p, condition: e.target.value as WizardPrizeSpec['condition'] } : p
                          )
                        )
                      }
                    >
                      <option value="winner">{format === 'league' ? 'Chi arriva primo' : 'Chi vince la finale'}</option>
                      <option value="runner_up">
                        {format === 'league' ? 'Chi arriva secondo' : 'Chi perde la finale'}
                      </option>
                      <option value="rank">Una posizione in classifica</option>
                      <option value="stat">Un primato (media, attacco, difesa…)</option>
                    </select>
                  </div>
                  {prize.condition === 'stat' ? (
                    <div className="mt-2">
                      <select
                        className={inputCls}
                        value={`${prize.stat ?? DEFAULT_RECORD.stat}_${prize.direction ?? DEFAULT_RECORD.direction}`}
                        onChange={(e) => {
                          const rec = recordByValue(e.target.value);
                          setPrizes((prev) =>
                            prev.map((p, i) => (i === idx ? { ...p, stat: rec.stat, direction: rec.direction } : p))
                          );
                        }}
                      >
                        {PRIZE_RECORDS.map((r) => (
                          <option key={r.value} value={r.value}>
                            {r.label}
                          </option>
                        ))}
                      </select>
                      <div className="mt-1 text-[11px] text-ink-faint">
                        Si assegna a fine competizione, su tutte le giornate giocate.
                      </div>
                    </div>
                  ) : null}
                  {prize.condition === 'rank' ? (
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      <Field label="Dalla posizione">
                        <input
                          type="number"
                          min={1}
                          className={inputCls}
                          value={prize.rank_from ?? 1}
                          onChange={(e) =>
                            setPrizes((prev) =>
                              prev.map((p, i) => (i === idx ? { ...p, rank_from: Number(e.target.value) || 1 } : p))
                            )
                          }
                        />
                      </Field>
                      <Field label="Alla posizione">
                        <input
                          type="number"
                          min={1}
                          className={inputCls}
                          value={prize.rank_to ?? prize.rank_from ?? 1}
                          onChange={(e) =>
                            setPrizes((prev) =>
                              prev.map((p, i) => (i === idx ? { ...p, rank_to: Number(e.target.value) || 1 } : p))
                            )
                          }
                        />
                      </Field>
                    </div>
                  ) : null}
                </div>
              ))}
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setPrizes((prev) => [...prev, { name: '', icon: '🥈', condition: 'runner_up' }])}
              >
                + Aggiungi premio
              </Button>
            </div>
          </Card>

          <Card className="p-4 sm:p-5">
            <SectionTitle>Riepilogo</SectionTitle>
            <dl className="mt-2 divide-y divide-line text-sm">
              <div className="flex justify-between gap-3 py-2">
                <dt className="text-ink-faint">Nome</dt>
                <dd className="truncate font-semibold text-ink">{name}</dd>
              </div>
              <div className="flex justify-between gap-3 py-2">
                <dt className="text-ink-faint">Formato</dt>
                <dd className="font-semibold text-ink">{FORMATS.find((f) => f.id === format)?.title}</dd>
              </div>
              <div className="flex justify-between gap-3 py-2">
                <dt className="text-ink-faint">Partecipanti</dt>
                <dd className="text-right font-semibold text-ink">
                  {source === 'teams'
                    ? `${selectedTeamIds.length} squadre`
                    : `${qualifiedCount} qualificate${selectedQualRound ? ` · ${selectedQualRound.compName}` : ''}`}
                </dd>
              </div>
              {plan ? (
                <div className="flex justify-between gap-3 py-2">
                  <dt className="text-ink-faint">Giornate</dt>
                  <dd className="text-right font-semibold text-ink">
                    {plan.total_rounds}
                    {startMd ? ` · dalla ${startMd}ª reale` : ''}
                  </dd>
                </div>
              ) : null}
              <div className="flex justify-between gap-3 py-2">
                <dt className="text-ink-faint">Premi</dt>
                <dd className="text-right font-semibold text-ink">
                  {prizes.filter((p) => p.name.trim()).length
                    ? prizes
                        .filter((p) => p.name.trim())
                        .map((p) => `${p.icon ?? ''} ${p.name}`)
                        .join(', ')
                    : 'nessuno'}
                </dd>
              </div>
            </dl>

            {error ? <div className="mt-3 rounded-xl bg-bad-bg p-3 text-sm text-bad">{error}</div> : null}

            <div className="mt-4 flex items-center justify-between">
              <Button variant="ghost" onClick={() => setStep(3)} disabled={busy}>
                ← Indietro
              </Button>
              <Button onClick={handleCreate} disabled={busy || issues.length > 0}>
                {busy ? 'Creazione…' : 'Crea competizione'}
              </Button>
            </div>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
