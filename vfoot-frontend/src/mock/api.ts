import type { LineupContextResponse, MatchDetailResponse, MatchListItem, SaveLineupRequest, SaveLineupResponse } from '../types/contracts';
import type { AuthResponse, AuthUser, LoginRequest, RegisterRequest } from '../types/auth';
import type {
  AuctionState,
  CompetitionItem,
  CompetitionUpdateRequest,
  CompetitionTemplateRequest,
  CreateLeagueRequest,
  JoinLeagueRequest,
  LeagueDetail,
  LeagueFixtureItem,
  LeagueSummary,
  PlayerSearchItem,
  QualificationRuleCreateRequest,
  TeamRoster,
} from '../types/league';
import { mockLineupContext, mockMatches, mockMatchDetail } from './data';
import { computeCoveragePreview } from '../utils/coverage';

let inMemoryLineup = structuredClone(mockLineupContext.saved_lineup);
const MOCK_USERS_KEY = 'vfoot_mock_users';
const MOCK_SESSION_KEY = 'vfoot_mock_session';

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readUsers(): Array<{ username: string; email: string; password: string }> {
  if (typeof window === 'undefined') return [];
  const raw = window.localStorage.getItem(MOCK_USERS_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as Array<{ username: string; email: string; password: string }>;
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeUsers(users: Array<{ username: string; email: string; password: string }>) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(MOCK_USERS_KEY, JSON.stringify(users));
}

function toAuthUser(username: string, email: string): AuthUser {
  return { id: Math.abs(hash(username)) + 1, username, email };
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return h;
}

function setSession(user: AuthUser) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(MOCK_SESSION_KEY, JSON.stringify(user));
}

function clearSession() {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(MOCK_SESSION_KEY);
}

export function hasStoredSession(): boolean {
  if (typeof window === 'undefined') return false;
  return !!window.localStorage.getItem(MOCK_SESSION_KEY);
}

export async function register(req: RegisterRequest): Promise<AuthResponse> {
  await sleep(250);
  const users = readUsers();
  if (users.some((u) => u.username === req.username)) {
    throw new Error('Username already exists.');
  }
  users.push({ username: req.username, email: req.email ?? '', password: req.password });
  writeUsers(users);
  const user = toAuthUser(req.username, req.email ?? '');
  setSession(user);
  return { token: `mock-token-${req.username}`, user };
}

export async function login(req: LoginRequest): Promise<AuthResponse> {
  await sleep(200);
  const users = readUsers();
  const found = users.find((u) => u.username === req.username && u.password === req.password);
  if (!found) throw new Error('Invalid credentials.');
  const user = toAuthUser(found.username, found.email);
  setSession(user);
  return { token: `mock-token-${found.username}`, user };
}

export async function getCurrentUser(): Promise<AuthUser> {
  await sleep(100);
  if (typeof window === 'undefined') throw new Error('No active session.');
  const raw = window.localStorage.getItem(MOCK_SESSION_KEY);
  if (!raw) throw new Error('No active session.');
  return JSON.parse(raw) as AuthUser;
}

export async function logout(): Promise<void> {
  await sleep(100);
  clearSession();
}

export async function getLineupContext(): Promise<LineupContextResponse> {
  await sleep(250);
  const base = structuredClone(mockLineupContext);
  base.saved_lineup = structuredClone(inMemoryLineup);
  // recompute preview based on current lineup
  base.coverage_preview = computeCoveragePreview(base.zone_grid, base.roster, base.saved_lineup, base.rules.gk_separate_slot);
  return base;
}

export async function saveLineup(req: SaveLineupRequest): Promise<SaveLineupResponse> {
  await sleep(300);
  inMemoryLineup = {
    lineup_id: 'LU-' + Math.floor(Math.random() * 10000),
    gk_player_id: req.gk_player_id ?? null,
    starter_player_ids: req.starter_player_ids,
    bench_player_ids: req.bench_player_ids,
    starter_backups: req.starter_backups,
    ui_hints: { last_saved_at: new Date().toISOString() }
  };

  const roster = mockLineupContext.roster;
  const preview = computeCoveragePreview(mockLineupContext.zone_grid, roster, inMemoryLineup, mockLineupContext.rules.gk_separate_slot);

  const warnings: SaveLineupResponse['warnings'] = [];
  for (const pid of req.starter_player_ids) {
    const p = roster.find((x) => x.player_id === pid);
    if (p && p.status.minutes_expectation.label === 'low') {
      warnings.push({ code: 'LOW_MINUTES_RISK', player_id: pid, message: `${p.name}: rischio minutaggio` });
    }
  }

  return {
    lineup_id: inMemoryLineup.lineup_id,
    saved_at: new Date().toISOString(),
    coverage_preview: preview,
    warnings: warnings.length ? warnings : undefined
  };
}

