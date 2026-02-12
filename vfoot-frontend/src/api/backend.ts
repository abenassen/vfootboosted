import type {
  LineupContextResponse,
  MatchDetailResponse,
  MatchListItem,
  SaveLineupRequest,
  SaveLineupResponse,
} from '../types/contracts';
import type { AuthResponse, AuthUser, LoginRequest, RegisterRequest } from '../types/auth';
import type {
  CompetitionTemplateRequest,
  CreateLeagueRequest,
  JoinLeagueRequest,
  LeagueDetail,
  LeagueSummary,
  TeamRoster,
} from '../types/league';

const DEFAULT_BASE_URL = 'http://localhost:8000/api/v1';
const TOKEN_STORAGE_KEY = 'vfoot_auth_token';

function trimTrailingSlash(s: string): string {
  return s.replace(/\/+$/, '');
}

function baseUrl(): string {
  const v = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
  return trimTrailingSlash(v && v.length > 0 ? v : DEFAULT_BASE_URL);
}

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

function setToken(token: string | null) {
  if (typeof window === 'undefined') return;
  if (!token) {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  if (!token) return {};
  return { Authorization: `Token ${token}` };
}

async function parseJsonOrThrow(res: Response) {
  if (!res.ok) {
    let details = '';
    try {
      const data = await res.json();
      details = typeof data === 'string' ? data : JSON.stringify(data);
    } catch {
      details = await res.text();
    }
    throw new Error(`API ${res.status}: ${details || res.statusText}`);
  }
  return res.json();
}

export function hasStoredSession(): boolean {
  return !!getToken();
}

export async function register(req: RegisterRequest): Promise<AuthResponse> {
  const res = await fetch(`${baseUrl()}/auth/register`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(req),
  });
  const data = (await parseJsonOrThrow(res)) as AuthResponse;
  setToken(data.token);
  return data;
}

export async function login(req: LoginRequest): Promise<AuthResponse> {
  const res = await fetch(`${baseUrl()}/auth/login`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(req),
  });
  const data = (await parseJsonOrThrow(res)) as AuthResponse;
  setToken(data.token);
  return data;
}

export async function getCurrentUser(): Promise<AuthUser> {
  const res = await fetch(`${baseUrl()}/auth/me`, {
    headers: {
      Accept: 'application/json',
      ...authHeaders(),
    },
  });
  const data = (await parseJsonOrThrow(res)) as { user: AuthUser };
  return data.user;
}

export async function logout(): Promise<void> {
  const token = getToken();
  if (!token) return;
  try {
    await fetch(`${baseUrl()}/auth/logout`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        ...authHeaders(),
      },
    });
  } finally {
    setToken(null);
  }
}

export async function getLineupContext(): Promise<LineupContextResponse> {
  const res = await fetch(`${baseUrl()}/lineup/context`, {
    headers: {
      Accept: 'application/json',
      ...authHeaders(),
    },
  });
  return parseJsonOrThrow(res);
}

export async function saveLineup(req: SaveLineupRequest): Promise<SaveLineupResponse> {
  const res = await fetch(`${baseUrl()}/lineup/save`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body: JSON.stringify(req),
  });
  return parseJsonOrThrow(res);
}

export async function getMatches(): Promise<MatchListItem[]> {
  const res = await fetch(`${baseUrl()}/matches`, {
    headers: {
      Accept: 'application/json',
      ...authHeaders(),
    },
  });
  return parseJsonOrThrow(res);
}

export async function getMatchDetail(matchId: string): Promise<MatchDetailResponse> {
  const res = await fetch(`${baseUrl()}/matches/${encodeURIComponent(matchId)}`, {
    headers: {
      Accept: 'application/json',
      ...authHeaders(),
    },
  });
  return parseJsonOrThrow(res);
}

export async function getLeagues(): Promise<LeagueSummary[]> {
  const res = await fetch(`${baseUrl()}/leagues`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function createLeague(req: CreateLeagueRequest): Promise<{ league_id: number; invite_code: string }> {
  const res = await fetch(`${baseUrl()}/leagues`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  return parseJsonOrThrow(res);
}

export async function joinLeague(req: JoinLeagueRequest): Promise<{ league_id: number; team_id: number }> {
  const res = await fetch(`${baseUrl()}/leagues/join`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  return parseJsonOrThrow(res);
}

export async function getLeagueDetail(leagueId: number): Promise<LeagueDetail> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function updateMemberRole(leagueId: number, membershipId: number, role: 'admin' | 'manager') {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/members/${membershipId}/role`, {
    method: 'PATCH',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ role }),
  });
  return parseJsonOrThrow(res);
}

export async function setMarketStatus(leagueId: number, isOpen: boolean) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/market`, {
    method: 'PATCH',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ is_open: isOpen }),
  });
  return parseJsonOrThrow(res);
}

export async function getTeamRoster(leagueId: number, teamId: number): Promise<TeamRoster> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/teams/${teamId}/roster`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function addRosterPlayer(leagueId: number, teamId: number, playerId: number, purchasePrice = 1) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/teams/${teamId}/roster/add`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ player_id: playerId, purchase_price: purchasePrice }),
  });
  return parseJsonOrThrow(res);
}

export async function removeRosterPlayer(leagueId: number, teamId: number, playerId: number) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/teams/${teamId}/roster/remove`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ player_id: playerId }),
  });
  if (res.status === 204) return { ok: true };
  return parseJsonOrThrow(res);
}

export async function bulkAssignRoster(leagueId: number, playerIds: number[], purchasePrice = 1, randomSeed = 42) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/roster/bulk-assign`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ player_ids: playerIds, purchase_price: purchasePrice, random_seed: randomSeed }),
  });
  return parseJsonOrThrow(res);
}

export async function importRosterCsv(leagueId: number, csvText: string) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/roster/import-csv`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ csv_text: csvText }),
  });
  return parseJsonOrThrow(res);
}

export async function createCompetitionTemplate(leagueId: number, req: CompetitionTemplateRequest) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/competitions/template`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  return parseJsonOrThrow(res);
}

export async function createAuction(leagueId: number, playerIds: number[], randomSeed = 42) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/auctions`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ player_ids: playerIds, random_seed: randomSeed }),
  });
  return parseJsonOrThrow(res);
}

export async function nominateNext(auctionId: number) {
  const res = await fetch(`${baseUrl()}/auctions/${auctionId}/nominate-next`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({}),
  });
  return parseJsonOrThrow(res);
}

export async function placeBid(nominationId: number, amount: number) {
  const res = await fetch(`${baseUrl()}/nominations/${nominationId}/bid`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ amount }),
  });
  return parseJsonOrThrow(res);
}

export async function closeNomination(nominationId: number) {
  const res = await fetch(`${baseUrl()}/nominations/${nominationId}/close`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({}),
  });
  return parseJsonOrThrow(res);
}
