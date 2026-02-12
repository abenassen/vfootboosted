import { FormEvent, useEffect, useMemo, useState } from 'react';
import {
  addRosterPlayer,
  bulkAssignRoster,
  closeNomination,
  createAuction,
  createCompetitionTemplate,
  createLeague,
  getLeagueDetail,
  getLeagues,
  getTeamRoster,
  importRosterCsv,
  joinLeague,
  nominateNext,
  placeBid,
  removeRosterPlayer,
  setMarketStatus,
  updateMemberRole,
} from '../api';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type { LeagueDetail, LeagueSummary, TeamRoster } from '../types/league';

export default function LeagueAdminPage() {
  const [leagues, setLeagues] = useState<LeagueSummary[]>([]);
  const [selectedLeagueId, setSelectedLeagueId] = useState<number | null>(null);
  const [league, setLeague] = useState<LeagueDetail | null>(null);
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);
  const [roster, setRoster] = useState<TeamRoster | null>(null);

  const [createName, setCreateName] = useState('');
  const [createTeam, setCreateTeam] = useState('');
  const [joinCode, setJoinCode] = useState('');
  const [joinTeam, setJoinTeam] = useState('');

  const [manualPlayerId, setManualPlayerId] = useState('');
  const [manualPrice, setManualPrice] = useState('1');
  const [bulkPlayerIds, setBulkPlayerIds] = useState('');
  const [csvText, setCsvText] = useState('team_name,player_id,price\n');

  const [compName, setCompName] = useState('Campionato');
  const [compType, setCompType] = useState<'round_robin' | 'knockout'>('round_robin');

  const [auctionPlayerIds, setAuctionPlayerIds] = useState('');
  const [auctionId, setAuctionId] = useState<number | null>(null);
  const [nominationId, setNominationId] = useState<number | null>(null);
  const [bidAmount, setBidAmount] = useState('1');

  const [msg, setMsg] = useState<string>('');
  const [busy, setBusy] = useState(false);

  const selectedLeague = useMemo(() => leagues.find((l) => l.league_id === selectedLeagueId) ?? null, [leagues, selectedLeagueId]);

  async function loadLeagues() {
    const data = await getLeagues();
    setLeagues(data);
    if (!selectedLeagueId && data.length) {
      setSelectedLeagueId(data[0].league_id);
    }
  }

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

  useEffect(() => {
    void loadLeagues().catch((e) => setMsg(`Errore caricamento leghe: ${e.message}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedLeagueId) return;
    void loadLeagueDetail(selectedLeagueId).catch((e) => setMsg(`Errore dettaglio lega: ${e.message}`));
  }, [selectedLeagueId]);

  useEffect(() => {
    if (!selectedLeagueId || !selectedTeamId) return;
    void loadRoster(selectedLeagueId, selectedTeamId).catch((e) => setMsg(`Errore roster: ${e.message}`));
  }, [selectedLeagueId, selectedTeamId]);

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

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <SectionTitle>League Admin</SectionTitle>
        <div className="mt-2 text-sm text-slate-600">Gestione lega, mercato, roster, competizioni e asta (beta).</div>
        {msg ? <div className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-700">{msg}</div> : null}
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
                await loadLeagues();
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
                await loadLeagues();
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
              <Button size="sm" onClick={() => void run(async () => { if (!league) return; await setMarketStatus(league.league_id, !league.market_open); await loadLeagueDetail(league.league_id); })}>
                {league.market_open ? 'Chiudi mercato' : 'Apri mercato'}
              </Button>
            </div>
            <div>
              <div className="font-semibold">Membri</div>
              <div className="mt-2 space-y-1">
                {league.members.map((m) => (
                  <div key={m.membership_id} className="flex items-center justify-between rounded-xl border px-3 py-2">
                    <span>{m.username}</span>
                    <div className="flex items-center gap-2">
                      <Badge tone={m.role === 'admin' ? 'green' : 'slate'}>{m.role}</Badge>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          void run(async () => {
                            if (!league) return;
                            await updateMemberRole(league.league_id, m.membership_id, m.role === 'admin' ? 'manager' : 'admin');
                            await loadLeagueDetail(league.league_id);
                          })
                        }
                      >
                        Toggle
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </Card>

      {league ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-4">
            <SectionTitle>Roster Tools</SectionTitle>
            <div className="mt-2">
              <select className="w-full rounded-xl border px-3 py-2 text-sm" value={selectedTeamId ?? ''} onChange={(e) => setSelectedTeamId(Number(e.target.value))}>
                {league.teams.map((t) => (
                  <option key={t.team_id} value={t.team_id}>{t.name}</option>
                ))}
              </select>
            </div>

            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              <input className="rounded-xl border px-3 py-2 text-sm" placeholder="player_id" value={manualPlayerId} onChange={(e) => setManualPlayerId(e.target.value)} />
              <input className="rounded-xl border px-3 py-2 text-sm" placeholder="price" value={manualPrice} onChange={(e) => setManualPrice(e.target.value)} />
              <div className="flex gap-2">
                <Button
                  size="sm"
                  onClick={() =>
                    void run(async () => {
                      if (!selectedLeagueId || !selectedTeamId) return;
                      await addRosterPlayer(selectedLeagueId, selectedTeamId, Number(manualPlayerId), Number(manualPrice));
                      await loadRoster(selectedLeagueId, selectedTeamId);
                    })
                  }
                >
                  Add
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    void run(async () => {
                      if (!selectedLeagueId || !selectedTeamId) return;
                      await removeRosterPlayer(selectedLeagueId, selectedTeamId, Number(manualPlayerId));
                      await loadRoster(selectedLeagueId, selectedTeamId);
                    })
                  }
                >
                  Remove
                </Button>
              </div>
            </div>

            <textarea
              className="mt-3 h-24 w-full rounded-xl border px-3 py-2 text-xs"
              placeholder="Bulk player IDs (e.g. 1,2,3,4...)"
              value={bulkPlayerIds}
              onChange={(e) => setBulkPlayerIds(e.target.value)}
            />
            <div className="mt-2 flex gap-2">
              <Button
                size="sm"
                onClick={() =>
                  void run(async () => {
                    if (!selectedLeagueId) return;
                    const ids = parseIds(bulkPlayerIds);
                    await bulkAssignRoster(selectedLeagueId, ids, 5, 42);
                    if (selectedTeamId) await loadRoster(selectedLeagueId, selectedTeamId);
                  })
                }
              >
                Bulk assign
              </Button>
            </div>

            <textarea
              className="mt-3 h-28 w-full rounded-xl border px-3 py-2 text-xs"
              value={csvText}
              onChange={(e) => setCsvText(e.target.value)}
            />
            <Button
              size="sm"
              className="mt-2"
              onClick={() =>
                void run(async () => {
                  if (!selectedLeagueId) return;
                  await importRosterCsv(selectedLeagueId, csvText);
                  if (selectedTeamId) await loadRoster(selectedLeagueId, selectedTeamId);
                })
              }
            >
              Import CSV
            </Button>

            <div className="mt-3">
              <div className="text-xs font-semibold text-slate-500">Roster corrente</div>
              <div className="mt-2 max-h-56 overflow-auto space-y-1 text-xs">
                {roster?.players.map((p) => (
                  <div key={p.player_id} className="rounded-lg border px-2 py-1">#{p.player_id} {p.name} (€{p.price})</div>
                ))}
              </div>
            </div>
          </Card>

          <Card className="p-4">
            <SectionTitle>Competizioni e Asta</SectionTitle>
            <div className="mt-3 space-y-2">
              <input className="w-full rounded-xl border px-3 py-2 text-sm" value={compName} onChange={(e) => setCompName(e.target.value)} placeholder="Nome competizione" />
              <select className="w-full rounded-xl border px-3 py-2 text-sm" value={compType} onChange={(e) => setCompType(e.target.value as 'round_robin' | 'knockout')}>
                <option value="round_robin">Round robin</option>
                <option value="knockout">Knockout</option>
              </select>
              <Button
                size="sm"
                onClick={() =>
                  void run(async () => {
                    if (!selectedLeagueId) return;
                    const teamIds = league.teams.map((t) => t.team_id);
                    await createCompetitionTemplate(selectedLeagueId, { name: compName, competition_type: compType, team_ids: teamIds });
                    setMsg('Competizione creata');
                  })
                }
              >
                Crea competizione
              </Button>
            </div>

            <div className="mt-5 space-y-2">
              <textarea
                className="h-24 w-full rounded-xl border px-3 py-2 text-xs"
                placeholder="Player IDs per asta (e.g. 1,2,3,4...)"
                value={auctionPlayerIds}
                onChange={(e) => setAuctionPlayerIds(e.target.value)}
              />
              <Button
                size="sm"
                onClick={() =>
                  void run(async () => {
                    if (!selectedLeagueId) return;
                    const ids = parseIds(auctionPlayerIds);
                    const res = await createAuction(selectedLeagueId, ids, 42);
                    setAuctionId(res.auction_id);
                    setMsg(`Asta creata: ${res.auction_id}`);
                  })
                }
              >
                Crea asta
              </Button>

              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    void run(async () => {
                      if (!auctionId) return;
                      const res = await nominateNext(auctionId);
                      setNominationId(res.nomination_id);
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
                      setMsg(`Nomination chiusa. Winner team: ${res.winner_team_id ?? '-'}`);
                    })
                  }
                >
                  Close nomination
                </Button>
              </div>
            </div>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
