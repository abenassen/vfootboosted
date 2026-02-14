import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  addRosterPlayer,
  buildDefaultCompetitionStages,
  concludeLeagueMatchday,
  bulkAssignRoster,
  closeNomination,
  createCompetitionStage,
  createCompetitionPrize,
  createAuction,
  addCompetitionStageRule,
  createCompetitionTemplate,
  deleteCompetition,
  deleteCompetitionPrize,
  deleteCompetitionStage,
  createLeague,
  getCompetitionStages,
  getAuctionState,
  getCompetitions,
  getLeagueDetail,
  getLeagueMatchdays,
  getTeamRoster,
  importRosterCsv,
  joinLeague,
  nominateNext,
  placeBid,
  previewCompetitionSchedule,
  removeRosterPlayer,
  scheduleCompetition,
  searchPlayers,
  setMarketStatus,
  updateCompetitionStage,
  updateCompetition,
  updateMemberRole,
} from '../api';
import { useAuth } from '../auth/AuthContext';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type {
  AuctionState,
  CompetitionItem,
  CompetitionSchedulePreview,
  CompetitionStageItem,
  LeagueDetail,
  LeagueMatchdayItem,
  PlayerSearchItem,
  TeamRoster,
} from '../types/league';

type AdminTab = 'user' | 'league';
type LeagueTab = 'overview' | 'roster' | 'competitions' | 'matchdays' | 'auction';