export async function getMatches(): Promise<MatchListItem[]> {
  await sleep(200);
  return structuredClone(mockMatches);
}

export async function getMatchDetail(matchId: string): Promise<MatchDetailResponse> {
  await sleep(280);
  // Single mock; in futuro: usare matchId
  return structuredClone({ ...mockMatchDetail, match: { ...mockMatchDetail.match, match_id: matchId } });
}

export async function getLeagueFixtures(_leagueId: number, _competitionId?: number): Promise<LeagueFixtureItem[]> {
  await sleep(120);
  return [
    {
      fixture_id: 1,
      competition_id: 1,
      competition_name: 'Campionato Mock',
      round_no: 1,
      leg_no: 1,
      kickoff: null,
      status: 'scheduled',
      home_team: { team_id: 11, name: 'Mock Team' },
      away_team: { team_id: 12, name: 'Mock Team 2' },
      score: null,
      is_user_involved: true,
    },
    {
      fixture_id: 2,
      competition_id: 1,
      competition_name: 'Campionato Mock',
      round_no: 2,
      leg_no: 1,
      kickoff: null,
      status: 'finished',
      home_team: { team_id: 12, name: 'Mock Team 2' },
      away_team: { team_id: 11, name: 'Mock Team' },
      score: { home_total: 67.5, away_total: 69.2 },
      is_user_involved: true,
    },
  ];
}

// Admin/league mock endpoints (minimal local in-memory compatibility)
const mockLeagues: LeagueDetail[] = [];
let mockLeagueSeq = 1;

export async function getLeagues(): Promise<LeagueSummary[]> {
  await sleep(120);
  return mockLeagues.map((l) => ({
    league_id: l.league_id,
    name: l.name,
    role: 'admin',
    invite_code: l.invite_code,
    market_open: l.market_open
  }));
}

export async function createLeague(req: CreateLeagueRequest) {
  await sleep(150);
  const id = mockLeagueSeq++;
  const league: LeagueDetail = {
    league_id: id,
    name: req.name,
    market_open: true,
    invite_code: `MOCK${id}`,
    invite_link: `/join/MOCK${id}`,
    members: [{ membership_id: id * 10 + 1, user_id: 1, username: 'mock-admin', role: 'admin' }],
    teams: [{ team_id: id * 10 + 1, name: req.team_name, manager_user_id: 1, manager_username: 'mock-admin' }]
  };
  mockLeagues.push(league);
  return { league_id: id, invite_code: league.invite_code };
}

export async function joinLeague(req: JoinLeagueRequest) {
  await sleep(120);
  const l = mockLeagues.find((x) => x.invite_code === req.invite_code);
  if (!l) throw new Error('League not found.');
  const teamId = l.teams.length + l.league_id * 10 + 1;
  l.teams.push({ team_id: teamId, name: req.team_name, manager_user_id: 2, manager_username: 'mock-user' });
  l.members.push({ membership_id: teamId, user_id: 2, username: 'mock-user', role: 'manager' });
  return { league_id: l.league_id, team_id: teamId };
}

export async function getLeagueDetail(leagueId: number): Promise<LeagueDetail> {
  await sleep(100);
  const l = mockLeagues.find((x) => x.league_id === leagueId);
  if (!l) throw new Error('League not found.');
  return structuredClone(l);
}

export async function updateMemberRole(leagueId: number, membershipId: number, role: 'admin' | 'manager') {
  await sleep(80);
  const l = mockLeagues.find((x) => x.league_id === leagueId);
  if (!l) throw new Error('League not found.');
  const m = l.members.find((x) => x.membership_id === membershipId);
  if (!m) throw new Error('Member not found.');
  m.role = role;
  return { membership_id: m.membership_id, role: m.role };
}

export async function setMarketStatus(leagueId: number, isOpen: boolean) {
  await sleep(80);
  const l = mockLeagues.find((x) => x.league_id === leagueId);
  if (!l) throw new Error('League not found.');
  l.market_open = isOpen;
  return { league_id: leagueId, market_open: isOpen };
}

export async function getTeamRoster(_leagueId: number, teamId: number): Promise<TeamRoster> {
  await sleep(80);
  return { team_id: teamId, team_name: `Team ${teamId}`, players: [] };
}

export async function addRosterPlayer(_leagueId: number, _teamId: number, playerId: number, _purchasePrice = 1) {
  await sleep(80);
  return { player_id: playerId };
}

export async function removeRosterPlayer(_leagueId: number, _teamId: number, _playerId: number) {
  await sleep(80);
  return { ok: true };
}

