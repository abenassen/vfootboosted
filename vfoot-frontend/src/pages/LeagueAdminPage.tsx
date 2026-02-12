import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  addRosterPlayer,
  bulkAssignRoster,
  closeNomination,
  createAuction,
  addCompetitionRule,
  createCompetitionTemplate,
  createLeague,
  getAuctionState,
  getCompetitions,
  getLeagueDetail,
  getTeamRoster,
  importRosterCsv,
  joinLeague,
  nominateNext,
  placeBid,
  removeRosterPlayer,
  resolveCompetitionDependencies,
  searchPlayers,
  setMarketStatus,
  updateCompetition,
  updateMemberRole,
} from '../api';
import { useAuth } from '../auth/AuthContext';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type { AuctionState, CompetitionItem, LeagueDetail, PlayerSearchItem, TeamRoster } from '../types/league';

type AdminTab = 'user' | 'league';
type LeagueTab = 'overview' | 'roster' | 'competitions' | 'auction';

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

  const [compName, setCompName] = useState('Campionato');
  const [compType, setCompType] = useState<'round_robin' | 'knockout'>('round_robin');
  const [compTeamIds, setCompTeamIds] = useState<number[]>([]);
  const [competitions, setCompetitions] = useState<CompetitionItem[]>([]);
  const [selectedCompetitionId, setSelectedCompetitionId] = useState<number | null>(null);
  const [ruleSourceCompetitionId, setRuleSourceCompetitionId] = useState<number | null>(null);
  const [ruleSourceStage, setRuleSourceStage] = useState<'halfway' | 'final'>('final');
  const [ruleMode, setRuleMode] = useState<'table_range' | 'winner' | 'loser'>('winner');
  const [ruleRankFrom, setRuleRankFrom] = useState('');
  const [ruleRankTo, setRuleRankTo] = useState('');

  const [auctionPlayerIds, setAuctionPlayerIds] = useState('');
  const [auctionId, setAuctionId] = useState<number | null>(null);
  const [auctionState, setAuctionState] = useState<AuctionState | null>(null);
  const [nominationId, setNominationId] = useState<number | null>(null);
  const [bidAmount, setBidAmount] = useState('1');

  const [msg, setMsg] = useState<string>('');
  const [busy, setBusy] = useState(false);

  const selectedTeamName = useMemo(
    () => league?.teams.find((t) => t.team_id === selectedTeamId)?.name ?? '',
    [league, selectedTeamId]
  );
  const selectedCompetition = useMemo(
    () => competitions.find((c) => c.competition_id === selectedCompetitionId) ?? null,
    [competitions, selectedCompetitionId]
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
  }

  async function loadAuctionState(currentAuctionId: number) {
    const s = await getAuctionState(currentAuctionId);
    setAuctionState(s);
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
      return;
    }
    void loadLeagueDetail(selectedLeagueId).catch((e) => setMsg(`Errore dettaglio lega: ${e.message}`));
    void loadCompetitions(selectedLeagueId).catch((e) => setMsg(`Errore competizioni: ${e.message}`));
  }, [selectedLeagueId]);

  useEffect(() => {
    if (!league?.teams.length) return;
    setCompTeamIds(league.teams.map((t) => t.team_id));
  }, [league?.teams]);

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

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setMsg('');
    try {
      await action();
    } catch (e) {
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

        {msg ? <div className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-700">{msg}</div> : null}
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
                      <label className="mb-1 block text-xs font-semibold text-slate-500">Fantasy Team</label>
                      <select className="w-full rounded-xl border px-3 py-2 text-sm" value={selectedTeamId ?? ''} onChange={(e) => setSelectedTeamId(Number(e.target.value))}>
                        {league.teams.map((t) => (
                          <option key={t.team_id} value={t.team_id}>{t.name}</option>
                        ))}
                      </select>
                    </div>

                    <div className="mt-3 rounded-xl border p-3">
                      <div className="text-xs font-semibold text-slate-500">Aggiungi giocatore per nome</div>
                      <input
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
                        <input className="rounded-xl border px-3 py-2 text-sm" placeholder="Prezzo" value={manualPrice} onChange={(e) => setManualPrice(e.target.value)} />
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
                      <textarea
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
                      <input
                        type="file"
                        accept=".csv,text/csv"
                        className="mt-2 block w-full rounded-xl border px-3 py-2 text-xs"
                        onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
                      />
                      <textarea
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
                <div className="grid gap-4 lg:grid-cols-2">
                  <Card className="p-4">
                    <SectionTitle>Crea Competizione</SectionTitle>
                    <div className="mt-2 text-xs text-slate-500">
                      Parita con legacy: puoi creare competizioni con partecipanti manuali (team della lega) e poi aggiungere regole di qualificazione da altre competizioni.
                    </div>
                    <div className="mt-3 space-y-2">
                      <input className="w-full rounded-xl border px-3 py-2 text-sm" value={compName} onChange={(e) => setCompName(e.target.value)} placeholder="Nome competizione" />
                      <select className="w-full rounded-xl border px-3 py-2 text-sm" value={compType} onChange={(e) => setCompType(e.target.value as 'round_robin' | 'knockout')}>
                        <option value="round_robin">Round robin</option>
                        <option value="knockout">Knockout</option>
                      </select>

                      <div className="rounded-xl border p-2">
                        <div className="text-xs font-semibold text-slate-500">Partecipanti manuali (team lega)</div>
                        <div className="mt-2 space-y-1 text-sm">
                          {league.teams.map((t) => (
                            <label key={t.team_id} className="flex items-center gap-2">
                              <input
                                type="checkbox"
                                checked={compTeamIds.includes(t.team_id)}
                                onChange={(e) =>
                                  setCompTeamIds((prev) =>
                                    e.target.checked ? [...prev, t.team_id] : prev.filter((id) => id !== t.team_id)
                                  )
                                }
                              />
                              <span>{t.name}</span>
                              <span className="text-xs text-slate-500">({t.manager_username})</span>
                            </label>
                          ))}
                        </div>
                      </div>

                      <Button
                        size="sm"
                        onClick={() =>
                          void run(async () => {
                            if (!selectedLeagueId) return;
                            await createCompetitionTemplate(selectedLeagueId, { name: compName, competition_type: compType, team_ids: compTeamIds });
                            await loadCompetitions(selectedLeagueId);
                            setMsg('Competizione creata');
                          })
                        }
                      >
                        Crea competizione
                      </Button>
                    </div>
                  </Card>

                  <Card className="p-4">
                    <SectionTitle>Competizioni Create</SectionTitle>
                    <div className="mt-2 text-xs text-slate-500">Qui compaiono tutte le competizioni della lega con stato, fixture e regole qualificazione.</div>

                    <div className="mt-3">
                      <select
                        className="w-full rounded-xl border px-3 py-2 text-sm"
                        value={selectedCompetitionId ?? ''}
                        onChange={(e) => setSelectedCompetitionId(e.target.value ? Number(e.target.value) : null)}
                      >
                        <option value="">Seleziona competizione</option>
                        {competitions.map((c) => (
                          <option key={c.competition_id} value={c.competition_id}>
                            {c.name} ({c.competition_type})
                          </option>
                        ))}
                      </select>
                    </div>

                    {selectedCompetition ? (
                      <div className="mt-3 space-y-3 text-sm">
                        <div className="rounded-xl border p-2">
                          <div><span className="font-semibold">Stato:</span> {selectedCompetition.status}</div>
                          <div><span className="font-semibold">Fixture:</span> {selectedCompetition.fixtures.finished}/{selectedCompetition.fixtures.total}</div>
                          <div><span className="font-semibold">Partecipanti:</span> {selectedCompetition.participants.length}</div>
                        </div>

                        <div className="flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() =>
                              void run(async () => {
                                if (!selectedCompetition) return;
                                await updateCompetition(selectedCompetition.competition_id, { status: 'active' });
                                if (selectedLeagueId) await loadCompetitions(selectedLeagueId);
                              })
                            }
                          >
                            Set active
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() =>
                              void run(async () => {
                                if (!selectedCompetition) return;
                                await updateCompetition(selectedCompetition.competition_id, { status: 'done' });
                                if (selectedLeagueId) await loadCompetitions(selectedLeagueId);
                              })
                            }
                          >
                            Set done
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() =>
                              void run(async () => {
                                if (!selectedCompetition) return;
                                await resolveCompetitionDependencies(selectedCompetition.competition_id);
                                if (selectedLeagueId) await loadCompetitions(selectedLeagueId);
                                setMsg('Dipendenze e calendario aggiornati');
                              })
                            }
                          >
                            Aggiorna dipendenze/calendario
                          </Button>
                        </div>

                        <div className="rounded-xl border p-2">
                          <div className="text-xs font-semibold text-slate-500">Aggiungi regola qualificazione (legacy-style)</div>
                          <div className="mt-2 space-y-2">
                            <select
                              className="w-full rounded-xl border px-3 py-2 text-sm"
                              value={ruleSourceCompetitionId ?? ''}
                              onChange={(e) => setRuleSourceCompetitionId(e.target.value ? Number(e.target.value) : null)}
                            >
                              <option value="">Sorgente competizione</option>
                              {competitions
                                .filter((c) => c.competition_id !== selectedCompetition.competition_id)
                                .map((c) => (
                                  <option key={c.competition_id} value={c.competition_id}>
                                    {c.name}
                                  </option>
                                ))}
                            </select>
                            <select className="w-full rounded-xl border px-3 py-2 text-sm" value={ruleSourceStage} onChange={(e) => setRuleSourceStage(e.target.value as 'halfway' | 'final')}>
                              <option value="halfway">Classifica metà stagione</option>
                              <option value="final">Classifica finale</option>
                            </select>
                            <select className="w-full rounded-xl border px-3 py-2 text-sm" value={ruleMode} onChange={(e) => setRuleMode(e.target.value as 'table_range' | 'winner' | 'loser')}>
                              <option value="winner">Winner competizione sorgente</option>
                              <option value="loser">Loser competizione sorgente</option>
                              <option value="table_range">Range classifica</option>
                            </select>
                            {ruleMode === 'table_range' ? (
                              <div className="grid gap-2 sm:grid-cols-2">
                                <input className="rounded-xl border px-3 py-2 text-sm" placeholder="rank_from" value={ruleRankFrom} onChange={(e) => setRuleRankFrom(e.target.value)} />
                                <input className="rounded-xl border px-3 py-2 text-sm" placeholder="rank_to" value={ruleRankTo} onChange={(e) => setRuleRankTo(e.target.value)} />
                              </div>
                            ) : null}
                            <Button
                              size="sm"
                              onClick={() =>
                                void run(async () => {
                                  if (!selectedCompetition || !ruleSourceCompetitionId) return;
                                  await addCompetitionRule(selectedCompetition.competition_id, {
                                    source_competition_id: ruleSourceCompetitionId,
                                    source_stage: ruleSourceStage,
                                    mode: ruleMode,
                                    rank_from: ruleMode === 'table_range' ? Number(ruleRankFrom || 1) : undefined,
                                    rank_to: ruleMode === 'table_range' ? Number(ruleRankTo || 1) : undefined,
                                  });
                                  if (selectedLeagueId) await loadCompetitions(selectedLeagueId);
                                  setMsg('Regola qualificazione aggiunta');
                                })
                              }
                            >
                              Aggiungi regola
                            </Button>
                          </div>
                        </div>

                        <div className="rounded-xl border p-2">
                          <div className="text-xs font-semibold text-slate-500">Regole correnti</div>
                          <div className="mt-1 max-h-32 overflow-auto space-y-1 text-xs">
                            {selectedCompetition.qualification_rules.length ? (
                              selectedCompetition.qualification_rules.map((r) => (
                                <div key={r.rule_id} className="rounded-lg border px-2 py-1">
                                  {r.mode} from {r.source_competition_name} ({r.source_stage})
                                  {r.mode === 'table_range' ? ` [${r.rank_from}-${r.rank_to}]` : ''}
                                </div>
                              ))
                            ) : (
                              <div className="text-slate-500">Nessuna regola qualificazione.</div>
                            )}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="mt-3 text-sm text-slate-500">Crea o seleziona una competizione per visualizzare stato e modificarla.</div>
                    )}
                  </Card>
                </div>
              ) : null}

              {leagueTab === 'auction' ? (
                <div className="grid gap-4 lg:grid-cols-2">
                  <Card className="p-4">
                    <SectionTitle>Auction Room (beta)</SectionTitle>
                    <div className="mt-2 text-xs text-slate-500">Questa sezione mostra stato asta: prossimo giocatore, giocatori chiamati e budget disponibili per team.</div>

                    <textarea
                      className="mt-3 h-20 w-full rounded-xl border px-3 py-2 text-xs"
                      placeholder="Player IDs per creare l'asta (es. 101,102,103...)"
                      value={auctionPlayerIds}
                      onChange={(e) => setAuctionPlayerIds(e.target.value)}
                    />
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
                        className="w-28 rounded-xl border px-3 py-2 text-sm"
                        placeholder="auction id"
                        value={auctionId ?? ''}
                        onChange={(e) => setAuctionId(e.target.value ? Number(e.target.value) : null)}
                      />
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
                      <input className="w-24 rounded-xl border px-3 py-2 text-sm" value={bidAmount} onChange={(e) => setBidAmount(e.target.value)} />
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