export default function LeagueAdminPage() {
  const [searchParams] = useSearchParams();
  const { user } = useAuth();
  const { leagues, selectedLeagueId, selectedLeague, setSelectedLeagueId, refreshLeagues } = useLeagueContext();

  const [activeTab, setActiveTab] = useState<AdminTab>('user');
  const [leagueTab, setLeagueTab] = useState<LeagueTab>('overview');

  const [league, setLeague] = useState<LeagueDetail | null>(null);
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);
  const [roster, setRoster] = useState<TeamRoster | null>(null);

  const [createName, setCreateName] = useState('');
  const [createTeam, setCreateTeam] = useState('');
  const [joinCode, setJoinCode] = useState('');
  const [joinTeam, setJoinTeam] = useState('');

  const [playerQuery, setPlayerQuery] = useState('');
  const [playerResults, setPlayerResults] = useState<PlayerSearchItem[]>([]);
  const [selectedPlayer, setSelectedPlayer] = useState<PlayerSearchItem | null>(null);
  const [manualPrice, setManualPrice] = useState('1');

  const [bulkAssignmentsText, setBulkAssignmentsText] = useState('team_name,player_id,price\n');
  const [csvText, setCsvText] = useState('team_name,manager_username,player_id,price\n');
  const [csvFile, setCsvFile] = useState<File | null>(null);

  const [compName, setCompName] = useState('');
  const [compCreateMacro, setCompCreateMacro] = useState<'none' | 'round_robin' | 'knockout'>('none');
  const [compWizardStartsAt, setCompWizardStartsAt] = useState('');
  const [compWizardEndsAt, setCompWizardEndsAt] = useState('');
  const [competitions, setCompetitions] = useState<CompetitionItem[]>([]);
  const [selectedCompetitionId, setSelectedCompetitionId] = useState<number | null>(null);
  const [compStartsAt, setCompStartsAt] = useState('');
  const [compEndsAt, setCompEndsAt] = useState('');

  const [auctionPlayerIds, setAuctionPlayerIds] = useState('');
  const [auctionId, setAuctionId] = useState<number | null>(null);
  const [auctionState, setAuctionState] = useState<AuctionState | null>(null);
  const [nominationId, setNominationId] = useState<number | null>(null);
  const [bidAmount, setBidAmount] = useState('1');
  const [matchdays, setMatchdays] = useState<LeagueMatchdayItem[]>([]);
  const [competitionStages, setCompetitionStages] = useState<CompetitionStageItem[]>([]);
  const [leagueStageOptions, setLeagueStageOptions] = useState<Array<{ stage_id: number; competition_id: number; label: string }>>([]);
  const [newStageName, setNewStageName] = useState('Regular season');
  const [newStageType, setNewStageType] = useState<'round_robin' | 'knockout'>('round_robin');
  const [newStageOrder, setNewStageOrder] = useState('1');
  const [newStageTeamIds, setNewStageTeamIds] = useState<number[]>([]);
  const [manualStageTeamToAdd, setManualStageTeamToAdd] = useState<number | null>(null);
  const [selectedEditStageId, setSelectedEditStageId] = useState<number | null>(null);
  const [autoselectStageOnLoad, setAutoselectStageOnLoad] = useState(false);
  const [stageParticipantMode, setStageParticipantMode] = useState<'manual' | 'derived'>('manual');
  const [stageRuleSourceId, setStageRuleSourceId] = useState<number | null>(null);
  const [stageRuleMode, setStageRuleMode] = useState<'winners' | 'losers' | 'table_range'>('winners');
  const [stageRuleRankFrom, setStageRuleRankFrom] = useState('1');
  const [stageRuleRankTo, setStageRuleRankTo] = useState('1');
  const [prizeName, setPrizeName] = useState('');
  const [prizeConditionType, setPrizeConditionType] = useState<'final_table_range' | 'stage_table_range' | 'stage_winner' | 'stage_loser'>('final_table_range');
  const [prizeStageId, setPrizeStageId] = useState<number | null>(null);
  const [prizeRankFrom, setPrizeRankFrom] = useState('1');
  const [prizeRankTo, setPrizeRankTo] = useState('1');
  const [schedulePreview, setSchedulePreview] = useState<CompetitionSchedulePreview | null>(null);
  const [roundMappingDraft, setRoundMappingDraft] = useState<Record<string, string>>({});

  const [msg, setMsg] = useState<string>('');
  const [msgTone, setMsgTone] = useState<'info' | 'success' | 'warning' | 'error'>('info');
  const [busy, setBusy] = useState(false);

  const selectedTeamName = useMemo(
    () => league?.teams.find((t) => t.team_id === selectedTeamId)?.name ?? '',
    [league, selectedTeamId]
  );
  const selectedCompetition = useMemo(
    () => competitions.find((c) => c.competition_id === selectedCompetitionId) ?? null,
    [competitions, selectedCompetitionId]
  );
  const stageOptionsByCompetition = useMemo(() => {
    const grouped = new Map<number, { competitionName: string; items: Array<{ stage_id: number; label: string }> }>();
    leagueStageOptions.forEach((opt) => {
      const comp = competitions.find((c) => c.competition_id === opt.competition_id);
      const competitionName = comp?.name ?? `Competition ${opt.competition_id}`;
      if (!grouped.has(opt.competition_id)) {
        grouped.set(opt.competition_id, { competitionName, items: [] });
      }
      grouped.get(opt.competition_id)!.items.push({
        stage_id: opt.stage_id,
        label: opt.label.replace(`${competitionName} > `, ''),
      });
    });
    return [...grouped.entries()].map(([competitionId, data]) => ({
      competitionId,
      competitionName: data.competitionName,
      items: data.items,
    }));
  }, [leagueStageOptions, competitions]);
  const selectedEditStage = useMemo(
    () => competitionStages.find((s) => s.stage_id === selectedEditStageId) ?? null,
    [competitionStages, selectedEditStageId]
  );
  const stageParticipantEntries = useMemo(() => {
    const manualNames = new Set<number>();
    const manual = newStageTeamIds
      .map((teamId) => {
        const t = league?.teams.find((x) => x.team_id === teamId);
        if (!t) return null;
        manualNames.add(teamId);
        return { kind: 'manual' as const, key: `m-${teamId}`, label: `${t.name} (${t.manager_username})`, teamId };
      })
      .filter((x): x is { kind: 'manual'; key: string; label: string; teamId: number } => !!x);

    const derived = (selectedEditStage?.rules_in ?? []).map((r) => ({
      kind: 'derived' as const,
      key: `d-${r.rule_id}`,
      label: `${formatRuleModeLabel(r.mode, r.rank_from, r.rank_to)} da ${r.source_competition_name ? `${r.source_competition_name} / ` : ''}${r.source_stage_name}`,
    }));

    return [...manual, ...derived];
  }, [newStageTeamIds, league?.teams, selectedEditStage]);
  const manualAddableTeams = useMemo(
    () => (league?.teams ?? []).filter((t) => !newStageTeamIds.includes(t.team_id)),
    [league?.teams, newStageTeamIds]
  );

  async function loadLeagueDetail(leagueId: number) {
    const d = await getLeagueDetail(leagueId);
    setLeague(d);
    if (d.teams.length && !selectedTeamId) {
      setSelectedTeamId(d.teams[0].team_id);
    }
  }

  async function loadRoster(leagueId: number, teamId: number) {
    const r = await getTeamRoster(leagueId, teamId);
    setRoster(r);
  }

  async function loadCompetitions(leagueId: number) {
    const c = await getCompetitions(leagueId);
    setCompetitions(c);
    if (!selectedCompetitionId && c.length) {
      setSelectedCompetitionId(c[0].competition_id);
    }
    const allStages = await Promise.all(
      c.map(async (comp) => {
        try {
          const stages = await getCompetitionStages(comp.competition_id);
          return stages.map((s) => ({
            stage_id: s.stage_id,
            competition_id: comp.competition_id,
            label: `${comp.name} > #${s.order_index} ${s.name}`,
          }));
        } catch {
          return [];
        }
      })
    );
    setLeagueStageOptions(allStages.flat());
  }

  async function loadAuctionState(currentAuctionId: number) {
    const s = await getAuctionState(currentAuctionId);
    setAuctionState(s);
  }

  async function loadMatchdays(leagueId: number) {
    const items = await getLeagueMatchdays(leagueId);
    setMatchdays(items);
  }

  async function loadCompetitionStages(competitionId: number) {
    const items = await getCompetitionStages(competitionId);
    setCompetitionStages(items);
  }

  useEffect(() => {
    const tab = searchParams.get('tab');
    if (tab === 'league') setActiveTab('league');
    if (tab === 'user') setActiveTab('user');
  }, [searchParams]);

  useEffect(() => {
    if (!selectedLeagueId) {
      setLeague(null);
      setRoster(null);
      setCompetitions([]);
      setMatchdays([]);
      setLeagueStageOptions([]);
      return;
    }
    void loadLeagueDetail(selectedLeagueId).catch((e) => setMsg(`Errore dettaglio lega: ${e.message}`));
    void loadCompetitions(selectedLeagueId).catch((e) => setMsg(`Errore competizioni: ${e.message}`));
    void loadMatchdays(selectedLeagueId).catch((e) => setMsg(`Errore matchdays: ${e.message}`));
  }, [selectedLeagueId]);

  useEffect(() => {
    if (!selectedCompetitionId) {
      setCompetitionStages([]);
      return;
    }
    void loadCompetitionStages(selectedCompetitionId).catch(() => setCompetitionStages([]));
  }, [selectedCompetitionId]);

  useEffect(() => {
    if (!selectedCompetition) {
      setCompStartsAt('');
      setCompEndsAt('');
      setSchedulePreview(null);
      setRoundMappingDraft({});
      setPrizeStageId(null);
      setSelectedEditStageId(null);
      setAutoselectStageOnLoad(false);
      if (!compName.trim()) {
        setCompName(nextAvailableCompetitionName());
      }
      return;
    }
    setCompStartsAt(selectedCompetition.starts_at ?? '');
    setCompEndsAt(selectedCompetition.ends_at ?? '');
    setSchedulePreview(null);
    setRoundMappingDraft({});
    setPrizeStageId(null);
    setSelectedEditStageId(null);
    setAutoselectStageOnLoad(true);
  }, [selectedCompetition]);

  useEffect(() => {
    if (!league?.teams.length) return;
    setNewStageTeamIds(league.teams.map((t) => t.team_id));
    setManualStageTeamToAdd(league.teams[0]?.team_id ?? null);
  }, [league?.teams]);

  useEffect(() => {
    const nextOrder = (competitionStages.reduce((mx, s) => Math.max(mx, s.order_index), 0) || 0) + 1;
    setNewStageOrder(String(nextOrder));
  }, [competitionStages]);

  useEffect(() => {
    if (!selectedEditStageId) return;
    const st = competitionStages.find((x) => x.stage_id === selectedEditStageId);
    if (!st) return;
    setNewStageName(st.name);
    setNewStageType(st.stage_type);
    setNewStageOrder(String(st.order_index));
    setNewStageTeamIds(st.participants.filter((p) => p.source === 'manual').map((p) => p.team_id));
  }, [selectedEditStageId, competitionStages]);

  useEffect(() => {
    if (!manualAddableTeams.length) {
      setManualStageTeamToAdd(null);
      return;
    }
    if (!manualStageTeamToAdd || !manualAddableTeams.some((t) => t.team_id === manualStageTeamToAdd)) {
      setManualStageTeamToAdd(manualAddableTeams[0].team_id);
    }
  }, [manualAddableTeams, manualStageTeamToAdd]);

  useEffect(() => {
    if (!autoselectStageOnLoad) return;
    if (!competitionStages.length) {
      setSelectedEditStageId(null);
      setAutoselectStageOnLoad(false);
      return;
    }
    const sorted = [...competitionStages].sort((a, b) => (a.order_index - b.order_index) || (a.stage_id - b.stage_id));
    setSelectedEditStageId(sorted[0].stage_id);
    setAutoselectStageOnLoad(false);
  }, [autoselectStageOnLoad, competitionStages]);

  useEffect(() => {
    if (!selectedLeagueId || !selectedTeamId) return;
    void loadRoster(selectedLeagueId, selectedTeamId).catch((e) => setMsg(`Errore roster: ${e.message}`));
  }, [selectedLeagueId, selectedTeamId]);

  useEffect(() => {
    if (!selectedLeagueId || playerQuery.trim().length < 2) {
      setPlayerResults([]);
      return;
    }

    const t = window.setTimeout(() => {
      void searchPlayers(playerQuery, selectedLeagueId)
        .then(setPlayerResults)
        .catch(() => setPlayerResults([]));
    }, 250);

    return () => window.clearTimeout(t);
  }, [playerQuery, selectedLeagueId]);

  useEffect(() => {
    if (!msg) {
      setMsgTone('info');
      return;
    }
    const low = msg.toLowerCase();
    if (low.startsWith('api ') || low.startsWith('errore') || low.includes('failed') || low.includes('error')) {
      setMsgTone('error');
      return;
    }
    if (low.includes('in attesa') || low.includes('warning') || low.includes('attenzione')) {
      setMsgTone('warning');
      return;
    }
    if (
      low.includes('creat') ||
      low.includes('aggiornat') ||
      low.includes('aggiunt') ||
      low.includes('conclus')
    ) {
      setMsgTone('success');
      return;
    }
    setMsgTone('info');
  }, [msg]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setMsg('');
    try {
      await action();
    } catch (e) {
      setMsgTone('error');
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function parseIds(input: string): number[] {
    return input
      .split(/[\s,;]+/)
      .map((x) => Number(x.trim()))
      .filter((x) => Number.isFinite(x) && x > 0);
  }

  function parseAssignments(input: string): Array<{ team_name: string; player_id: number; price: number }> {
    return input
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => line.split(',').map((x) => x.trim()))
      .filter((cols) => cols.length >= 2)
      .map((cols) => ({
        team_name: cols[0],
        player_id: Number(cols[1]),
        price: Number(cols[2] || '1'),
      }))
      .filter((r) => r.team_name.length > 0 && Number.isFinite(r.player_id) && r.player_id > 0);
  }

  function concludeDisabledReason(md: LeagueMatchdayItem): string | null {
    if (md.status === 'concluded') return 'Gia conclusa';
    if (!md.real_completion.is_completed) return 'Giornata reale non completata';
    if (md.fixtures.total === 0) return 'Nessuna fixture fantasy associata';
    return null;
  }

  function formatRuleModeLabel(mode: 'winners' | 'losers' | 'table_range', rankFrom?: number | null, rankTo?: number | null): string {
    if (mode === 'winners') return 'Vincitore';
    if (mode === 'losers') return 'Sconfitto';
    const rf = rankFrom ?? 1;
    const rt = rankTo ?? rf;
    return rf === rt ? `${rf}° classificato` : `Classificati ${rf}-${rt}`;
  }

  function nextAvailableCompetitionName(): string {
    const used = new Set(competitions.map((c) => c.name.trim().toLowerCase()));
    const base = 'Nuova competizione';
    if (!used.has(base.toLowerCase())) return base;
    let i = 2;
    while (used.has(`${base} ${i}`.toLowerCase())) i += 1;
    return `${base} ${i}`;
  }

  function formatDeletionDependencyError(err: unknown): Error {
    if (!(err instanceof Error)) return new Error(String(err));
    const msg = err.message ?? '';
    const marker = 'API 400:';
    const idx = msg.indexOf(marker);
    if (idx < 0) return err;

    const raw = msg.slice(idx + marker.length).trim();
    try {
      const payload = JSON.parse(raw) as {
        detail?: string;
        dependent_targets?: Array<{
          target_competition_name?: string;
          target_stage_name?: string;
          mode?: string;
          rank_from?: number | null;
          rank_to?: number | null;
        }>;
        dependent_competitions?: Array<{
          competition_name?: string;
          mode?: string;
          source_stage?: string;
          rank_from?: number | null;
          rank_to?: number | null;
        }>;
        dependent_prizes?: Array<{
          competition_name?: string;
          prize_name?: string;
          source_stage_name?: string | null;
        }>;
      };

      const chunks: string[] = [];

      if (payload.dependent_targets?.length) {
        const shown = payload.dependent_targets.slice(0, 3).map((d) => {
          const mode = d.mode ?? 'rule';
          const suffix =
            mode === 'table_range' && d.rank_from
              ? ` (${d.rank_from}${d.rank_to && d.rank_to !== d.rank_from ? `-${d.rank_to}` : ''})`
              : '';
          return `${d.target_competition_name ?? 'Comp'} / ${d.target_stage_name ?? 'Stage'} via ${mode}${suffix}`;
        });
        const more = payload.dependent_targets.length > 3 ? ` (+${payload.dependent_targets.length - 3} altre)` : '';
        chunks.push(`Dipendenze stage: ${shown.join('; ')}${more}`);
      }

      if (payload.dependent_competitions?.length) {
        const shown = payload.dependent_competitions.slice(0, 3).map((d) => {
          const mode = d.mode ?? 'rule';
          return `${d.competition_name ?? 'Comp'} via ${mode}/${d.source_stage ?? 'final'}`;
        });
        const more = payload.dependent_competitions.length > 3 ? ` (+${payload.dependent_competitions.length - 3} altre)` : '';
        chunks.push(`Dipendenze competizione: ${shown.join('; ')}${more}`);
      }

      if (payload.dependent_prizes?.length) {
        const shown = payload.dependent_prizes.slice(0, 3).map((d) => `${d.competition_name ?? 'Comp'}: ${d.prize_name ?? 'Premio'}`);
        const more = payload.dependent_prizes.length > 3 ? ` (+${payload.dependent_prizes.length - 3} altri)` : '';
        chunks.push(`Premi collegati: ${shown.join('; ')}${more}`);
      }

      if (chunks.length) {
        return new Error(`${payload.detail ?? 'Eliminazione bloccata.'} ${chunks.join(' | ')}`);
      }
      if (payload.detail) return new Error(payload.detail);
      return err;
    } catch {
      return err;
    }
  }

  async function reloadSchedulePreview(competitionId: number) {
    const preview = await previewCompetitionSchedule(competitionId, {
      starts_at: compStartsAt || null,
      ends_at: compEndsAt || null,
    });
    setSchedulePreview(preview);
    const next: Record<string, string> = {};
    for (const rno of preview.rounds) {
      const key = String(rno);
      const manual = preview.current_mapping[key] ?? preview.proposed_mapping[key];
      next[key] = manual !== undefined ? String(manual) : '';
    }
    setRoundMappingDraft(next);
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <SectionTitle>Administration</SectionTitle>
        <div className="mt-2 text-sm text-slate-600">Separazione tra gestione utente e gestione della lega.</div>

        <div className="mt-4 inline-flex rounded-xl bg-slate-100 p-1">
          <button
            type="button"
            onClick={() => setActiveTab('user')}
            className={activeTab === 'user' ? 'rounded-lg bg-white px-3 py-2 text-sm font-semibold' : 'px-3 py-2 text-sm font-semibold text-slate-600'}
          >
            User Admin
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('league')}
            className={activeTab === 'league' ? 'rounded-lg bg-white px-3 py-2 text-sm font-semibold' : 'px-3 py-2 text-sm font-semibold text-slate-600'}
          >
            League Admin
          </button>
        </div>

        {msg ? (
          <div
            className={`mt-3 rounded-xl px-3 py-2 text-sm ${
              msgTone === 'error'
                ? 'bg-rose-50 text-rose-700'
                : msgTone === 'warning'
                  ? 'bg-amber-50 text-amber-700'
                  : msgTone === 'success'
                    ? 'bg-emerald-50 text-emerald-700'
                    : 'bg-slate-100 text-slate-700'
            }`}
            role="status"
            aria-live="polite"
          >
            <span className="mr-2 font-semibold">
              {msgTone === 'error' ? 'Errore' : msgTone === 'warning' ? 'Attenzione' : msgTone === 'success' ? 'OK' : 'Info'}:
            </span>
            {msg}
          </div>
        ) : null}
      </Card>

      {activeTab === 'user' ? (
        <>
          <Card className="p-4">
            <SectionTitle>User Profile</SectionTitle>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
              <Badge tone="slate">{user?.username ?? 'Utente'}</Badge>
              <span className="text-slate-600">{user?.email || 'Email non impostata'}</span>
            </div>
            <div className="mt-2 text-xs text-slate-500">Modifica profilo/password: da aggiungere con endpoint dedicati.</div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="p-4">
              <SectionTitle>Crea Lega</SectionTitle>
              <form
                className="mt-3 space-y-2"
                onSubmit={(e: FormEvent) => {
                  e.preventDefault();
                  void run(async () => {
                    const res = await createLeague({ name: createName, team_name: createTeam });
                    setMsg(`Lega creata. Invite code: ${res.invite_code}`);
                    setCreateName('');
                    setCreateTeam('');
                    await refreshLeagues();
                    setSelectedLeagueId(res.league_id);
                  });
                }}
              >
                <input className="w-full rounded-xl border px-3 py-2" placeholder="Nome lega" value={createName} onChange={(e) => setCreateName(e.target.value)} required />
                <input className="w-full rounded-xl border px-3 py-2" placeholder="Nome tua squadra" value={createTeam} onChange={(e) => setCreateTeam(e.target.value)} required />
                <Button type="submit" disabled={busy}>Crea</Button>
              </form>
            </Card>

            <Card className="p-4">
              <SectionTitle>Unisciti a Lega</SectionTitle>
              <form
                className="mt-3 space-y-2"
                onSubmit={(e: FormEvent) => {
                  e.preventDefault();
                  void run(async () => {
                    const res = await joinLeague({ invite_code: joinCode, team_name: joinTeam });
                    setMsg('Join completato');
                    setJoinCode('');
                    setJoinTeam('');
                    await refreshLeagues();
                    setSelectedLeagueId(res.league_id);
                  });
                }}
              >
                <input className="w-full rounded-xl border px-3 py-2" placeholder="Invite code" value={joinCode} onChange={(e) => setJoinCode(e.target.value)} required />
                <input className="w-full rounded-xl border px-3 py-2" placeholder="Nome squadra" value={joinTeam} onChange={(e) => setJoinTeam(e.target.value)} required />
                <Button type="submit" disabled={busy}>Join</Button>
              </form>
            </Card>
          </div>

          <Card className="p-4">
            <SectionTitle>Le Tue Leghe</SectionTitle>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <select
                className="rounded-xl border px-3 py-2 text-sm"
                value={selectedLeagueId ?? ''}
                onChange={(e) => setSelectedLeagueId(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">Seleziona lega</option>
                {leagues.map((l) => (
                  <option key={l.league_id} value={l.league_id}>
                    {l.name} ({l.role})
                  </option>
                ))}
              </select>
              <Button size="sm" variant="secondary" onClick={() => setActiveTab('league')} disabled={!selectedLeagueId}>
                Vai a League Admin
              </Button>
              {selectedLeague ? <Badge tone={selectedLeague.market_open ? 'green' : 'red'}>Mercato {selectedLeague.market_open ? 'aperto' : 'chiuso'}</Badge> : null}
            </div>
          </Card>
        </>
      ) : (
        <>
          <Card className="p-4">
            <SectionTitle>Lega Selezionata</SectionTitle>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <select
                className="rounded-xl border px-3 py-2 text-sm"
                value={selectedLeagueId ?? ''}
                onChange={(e) => setSelectedLeagueId(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">Seleziona lega</option>
                {leagues.map((l) => (
                  <option key={l.league_id} value={l.league_id}>
                    {l.name} ({l.role})
                  </option>
                ))}
              </select>
              {selectedLeague ? <Badge tone={selectedLeague.market_open ? 'green' : 'red'}>Mercato {selectedLeague.market_open ? 'aperto' : 'chiuso'}</Badge> : null}
            </div>

            {league ? (
              <div className="mt-3 space-y-3 text-sm">
                <div>
                  <span className="font-semibold">Invite code:</span> {league.invite_code}
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={() =>
                      void run(async () => {
                        if (!league) return;
                        await setMarketStatus(league.league_id, !league.market_open);
                        await loadLeagueDetail(league.league_id);
                        await refreshLeagues();
                      })
                    }
                  >
                    {league.market_open ? 'Chiudi mercato' : 'Apri mercato'}
                  </Button>
                </div>
                <div>
                  <div className="font-semibold">Membri</div>
                  <div className="mt-2 space-y-1">
                    {(() => {
                      const adminCount = league.members.filter((x) => x.role === 'admin').length;
                      return league.members.map((m) => {
                        const demoting = m.role === 'admin';
                        const isLastAdmin = demoting && adminCount <= 1;
                        const nextRole = demoting ? 'manager' : 'admin';
                        return (
                          <div key={m.membership_id} className="flex items-center justify-between rounded-xl border px-3 py-2">
                            <span>{m.username}</span>
                            <div className="flex items-center gap-2">
                              <Badge tone={m.role === 'admin' ? 'green' : 'slate'}>{m.role}</Badge>
                              <Button
                                size="sm"
                                variant="secondary"
                                disabled={isLastAdmin}
                                onClick={() =>
                                  void run(async () => {
                                    if (!league) return;
                                    if (m.user_id === user?.id && demoting) {
                                      const confirmed = window.confirm(
                                        'Confermi di rimuovere il tuo ruolo admin? Potrai perdere accesso alle funzioni di amministrazione.'
                                      );
                                      if (!confirmed) return;
                                    }
                                    await updateMemberRole(league.league_id, m.membership_id, nextRole);
                                    await loadLeagueDetail(league.league_id);
                                  })
                                }
                              >
                                Toggle
                              </Button>
                              {isLastAdmin ? <span className="text-xs text-amber-600">last admin</span> : null}
                            </div>
                          </div>
                        );
                      });
                    })()}
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                Seleziona una lega dal menu. Le funzioni avanzate sono disponibili solo su una lega selezionata.
              </div>
            )}
          </Card>

          {league ? (
            <>
              <Card className="p-4">
                <div className="inline-flex rounded-xl bg-slate-100 p-1">
                  {([
                    ['overview', 'Overview'],
                    ['roster', 'Roster'],
                    ['competitions', 'Competizioni'],
                    ['matchdays', 'Matchdays'],
                    ['auction', 'Asta'],
                  ] as Array<[LeagueTab, string]>).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setLeagueTab(id)}
                      className={leagueTab === id ? 'rounded-lg bg-white px-3 py-2 text-sm font-semibold' : 'px-3 py-2 text-sm font-semibold text-slate-600'}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </Card>

              {leagueTab === 'overview' ? (
                <Card className="p-4">
                  <SectionTitle>League Admin Overview</SectionTitle>
                  <ul className="mt-3 space-y-2 text-sm text-slate-700">
                    <li>• Roster: gestione giocatori per ciascun team della lega.</li>
                    <li>• Competizioni: crea round robin / knockout dai team partecipanti.</li>
                    <li>• Asta: controlla chiamate, cronologia e budget disponibili.</li>
                  </ul>
                </Card>
              ) : null}

              {leagueTab === 'roster' ? (
                <div className="grid gap-4 lg:grid-cols-2">
                  <Card className="p-4">
                    <SectionTitle>Roster Team</SectionTitle>
                    <div className="mt-2 text-xs text-slate-500">I nomi qui sotto (es. Alpha/Beta) sono i team fantasy della lega, non calciatori reali.</div>
                    <div className="mt-2">
                      <label htmlFor="roster-team-select" className="mb-1 block text-xs font-semibold text-slate-500">Fantasy Team</label>
                      <select id="roster-team-select" className="w-full rounded-xl border px-3 py-2 text-sm" value={selectedTeamId ?? ''} onChange={(e) => setSelectedTeamId(Number(e.target.value))}>
                        {league.teams.map((t) => (
                          <option key={t.team_id} value={t.team_id}>{t.name}</option>
                        ))}
                      </select>
                    </div>

                    <div className="mt-3 rounded-xl border p-3">
                      <div className="text-xs font-semibold text-slate-500">Aggiungi giocatore per nome</div>
                      <label htmlFor="roster-player-search" className="sr-only">Cerca giocatore</label>
                      <input
                        id="roster-player-search"
                        className="mt-2 w-full rounded-xl border px-3 py-2 text-sm"
                        placeholder="Cerca giocatore (es. Lautaro, Leao...)"
                        value={playerQuery}
                        onChange={(e) => {
                          setPlayerQuery(e.target.value);
                          setSelectedPlayer(null);
                        }}
                      />
                      {playerResults.length ? (
                        <div className="mt-2 max-h-36 overflow-auto space-y-1">
                          {playerResults.map((p) => (
                            <button
                              key={p.player_id}
                              type="button"
                              className="w-full rounded-lg border px-2 py-1 text-left text-xs hover:bg-slate-50"
                              onClick={() => {
                                setSelectedPlayer(p);
                                setPlayerQuery(p.full_name);
                              }}
                            >
                              {p.full_name} <span className="text-slate-400">(id {p.player_id})</span>
                            </button>
                          ))}
                        </div>
                      ) : null}

                      <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_120px_auto]">
                        <div className="rounded-xl border bg-slate-50 px-3 py-2 text-sm">
                          {selectedPlayer ? `Selezionato: ${selectedPlayer.full_name}` : 'Seleziona un giocatore dalla ricerca'}
                        </div>
                        <label htmlFor="roster-player-price" className="sr-only">Prezzo acquisto</label>
                        <input id="roster-player-price" className="rounded-xl border px-3 py-2 text-sm" placeholder="Prezzo" value={manualPrice} onChange={(e) => setManualPrice(e.target.value)} />
                        <Button
                          size="sm"
                          onClick={() =>
                            void run(async () => {
                              if (!selectedLeagueId || !selectedTeamId || !selectedPlayer) return;
                              await addRosterPlayer(selectedLeagueId, selectedTeamId, selectedPlayer.player_id, Number(manualPrice));
                              await loadRoster(selectedLeagueId, selectedTeamId);
                              setPlayerQuery('');
                              setPlayerResults([]);
                              setSelectedPlayer(null);
                            })
                          }
                        >
                          Add
                        </Button>
                      </div>
                    </div>

                    <div className="mt-3 rounded-xl border p-3">
                      <div className="text-xs font-semibold text-slate-500">Assegnazione bulk per roster (deterministica)</div>
                      <div className="mt-1 text-xs text-slate-500">Usa il nome del team fantasy (non ID): <code>team_name,player_id,price</code>.</div>
                      <label htmlFor="roster-bulk-textarea" className="sr-only">Dati assegnazione bulk</label>
                      <textarea
                        id="roster-bulk-textarea"
                        className="mt-2 h-20 w-full rounded-xl border px-3 py-2 text-xs"
                        placeholder={'team_name,player_id,price\nAlpha,101,12\nBeta,102,8'}
                        value={bulkAssignmentsText}
                        onChange={(e) => setBulkAssignmentsText(e.target.value)}
                      />
                      <Button
                        size="sm"
                        className="mt-2"
                        onClick={() =>
                          void run(async () => {
                            if (!selectedLeagueId) return;
                            const assignments = parseAssignments(
                              bulkAssignmentsText
                                .split('\n')
                                .slice(1)
                                .join('\n')
                            );
                            if (!assignments.length) {
                              setMsg('Inserisci almeno una riga valida nel formato team_name,player_id,price');
                              return;
                            }
                            await bulkAssignRoster(selectedLeagueId, { assignments });
                            if (selectedTeamId) await loadRoster(selectedLeagueId, selectedTeamId);
                          })
                        }
                      >
                        Esegui assegnazione bulk
                      </Button>
                    </div>

                    <div className="mt-3 rounded-xl border p-3">
                      <div className="text-xs font-semibold text-slate-500">Import roster da CSV</div>
                      <div className="mt-1 text-xs text-slate-500">Import tecnico per riempire i roster in blocco. Colonne supportate: <code>team_name</code> oppure <code>manager_username</code>, più <code>player_id</code> e <code>price</code>. Puoi usare testo oppure file .csv.</div>
                      <label htmlFor="roster-csv-file" className="sr-only">Seleziona file CSV</label>
                      <input
                        id="roster-csv-file"
                        type="file"
                        accept=".csv,text/csv"
                        className="mt-2 block w-full rounded-xl border px-3 py-2 text-xs"
                        onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
                      />
                      <label htmlFor="roster-csv-text" className="sr-only">Testo CSV roster</label>
                      <textarea
                        id="roster-csv-text"
                        className="mt-2 h-24 w-full rounded-xl border px-3 py-2 text-xs"
                        value={csvText}
                        onChange={(e) => setCsvText(e.target.value)}
                      />
                      <Button
                        size="sm"
                        className="mt-2"
                        onClick={() =>
                          void run(async () => {
                            if (!selectedLeagueId) return;
                            if (!csvFile && !csvText.trim()) {
                              setMsg('Inserisci CSV nel box oppure seleziona un file .csv');
                              return;
                            }
                            await importRosterCsv(selectedLeagueId, csvText, csvFile);
                            if (selectedTeamId) await loadRoster(selectedLeagueId, selectedTeamId);
                            setCsvFile(null);
                          })
                        }
                      >
                        Import CSV
                      </Button>
                    </div>
                  </Card>

                  <Card className="p-4">
                    <SectionTitle>Roster corrente</SectionTitle>
                    <div className="mt-2 text-sm text-slate-600">Team: <span className="font-semibold">{selectedTeamName || '-'}</span></div>
                    <div className="mt-2 max-h-[520px] overflow-auto space-y-1 text-xs">
                      {roster?.players.length ? (
                        roster.players.map((p) => (
                          <div key={p.player_id} className="flex items-center justify-between rounded-lg border px-2 py-1">
                            <span>#{p.player_id} {p.name} (EUR {p.price})</span>
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() =>
                                void run(async () => {
                                  if (!selectedLeagueId || !selectedTeamId) return;
                                  await removeRosterPlayer(selectedLeagueId, selectedTeamId, p.player_id);
                                  await loadRoster(selectedLeagueId, selectedTeamId);
                                })
                              }
                            >
                              Remove
                            </Button>
                          </div>
                        ))
                      ) : (
                        <div className="text-slate-500">Nessun giocatore nel roster.</div>
                      )}
                    </div>
                  </Card>
                </div>
              ) : null}

              {leagueTab === 'competitions' ? (
                <div className="space-y-4">
                  <Card className="p-4">
                    <SectionTitle>Competition Builder</SectionTitle>
                    <div className="mt-2 text-xs text-slate-600">
                      Flusso lineare: 1) crea contenitore competizione, 2) aggiungi sottocompetizioni (stage), 3) collega qualificazioni tra stage, 4) pianifica round su matchday reali.
                    </div>
                  </Card>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <Card className="p-4 lg:col-span-2">
                      <SectionTitle>1. Seleziona O Crea Competizione</SectionTitle>
                      <div className="mt-2 text-xs text-slate-500">Usa il menu per aprire una competizione esistente oppure scegli "Nuova competizione".</div>
                      <select
                        className="mt-3 w-full rounded-xl border px-3 py-2 text-sm"
                        value={selectedCompetitionId ?? '__new__'}
                        onChange={(e) => {
                          if (e.target.value === '__new__') {
                            setSelectedCompetitionId(null);
                            setCompName(nextAvailableCompetitionName());
                            return;
                          }
                          setSelectedCompetitionId(Number(e.target.value));
                        }}
                      >
                        <option value="__new__">+ Nuova competizione</option>
                        {competitions.map((c) => (
                          <option key={c.competition_id} value={c.competition_id}>
                            {c.name} ({c.competition_type})
                          </option>
                        ))}
                      </select>

                      {!selectedCompetition ? (
                        <div className="mt-3 space-y-2">
                          <input className="w-full rounded-xl border px-3 py-2 text-sm" value={compName} onChange={(e) => setCompName(e.target.value)} placeholder="Nome competizione (es. Champions League Lega)" />
                          <div className="grid gap-2 sm:grid-cols-2">
                            <input type="date" className="rounded-xl border px-3 py-2 text-sm" value={compWizardStartsAt} onChange={(e) => setCompWizardStartsAt(e.target.value)} />
                            <input type="date" className="rounded-xl border px-3 py-2 text-sm" value={compWizardEndsAt} onChange={(e) => setCompWizardEndsAt(e.target.value)} />
                          </div>
                          <select className="w-full rounded-xl border px-3 py-2 text-sm" value={compCreateMacro} onChange={(e) => setCompCreateMacro(e.target.value as 'none' | 'round_robin' | 'knockout')}>
                            <option value="none">Nessun macro: crea solo contenitore</option>
                            <option value="round_robin">Macro: campionato round-robin (1 stage)</option>
                            <option value="knockout">Macro: torneo knockout automatico</option>
                          </select>
                          <div className="text-xs text-slate-500">Con i macro, il sistema include tutti i team della lega e genera automaticamente stage/fixture iniziali.</div>
                          <Button
                            size="sm"
                            onClick={() =>
                              void run(async () => {
                                if (!selectedLeagueId) return;
                                const macroMode = compCreateMacro !== 'none';
                                const res = await createCompetitionTemplate(selectedLeagueId, {
                                  name: compName,
                                  competition_type: macroMode ? compCreateMacro : 'round_robin',
                                  container_only: !macroMode,
                                  team_ids: macroMode ? league.teams.map((t) => t.team_id) : undefined,
                                  starts_at: compWizardStartsAt || null,
                                  ends_at: compWizardEndsAt || null,
                                });
                                if (macroMode) {
                                  await buildDefaultCompetitionStages(res.competition_id, false, 42);
                                }
                                await loadCompetitions(selectedLeagueId);
                                setSelectedCompetitionId(res.competition_id);
                                setMsg(macroMode ? `Competizione creata con macro ${compCreateMacro}` : `Competizione creata (contenitore): ${res.name}`);
                              })
                            }
                          >
                            Crea competizione
                          </Button>
                        </div>
                      ) : (
                        <div className="mt-3 rounded-xl border p-2 text-sm">
                          <div><span className="font-semibold">Stato:</span> {selectedCompetition.status}</div>
                          <div><span className="font-semibold">Fixture:</span> {selectedCompetition.fixtures.finished}/{selectedCompetition.fixtures.total}</div>
                          <div><span className="font-semibold">Stage:</span> {competitionStages.length}</div>
                          <div className="mt-2">
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() =>
                                void run(async () => {
                                  if (!selectedCompetition) return;
                                  const ok = window.confirm(
                                    `Eliminare la competizione "${selectedCompetition.name}"? Operazione irreversibile.`
                                  );
                                  if (!ok) return;
                                  try {
                                    await deleteCompetition(selectedCompetition.competition_id);
                                  } catch (e) {
                                    throw formatDeletionDependencyError(e);
                                  }
                                  setSelectedCompetitionId(null);
                                  setSelectedEditStageId(null);
                                  if (selectedLeagueId) await loadCompetitions(selectedLeagueId);
                                  setMsg('Competizione eliminata');
                                })
                              }
                            >
                              Elimina competizione
                            </Button>
                          </div>
                        </div>
                      )}
                    </Card>
                  </div>

                  {selectedCompetition ? (
                    <div className="grid gap-4 lg:grid-cols-2">
                      <Card className="p-4">
                        <SectionTitle>3. Crea/Edita Sottocompetizione (Stage)</SectionTitle>
                        <div className="mt-2 text-xs text-slate-500">Modalita partecipanti: manuale (team scelti) oppure derivata (regole da altri stage).</div>
                        <div className="mt-3 space-y-2">
                          <label htmlFor="stage-editor-select" className="block text-xs font-semibold text-slate-500">Stage da modificare</label>
                          <select
                            id="stage-editor-select"
                            className="w-full rounded-xl border px-3 py-2 text-sm"
                            value={selectedEditStageId ?? ''}
                            onChange={(e) => setSelectedEditStageId(e.target.value ? Number(e.target.value) : null)}
                          >
                            <option value="">Nuovo stage</option>
                            {competitionStages.map((s) => (
                              <option key={s.stage_id} value={s.stage_id}>#{s.order_index} {s.name}</option>
                            ))}
                          </select>
                          <label htmlFor="stage-editor-name" className="block text-xs font-semibold text-slate-500">Nome stage</label>
                          <input id="stage-editor-name" className="w-full rounded-xl border px-3 py-2 text-sm" value={newStageName} onChange={(e) => setNewStageName(e.target.value)} placeholder="Nome stage (es. Girone A, Semifinale)" />
                          <div className="grid gap-2 sm:grid-cols-2">
                            <div>
                              <label htmlFor="stage-editor-type" className="mb-1 block text-xs font-semibold text-slate-500">Formato stage</label>
                              <select id="stage-editor-type" className="w-full rounded-xl border px-3 py-2 text-sm" value={newStageType} onChange={(e) => setNewStageType(e.target.value as 'round_robin' | 'knockout')}>
                                <option value="round_robin">Round robin</option>
                                <option value="knockout">Knockout</option>
                              </select>
                            </div>
                            <div>
                              <label htmlFor="stage-editor-order" className="mb-1 block text-xs font-semibold text-slate-500">Ordine stage</label>
                              <input id="stage-editor-order" className="w-full rounded-xl border px-3 py-2 text-sm" value={newStageOrder} onChange={(e) => setNewStageOrder(e.target.value)} placeholder="Ordine stage" />
                            </div>
                          </div>

                          <div className="rounded-xl border p-2">
                            <div className="text-xs font-semibold text-slate-500">Lista partecipanti stage</div>
                            <div className="mt-2 max-h-36 space-y-1 overflow-auto text-xs">
                              {stageParticipantEntries.length ? (
                                stageParticipantEntries.map((entry) => (
                                  <div key={entry.key} className="flex items-center justify-between rounded-lg border px-2 py-1">
                                    <div className="flex items-center gap-2">
                                      <Badge tone={entry.kind === 'manual' ? 'slate' : 'amber'}>{entry.kind === 'manual' ? 'team' : 'derived'}</Badge>
                                      <span>{entry.label}</span>
                                    </div>
                                    {entry.kind === 'manual' ? (
                                      <Button
                                        size="sm"
                                        variant="secondary"
                                        onClick={() => setNewStageTeamIds((prev) => prev.filter((id) => id !== entry.teamId))}
                                      >
                                        Remove
                                      </Button>
                                    ) : null}
                                  </div>
                                ))
                              ) : (
                                <div className="text-slate-500">Nessun partecipante selezionato.</div>
                              )}
                            </div>
                          </div>

                          <div className="inline-flex rounded-xl bg-slate-100 p-1">
                            <button type="button" onClick={() => setStageParticipantMode('manual')} className={stageParticipantMode === 'manual' ? 'rounded-lg bg-white px-3 py-1 text-xs font-semibold' : 'px-3 py-1 text-xs font-semibold text-slate-600'}>Manuale</button>
                            <button type="button" onClick={() => setStageParticipantMode('derived')} className={stageParticipantMode === 'derived' ? 'rounded-lg bg-white px-3 py-1 text-xs font-semibold' : 'px-3 py-1 text-xs font-semibold text-slate-600'}>Derivata</button>
                          </div>

                          {stageParticipantMode === 'manual' ? (
                            <>
                              <div className="rounded-xl border p-2">
                                <div className="text-xs font-semibold text-slate-500">Partecipanti manuali</div>
                                <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto]">
                                  <select
                                    id="stage-manual-team-select"
                                    className="rounded-xl border px-3 py-2 text-sm"
                                    value={manualStageTeamToAdd ?? ''}
                                    onChange={(e) => setManualStageTeamToAdd(e.target.value ? Number(e.target.value) : null)}
                                  >
                                    <option value="">Seleziona team da aggiungere</option>
                                    {manualAddableTeams.map((t) => (
                                      <option key={t.team_id} value={t.team_id}>
                                        {t.name} ({t.manager_username})
                                      </option>
                                    ))}
                                  </select>
                                  <Button
                                    size="sm"
                                    variant="secondary"
                                    disabled={!manualStageTeamToAdd || manualAddableTeams.length === 0}
                                    onClick={() => {
                                      if (!manualStageTeamToAdd) return;
                                      setNewStageTeamIds((prev) => (prev.includes(manualStageTeamToAdd) ? prev : [...prev, manualStageTeamToAdd]));
                                    }}
                                  >
                                    Add
                                  </Button>
                                </div>
                                {manualAddableTeams.length === 0 ? (
                                  <div className="mt-2 text-xs text-slate-500">Tutti i team della lega sono gia presenti nello stage.</div>
                                ) : null}
                              </div>
                            </>
                          ) : (
                            <>
                              {!selectedEditStageId ? (
                                <div className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
                                  Seleziona prima uno stage esistente dal menu in alto per aggiungere regole derivate.
                                </div>
                              ) : (
                                <div className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
                                  Stage target corrente: <span className="font-semibold">#{selectedEditStage?.order_index} {selectedEditStage?.name}</span>
                                </div>
                              )}
                              <div className="text-xs text-slate-500">
                                Risoluzione automatica: se i risultati sorgente sono disponibili, i partecipanti vengono determinati subito; altrimenti al termine delle matchday rilevanti.
                              </div>
                              <label htmlFor="stage-rule-source" className="block text-xs font-semibold text-slate-500">Sorgente qualificazione</label>
                              <select id="stage-rule-source" className="w-full rounded-xl border px-3 py-2 text-sm" value={stageRuleSourceId ?? ''} onChange={(e) => setStageRuleSourceId(e.target.value ? Number(e.target.value) : null)}>
                                <option value="">Sorgente qualificazione</option>
                                {stageOptionsByCompetition.map((grp) => (
                                  <optgroup key={grp.competitionId} label={grp.competitionName}>
                                    {grp.items.map((item) => (
                                      <option key={item.stage_id} value={item.stage_id}>{item.label}</option>
                                    ))}
                                  </optgroup>
                                ))}
                              </select>
                              <label htmlFor="stage-rule-mode" className="block text-xs font-semibold text-slate-500">Criterio qualificazione</label>
                              <select id="stage-rule-mode" className="w-full rounded-xl border px-3 py-2 text-sm" value={stageRuleMode} onChange={(e) => setStageRuleMode(e.target.value as 'winners' | 'losers' | 'table_range')}>
                                <option value="winners">Vincitore dello stage sorgente</option>
                                <option value="losers">Sconfitto dello stage sorgente</option>
                                <option value="table_range">Posizione in classifica</option>
                              </select>
                              {stageRuleMode === 'table_range' ? (
                                <>
                                  <label htmlFor="stage-rule-rank" className="block text-xs font-semibold text-slate-500">Posizione in classifica</label>
                                  <input id="stage-rule-rank" className="w-full rounded-xl border px-3 py-2 text-sm" placeholder="Posizione (es. 1, 2, 3...)" value={stageRuleRankFrom} onChange={(e) => setStageRuleRankFrom(e.target.value)} />
                                </>
                              ) : null}
                              <Button
                                size="sm"
                                disabled={!selectedEditStageId}
                                onClick={() =>
                                  void run(async () => {
                                    if (!selectedEditStageId) {
                                      setMsg('Seleziona uno stage esistente da modificare.');
                                      return;
                                    }
                                    if (!stageRuleSourceId) {
                                      setMsg('Seleziona lo stage sorgente.');
                                      return;
                                    }
                                    if (selectedEditStageId === stageRuleSourceId) {
                                      setMsg('Sorgente e target non possono coincidere.');
                                      return;
                                    }
                                    const singleRank = Number(stageRuleRankFrom || 1);
                                    const created = await addCompetitionStageRule(selectedEditStageId, {
                                      source_stage_id: stageRuleSourceId,
                                      mode: stageRuleMode,
                                      rank_from: stageRuleMode === 'table_range' ? singleRank : undefined,
                                      rank_to: stageRuleMode === 'table_range' ? singleRank : undefined,
                                    });
                                    if (selectedCompetition) await loadCompetitionStages(selectedCompetition.competition_id);
                                    if (selectedLeagueId) await loadCompetitions(selectedLeagueId);
                                    const unresolved = created.resolve?.unresolved_rules ?? 0;
                                    if (unresolved > 0) {
                                      setMsg('Regola stage aggiunta. Partecipanti derivati in attesa dei risultati dello stage sorgente.');
                                    } else {
                                      setMsg('Regola stage aggiunta e partecipanti aggiornati.');
                                    }
                                  })
                                }
                              >
                                Aggiungi regola derivata
                              </Button>
                              <div className="rounded-xl border p-2 text-xs">
                                <div className="font-semibold text-slate-500">Regole derivate correnti (stage selezionato)</div>
                                <div className="mt-1 space-y-1">
                                  {selectedEditStage?.rules_in.length ? (
                                    selectedEditStage.rules_in.map((r) => (
                                      <div key={r.rule_id}>
                                        {formatRuleModeLabel(r.mode, r.rank_from, r.rank_to)} · {r.source_competition_name ? `${r.source_competition_name} / ` : ''}{r.source_stage_name}
                                      </div>
                                    ))
                                  ) : (
                                    <div className="text-slate-500">Nessuna regola derivata.</div>
                                  )}
                                </div>
                              </div>
                            </>
                          )}

                          <div className="flex flex-wrap gap-2">
                            <Button
                              size="sm"
                              onClick={() =>
                                void run(async () => {
                                  if (!selectedCompetition) return;
                                  if (selectedEditStageId) {
                                    await updateCompetitionStage(selectedEditStageId, {
                                      name: newStageName,
                                      stage_type: newStageType,
                                      order_index: Number(newStageOrder || 1),
                                      team_ids: newStageTeamIds,
                                    });
                                    setMsg('Stage aggiornato');
                                  } else {
                                    await createCompetitionStage(selectedCompetition.competition_id, {
                                      name: newStageName,
                                      stage_type: newStageType,
                                      order_index: Number(newStageOrder || 1),
                                      team_ids: newStageTeamIds,
                                    });
                                    setMsg('Stage creato');
                                  }
                                  await loadCompetitionStages(selectedCompetition.competition_id);
                                  if (selectedLeagueId) await loadCompetitions(selectedLeagueId);
                                })
                              }
                            >
                              {selectedEditStageId ? 'Salva modifiche stage' : 'Crea nuovo stage'}
                            </Button>
                            {selectedEditStageId ? (
                              <Button
                                size="sm"
                                variant="secondary"
                                onClick={() =>
                                  void run(async () => {
                                    if (!selectedEditStageId || !selectedCompetition) return;
                                    const stageToDelete = competitionStages.find((s) => s.stage_id === selectedEditStageId);
                                    const ok = window.confirm(
                                      `Eliminare lo stage "${stageToDelete?.name ?? `#${selectedEditStageId}`}"? Operazione irreversibile.`
                                    );
                                    if (!ok) return;
                                    try {
                                      await deleteCompetitionStage(selectedEditStageId);
                                    } catch (e) {
                                      throw formatDeletionDependencyError(e);
                                    }
                                    setSelectedEditStageId(null);
                                    await loadCompetitionStages(selectedCompetition.competition_id);
                                    if (selectedLeagueId) await loadCompetitions(selectedLeagueId);
                                    setMsg('Stage eliminato');
                                  })
                                }
                              >
                                Elimina stage
                              </Button>
                            ) : null}
                          </div>
                        </div>
                      </Card>

                      <Card className="p-4 lg:col-span-2">
                        <SectionTitle>Pianificazione Matchday e Stato</SectionTitle>
                        <div className="mt-2 rounded-xl border p-2">
                          <div className="text-xs font-semibold text-slate-500">Durata e Associazione ai Matchday Reali</div>
                          <div className="mt-2 grid gap-2 sm:grid-cols-2">
                            <input type="date" className="rounded-xl border px-3 py-2 text-sm" value={compStartsAt} onChange={(e) => setCompStartsAt(e.target.value)} />
                            <input type="date" className="rounded-xl border px-3 py-2 text-sm" value={compEndsAt} onChange={(e) => setCompEndsAt(e.target.value)} />
                          </div>
                          <div className="mt-2 flex flex-wrap gap-2">
                            <Button size="sm" variant="secondary" onClick={() => void run(async () => {
                              if (!selectedCompetition) return;
                              await updateCompetition(selectedCompetition.competition_id, { starts_at: compStartsAt || null, ends_at: compEndsAt || null });
                              if (selectedLeagueId) await loadCompetitions(selectedLeagueId);
                              setMsg('Date competizione aggiornate');
                            })}>Salva date</Button>
                            <Button size="sm" variant="secondary" onClick={() => void run(async () => {
                              if (!selectedCompetition) return;
                              await reloadSchedulePreview(selectedCompetition.competition_id);
                              setMsg('Preview calendario aggiornata');
                            })}>Preview mapping</Button>
                            <Button size="sm" onClick={() => void run(async () => {
                              if (!selectedCompetition) return;
                              const mapping: Record<string, number> = {};
                              Object.entries(roundMappingDraft).forEach(([k, v]) => {
                                const parsed = Number(v);
                                if (Number.isFinite(parsed) && parsed > 0) mapping[k] = parsed;
                              });
                              await scheduleCompetition(selectedCompetition.competition_id, {
                                starts_at: compStartsAt || null,
                                ends_at: compEndsAt || null,
                                round_mapping: mapping,
                              });
                              if (selectedLeagueId) {
                                await loadCompetitions(selectedLeagueId);
                                await loadMatchdays(selectedLeagueId);
                              }
                              await reloadSchedulePreview(selectedCompetition.competition_id);
                              setMsg('Scheduling applicato');
                            })}>Applica mapping</Button>
                            <Button size="sm" variant="secondary" onClick={() => void run(async () => {
                              if (!selectedCompetition) return;
                              await updateCompetition(selectedCompetition.competition_id, { status: 'active' });
                              if (selectedLeagueId) await loadCompetitions(selectedLeagueId);
                            })}>Set active</Button>
                            <Button size="sm" variant="secondary" onClick={() => void run(async () => {
                              if (!selectedCompetition) return;
                              await updateCompetition(selectedCompetition.competition_id, { status: 'done' });
                              if (selectedLeagueId) await loadCompetitions(selectedLeagueId);
                            })}>Set done</Button>
                          </div>
                        </div>
                        {schedulePreview ? (
                          <div className="mt-3 rounded-xl border bg-slate-50 p-2">
                            <div className="text-xs text-slate-600">Matchday reali disponibili: {schedulePreview.available_real_matchdays.length ? schedulePreview.available_real_matchdays.join(', ') : 'nessuno nel range date'}</div>
                            <div className="mt-2 space-y-2">
                              {schedulePreview.rounds.map((rno) => {
                                const key = String(rno);
                                const current = schedulePreview.current_mapping[key];
                                const proposed = schedulePreview.proposed_mapping[key];
                                return (
                                  <div key={key} className="grid items-center gap-2 rounded-lg border bg-white px-2 py-2 text-xs sm:grid-cols-[120px_1fr_auto]">
                                    <div className="font-semibold">Round {rno}</div>
                                    <select className="rounded-lg border px-2 py-1" value={roundMappingDraft[key] ?? ''} onChange={(e) => setRoundMappingDraft((prev) => ({ ...prev, [key]: e.target.value }))}>
                                      <option value="">Non assegnato</option>
                                      {schedulePreview.available_real_matchdays.map((md) => (
                                        <option key={md} value={md}>Real MD {md}</option>
                                      ))}
                                    </select>
                                    <div className="text-slate-500">curr {current ?? '-'} · auto {proposed ?? '-'}</div>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        ) : null}
                      </Card>

                      <Card className="p-4 lg:col-span-2">
                        <SectionTitle>Stage Graph</SectionTitle>
                        <div className="mt-2 max-h-80 space-y-2 overflow-auto text-xs">
                          {competitionStages.length ? (
                            competitionStages
                              .sort((a, b) => (a.order_index - b.order_index) || (a.stage_id - b.stage_id))
                              .map((st) => (
                                <div key={st.stage_id} className="rounded-lg border px-2 py-2">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span className="font-semibold">#{st.order_index} {st.name}</span>
                                    <Badge tone={st.stage_type === 'knockout' ? 'amber' : 'slate'}>{st.stage_type}</Badge>
                                    <Badge tone={st.status === 'done' ? 'green' : st.status === 'active' ? 'amber' : 'slate'}>{st.status}</Badge>
                                  </div>
                                  <div className="mt-1">partecipanti {st.participants.length} · fixture {st.fixtures.finished}/{st.fixtures.total}</div>
                                  {st.rules_in.length ? <div className="mt-1 text-slate-600">da: {st.rules_in.map((r) => `${formatRuleModeLabel(r.mode, r.rank_from, r.rank_to)} · ${r.source_competition_name ? `${r.source_competition_name} / ` : ''}${r.source_stage_name}`).join(', ')}</div> : <div className="mt-1 text-slate-500">nessuna regola in ingresso</div>}
                                </div>
                              ))
                          ) : (
                            <div className="text-slate-500">Nessuno stage definito.</div>
                          )}
                        </div>
                      </Card>

                      <Card className="p-4 lg:col-span-2">
                        <SectionTitle>Premi e Condizioni</SectionTitle>
                        <div className="mt-2 text-xs text-slate-500">
                          Definisci premi con condizione di assegnazione: classifica finale, classifica stage o vincitore/perdente di uno stage.
                        </div>
                        <div className="mt-3 grid gap-2 lg:grid-cols-[1.2fr_1fr_1fr_1fr_auto]">
                          <input className="rounded-xl border px-3 py-2 text-sm" placeholder="Nome premio (es. Scudetto, Coppa Fair Play)" value={prizeName} onChange={(e) => setPrizeName(e.target.value)} />
                          <select className="rounded-xl border px-3 py-2 text-sm" value={prizeConditionType} onChange={(e) => setPrizeConditionType(e.target.value as 'final_table_range' | 'stage_table_range' | 'stage_winner' | 'stage_loser')}>
                            <option value="final_table_range">Classifica finale (range)</option>
                            <option value="stage_table_range">Classifica stage (range)</option>
                            <option value="stage_winner">Vincitore stage</option>
                            <option value="stage_loser">Perdente stage</option>
                          </select>
                          <select
                            className="rounded-xl border px-3 py-2 text-sm"
                            value={prizeStageId ?? ''}
                            onChange={(e) => setPrizeStageId(e.target.value ? Number(e.target.value) : null)}
                            disabled={prizeConditionType === 'final_table_range'}
                          >
                            <option value="">Stage (se richiesto)</option>
                            {competitionStages.map((s) => (
                              <option key={s.stage_id} value={s.stage_id}>#{s.order_index} {s.name}</option>
                            ))}
                          </select>
                          <div className="grid grid-cols-2 gap-2">
                            <input className="rounded-xl border px-3 py-2 text-sm" placeholder="from" value={prizeRankFrom} onChange={(e) => setPrizeRankFrom(e.target.value)} disabled={!(prizeConditionType === 'final_table_range' || prizeConditionType === 'stage_table_range')} />
                            <input className="rounded-xl border px-3 py-2 text-sm" placeholder="to" value={prizeRankTo} onChange={(e) => setPrizeRankTo(e.target.value)} disabled={!(prizeConditionType === 'final_table_range' || prizeConditionType === 'stage_table_range')} />
                          </div>
                          <Button
                            size="sm"
                            onClick={() =>
                              void run(async () => {
                                if (!selectedCompetition || !prizeName.trim()) return;
                                await createCompetitionPrize(selectedCompetition.competition_id, {
                                  name: prizeName.trim(),
                                  condition_type: prizeConditionType,
                                  source_stage_id:
                                    prizeConditionType === 'final_table_range' ? undefined : (prizeStageId ?? undefined),
                                  rank_from:
                                    prizeConditionType === 'final_table_range' || prizeConditionType === 'stage_table_range'
                                      ? Number(prizeRankFrom || 1)
                                      : undefined,
                                  rank_to:
                                    prizeConditionType === 'final_table_range' || prizeConditionType === 'stage_table_range'
                                      ? Number(prizeRankTo || prizeRankFrom || 1)
                                      : undefined,
                                });
                                if (selectedLeagueId) await loadCompetitions(selectedLeagueId);
                                setPrizeName('');
                                setMsg('Premio aggiunto');
                              })
                            }
                          >
                            Aggiungi premio
                          </Button>
                        </div>

                        <div className="mt-3 max-h-52 space-y-2 overflow-auto text-xs">
                          {selectedCompetition.prizes.length ? (
                            selectedCompetition.prizes.map((p) => (
                              <div key={p.prize_id} className="flex items-center justify-between rounded-lg border px-2 py-2">
                                <div>
                                  <div className="font-semibold">{p.name}</div>
                                  <div className="text-slate-600">
                                    {p.condition_type}
                                    {p.source_stage_name ? ` · ${p.source_stage_name}` : ''}
                                    {p.rank_from !== null ? ` · ${p.rank_from}-${p.rank_to ?? p.rank_from}` : ''}
                                  </div>
                                </div>
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  onClick={() =>
                                    void run(async () => {
                                      await deleteCompetitionPrize(p.prize_id);
                                      if (selectedLeagueId) await loadCompetitions(selectedLeagueId);
                                    })
                                  }
                                >
                                  Remove
                                </Button>
                              </div>
                            ))
                          ) : (
                            <div className="text-slate-500">Nessun premio configurato.</div>
                          )}
                        </div>
                      </Card>
                    </div>
                  ) : (
                    <Card className="p-4">
                      <div className="text-sm text-slate-500">Crea e seleziona una competizione per proseguire con stage, regole e calendario.</div>
                    </Card>
                  )}
                </div>
              ) : null}

              {leagueTab === 'matchdays' ? (
                <div className="grid gap-4 lg:grid-cols-2">
                  <Card className="p-4">
                    <SectionTitle>Conclusione Giornate</SectionTitle>
                    <div className="mt-2 text-xs text-slate-500">
                      Le giornate fantasy vengono allineate automaticamente dal backend in base ai match reali associati alle fixture.
                    </div>
                  </Card>

                  <Card className="p-4">
                    <SectionTitle>Giornate Fantasy</SectionTitle>
                    <div className="mt-2 max-h-[520px] space-y-2 overflow-auto text-sm">
                      {matchdays.length ? (
                        matchdays.map((md) => {
                          const disabledReason = concludeDisabledReason(md);
                          const canConclude = !disabledReason;
                          return (
                            <div key={md.fantasy_matchday_id} className="rounded-xl border p-3">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="font-semibold">
                                  {md.real_competition_season.competition} · Giornata {md.real_matchday}
                                </span>
                                <Badge tone={md.status === 'concluded' ? 'green' : 'slate'}>{md.status}</Badge>
                                <Badge tone={md.real_completion.is_completed ? 'green' : 'amber'}>
                                  reale {md.real_completion.completed}/{md.real_completion.total}
                                </Badge>
                              </div>
                              <div className="mt-1 text-xs text-slate-600">
                                Fixture fantasy: {md.fixtures.finished}/{md.fixtures.total}
                                {md.concluded_by ? ` · conclusa da ${md.concluded_by}` : ''}
                              </div>
                              {disabledReason ? <div className="mt-1 text-xs text-amber-700">{disabledReason}</div> : null}
                              <div className="mt-2">
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  aria-label={`Concludi giornata ${md.real_matchday}`}
                                  disabled={!canConclude || busy}
                                  onClick={() =>
                                    void run(async () => {
                                      if (!selectedLeagueId) return;
                                      await concludeLeagueMatchday(selectedLeagueId, md.fantasy_matchday_id, false);
                                      await loadMatchdays(selectedLeagueId);
                                      if (selectedLeagueId) await loadCompetitions(selectedLeagueId);
                                      setMsg(`Giornata ${md.real_matchday} conclusa`);
                                    })
                                  }
                                >
                                  Concludi giornata
                                </Button>
                              </div>
                            </div>
                          );
                        })
                      ) : (
                        <div className="text-slate-500">Nessuna giornata fantasy disponibile al momento.</div>
                      )}
                    </div>
                  </Card>
                </div>
              ) : null}

              {leagueTab === 'auction' ? (
                <div className="grid gap-4 lg:grid-cols-2">
                  <Card className="p-4">
                    <SectionTitle>Auction Room (beta)</SectionTitle>
                    <div className="mt-2 text-xs text-slate-500">Questa sezione mostra stato asta: prossimo giocatore, giocatori chiamati e budget disponibili per team.</div>

                    <textarea
                      id="auction-player-ids"
                      className="mt-3 h-20 w-full rounded-xl border px-3 py-2 text-xs"
                      placeholder="Player IDs per creare l'asta (es. 101,102,103...)"
                      value={auctionPlayerIds}
                      onChange={(e) => setAuctionPlayerIds(e.target.value)}
                    />
                    <label htmlFor="auction-player-ids" className="sr-only">Player IDs per creare l'asta</label>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Button
                        size="sm"
                        onClick={() =>
                          void run(async () => {
                            if (!selectedLeagueId) return;
                            const ids = parseIds(auctionPlayerIds);
                            const res = await createAuction(selectedLeagueId, ids, 42);
                            setAuctionId(res.auction_id);
                            await loadAuctionState(res.auction_id);
                            setMsg(`Asta creata: ${res.auction_id}`);
                          })
                        }
                      >
                        Crea asta
                      </Button>
                      <input
                        id="auction-id-input"
                        className="w-28 rounded-xl border px-3 py-2 text-sm"
                        placeholder="auction id"
                        value={auctionId ?? ''}
                        onChange={(e) => setAuctionId(e.target.value ? Number(e.target.value) : null)}
                      />
                      <label htmlFor="auction-id-input" className="sr-only">Auction ID</label>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          void run(async () => {
                            if (!auctionId) return;
                            await loadAuctionState(auctionId);
                          })
                        }
                      >
                        Carica stato
                      </Button>
                    </div>

                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          void run(async () => {
                            if (!auctionId) return;
                            const res = await nominateNext(auctionId);
                            setNominationId(res.nomination_id);
                            await loadAuctionState(auctionId);
                            setMsg(`Nomination ${res.nomination_id}: ${res.player_name}`);
                          })
                        }
                      >
                        Nominate next
                      </Button>
                      <label htmlFor="auction-bid-amount" className="sr-only">Importo offerta</label>
                      <input id="auction-bid-amount" className="w-24 rounded-xl border px-3 py-2 text-sm" value={bidAmount} onChange={(e) => setBidAmount(e.target.value)} />
                      <Button
                        size="sm"
                        onClick={() =>
                          void run(async () => {
                            if (!nominationId) return;
                            await placeBid(nominationId, Number(bidAmount));
                            if (auctionId) await loadAuctionState(auctionId);
                            setMsg('Bid inserita');
                          })
                        }
                      >
                        Bid
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          void run(async () => {
                            if (!nominationId) return;
                            const res = await closeNomination(nominationId);
                            if (auctionId) await loadAuctionState(auctionId);
                            setMsg(`Nomination chiusa. Winner team: ${res.winner_team_id ?? '-'}`);
                          })
                        }
                      >
                        Close nomination
                      </Button>
                    </div>
                  </Card>

                  <Card className="p-4">
                    <SectionTitle>Stato Asta</SectionTitle>
                    {auctionState ? (
                      <div className="space-y-3 text-sm">
                        <div className="rounded-xl border p-2">
                          <div><span className="font-semibold">Asta:</span> {auctionState.name} (#{auctionState.auction_id})</div>
                          <div><span className="font-semibold">Progress:</span> {auctionState.nomination_index}/{auctionState.nomination_total}</div>
                          <div><span className="font-semibold">Prossimo giocatore:</span> {auctionState.next_player?.name ?? '-'}</div>
                          <div><span className="font-semibold">Giocatore in chiamata:</span> {auctionState.open_nomination?.player_name ?? '-'}</div>
                        </div>

                        <div>
                          <div className="text-xs font-semibold text-slate-500">Budget per team</div>
                          <div className="mt-1 max-h-40 overflow-auto space-y-1 text-xs">
                            {auctionState.team_budgets.map((b) => (
                              <div key={b.team_id} className="rounded-lg border px-2 py-1">
                                {b.team_name} ({b.manager_username}) · Disponibile {b.available_budget} / {b.initial_budget}
                              </div>
                            ))}
                          </div>
                        </div>

                        <div>
                          <div className="text-xs font-semibold text-slate-500">Giocatori già chiamati</div>
                          <div className="mt-1 max-h-48 overflow-auto space-y-1 text-xs">
                            {auctionState.recent_nominations.map((n) => (
                              <div key={n.nomination_id} className="rounded-lg border px-2 py-1">
                                {n.player_name} · top bid {n.top_bid} · winner {n.winner_team_name ?? '-'}
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="text-sm text-slate-500">Carica uno stato asta inserendo auction id oppure crea una nuova asta.</div>
                    )}
                  </Card>
                </div>
              ) : null}
            </>
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              <Card className="p-4">
                <SectionTitle>Funzioni League Admin</SectionTitle>
                <ul className="mt-3 space-y-2 text-sm text-slate-700">
                  <li>• Apri/chiudi mercato</li>
                  <li>• Modifica roster con ricerca giocatori per nome</li>
                  <li>• Crea competizioni (round robin/knockout)</li>
                  <li>• Gestione asta (prossimo chiamato, chiamati, budget)</li>
                </ul>
              </Card>
              <Card className="p-4">
                <SectionTitle>Come Procedere</SectionTitle>
                <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm text-slate-700">
                  <li>Passa al tab User Admin per creare/joinare una lega.</li>
                  <li>Seleziona la lega nel menu in alto.</li>
                  <li>Torna su League Admin per i controlli avanzati.</li>
                </ol>
              </Card>
            </div>
          )}
        </>
      )}
    </div>
  );
}