export async function bulkAssignRoster(
  _leagueId: number,
  payload:
    | { player_ids: number[]; purchase_price?: number; random_seed?: number }
    | { assignments: Array<{ team_name?: string; manager_username?: string; player_id: number; price?: number; purchase_price?: number }>; purchase_price?: number; random_seed?: number }
) {
  await sleep(100);
  if ('assignments' in payload) return { assigned_players: payload.assignments.length, mode: 'explicit' };
  return { assigned_players: payload.player_ids.length, mode: 'random' };
}

export async function importRosterCsv(_leagueId: number, csvText?: string, _file?: File | null) {
  await sleep(100);
  const rows = (csvText ?? '').trim().split('\n').slice(1).filter(Boolean).length;
  return { imported: rows };
}

export async function createCompetitionTemplate(_leagueId: number, req: CompetitionTemplateRequest) {
  await sleep(100);
  return { competition_id: 1, name: req.name, competition_type: req.competition_type, participants: req.team_ids?.length ?? 0, fixtures_created: 1 };
}

export async function getCompetitions(_leagueId: number): Promise<CompetitionItem[]> {
  await sleep(100);
  return [
    {
      competition_id: 1,
      name: 'Campionato Mock',
      competition_type: 'round_robin',
      status: 'active',
      points: { win: 3, draw: 1, loss: 0 },
      participants: [],
      qualification_rules: [],
      fixtures: { total: 6, finished: 2 },
    },
  ];
}

export async function updateCompetition(competitionId: number, req: CompetitionUpdateRequest): Promise<CompetitionItem> {
  await sleep(90);
  return {
    competition_id: competitionId,
    name: req.name ?? 'Campionato Mock',
    competition_type: 'round_robin',
    status: req.status ?? 'active',
    points: {
      win: req.points_win ?? 3,
      draw: req.points_draw ?? 1,
      loss: req.points_loss ?? 0,
    },
    participants: [],
    qualification_rules: [],
    fixtures: { total: 6, finished: 2 },
  };
}

export async function addCompetitionRule(_competitionId: number, req: QualificationRuleCreateRequest) {
  await sleep(90);
  return { rule_id: 1, ...req };
}

export async function resolveCompetitionDependencies(competitionId: number) {
  await sleep(90);
  return { competition_id: competitionId, resolved_rule_participants: 1, unresolved_rules: 0, fixtures_created: 4 };
}

export async function createAuction(_leagueId: number, playerIds: number[]) {
  await sleep(100);
  return { auction_id: 1, players: playerIds.length };
}

export async function nominateNext(_auctionId: number) {
  await sleep(80);
  return { nomination_id: 1, player_id: 1, player_name: 'Mock Player' };
}

export async function placeBid(_nominationId: number, amount: number) {
  await sleep(60);
  return { bid_id: 1, amount };
}

export async function closeNomination(_nominationId: number) {
  await sleep(80);
  return { nomination_id: 1, winner_team_id: 1 };
}

export async function searchPlayers(q: string): Promise<PlayerSearchItem[]> {
  await sleep(80);
  if (q.trim().length < 2) return [];
  return [
    { player_id: 101, name: 'L. Martinez', full_name: 'Lautaro Martinez' },
    { player_id: 102, name: 'R. Leao', full_name: 'Rafael Leao' },
    { player_id: 103, name: 'N. Barella', full_name: 'Nicolo Barella' },
  ].filter((p) => p.full_name.toLowerCase().includes(q.toLowerCase()) || p.name.toLowerCase().includes(q.toLowerCase()));
}

export async function getAuctionState(auctionId: number): Promise<AuctionState> {
  await sleep(90);
  return {
    auction_id: auctionId,
    name: 'Mock Auction',
    status: 'active',
    nomination_index: 3,
    nomination_total: 60,
    next_player: { player_id: 104, name: 'M. Thuram' },
    open_nomination: { nomination_id: 7, player_id: 103, player_name: 'N. Barella', nominator: 'mock-admin' },
    recent_nominations: [
      {
        nomination_id: 7,
        status: 'open',
        player_id: 103,
        player_name: 'N. Barella',
        nominator: 'mock-admin',
        top_bid: 18,
        winner_team_id: null,
        winner_team_name: null,
      },
      {
        nomination_id: 6,
        status: 'closed',
        player_id: 102,
        player_name: 'R. Leao',
        nominator: 'mock-user',
        top_bid: 42,
        winner_team_id: 11,
        winner_team_name: 'Mock Team',
      },
    ],
    team_budgets: [
      { team_id: 11, team_name: 'Mock Team', manager_username: 'mock-admin', initial_budget: 500, spent_budget: 42, available_budget: 458 },
      { team_id: 12, team_name: 'Mock Team 2', manager_username: 'mock-user', initial_budget: 500, spent_budget: 18, available_budget: 482 },
    ],
  };
}
