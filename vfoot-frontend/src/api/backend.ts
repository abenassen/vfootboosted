import type {
  LineupContextResponse,
  MatchDetailResponse,
  MatchListItem,
  SaveLineupRequest,
  SaveLineupResponse,
} from '../types/contracts';
import type {
  AuthResponse,
  AuthUser,
  LoginRequest,
  RegisterRequest,
  RegisterResponse,
  VerifyEmailRequest,
  VerifyEmailResponse,
} from '../types/auth';
import type {
  AuctionState,
  CompetitionItem,
  CompetitionScheduleApplyResult,
  CompetitionSchedulePreview,
  CompetitionPrizeCreateRequest,
  CompetitionPrizeItem,
  CompetitionStageCreateRequest,
  CompetitionStageUpdateRequest,
  CompetitionStageRuleCreateRequest,
  CompetitionStageRuleCreateResult,
  CompetitionStageItem,
  CompetitionUpdateRequest,
  CompetitionTemplateRequest,
  CreateLeagueRequest,
  JoinLeagueRequest,
  LeagueDetail,
  RealSeasonItem,
  ReferenceSeason,
  LeagueFixtureItem,
  LeagueMatchdayItem,
  LeagueStandingRow,
  LeagueSummary,
  PlayerSearchItem,
  QualificationRuleCreateRequest,
  TeamRoster,
} from '../types/league';
import type { SimFixtureDetail } from '../types/simulation';
import type { ClassicFixtureDetail } from '../types/classic';
import type { ChampionshipPlayersResponse, RealFixturesResponse } from '../types/realChampionship';
import type { SaveTeamLineupRequest, TeamLineupContext } from '../types/lineup';

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

/** An API failure carrying the HTTP status and the raw server payload, while its
 *  ``message`` is a sentence meant for the user. */
export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/** Technical field names -> the label the user sees in the form. */
const FIELD_LABELS: Record<string, string> = {
  name: 'Nome',
  team_name: 'Nome squadra',
  reference_season_id: 'Campionato di riferimento',
  invite_code: 'Codice invito',
  username: 'Username',
  email: 'Email',
  password: 'Password',
  password_confirm: 'Conferma password',
  competition_id: 'Competizione',
  matchday: 'Giornata',
  player_id: 'Giocatore',
  price: 'Prezzo',
  max_substitutions: 'Sostituzioni massime',
  non_field_errors: 'Errore',
};

/** Turn an HTTP failure into something a person can act on. The backend's own
 *  ``detail`` is preferred when present (ours are written in Italian for the user);
 *  otherwise the status decides. */
function humanMessage(status: number, parsed: any, statusText: string, url = ''): string {
  const detail =
    parsed && typeof parsed === 'object' && typeof parsed.detail === 'string'
      ? parsed.detail
      : null;

  if (status === 401) {
    // Decide from the ENDPOINT, not from a stored token: a stale token can linger
    // in localStorage while the user is in fact just signing in.
    return /\/auth\/(login|register)$/.test(url)
      ? 'Username o password non corretti.'
      : 'Sessione scaduta. Effettua di nuovo l’accesso.';
  }
  if (status === 403) return detail ?? 'Non hai i permessi per questa operazione.';
  if (status === 429) return detail ?? 'Troppi tentativi. Riprova tra qualche minuto.';
  if (status === 404) return detail ?? 'Risorsa non trovata.';
  if (status === 400) {
    if (detail) return detail;
    // DRF field errors: {campo: ["messaggio", …]}. The messages themselves already
    // come back in Italian; only the KEYS are technical, so we label them.
    if (parsed && typeof parsed === 'object') {
      const parts = Object.entries(parsed).map(
        ([field, msgs]) =>
          `${FIELD_LABELS[field] ?? field}: ${Array.isArray(msgs) ? msgs.join(' ') : String(msgs)}`,
      );
      if (parts.length) return parts.join(' · ');
    }
    return 'Dati non validi. Controlla i campi e riprova.';
  }
  if (status >= 500) return 'Errore del server. Riprova più tardi.';
  return detail ?? statusText ?? 'Operazione non riuscita.';
}

async function parseJsonOrThrow(res: Response): Promise<any> {
  const raw = await res.text();
  let parsed: unknown = null;
  if (raw) {
    try {
      parsed = JSON.parse(raw);
    } catch {
      parsed = null;
    }
  }

  if (!res.ok) {
    const details =
      parsed !== null ? (typeof parsed === 'string' ? parsed : JSON.stringify(parsed)) : raw;
    // Keep the raw payload for debugging, but never show it to the user.
    console.warn(`API ${res.status} ${res.url}:`, details || res.statusText);
    throw new ApiError(
      res.status, details, humanMessage(res.status, parsed, res.statusText, res.url));
  }

  if (!raw) return {};
  if (parsed !== null) return parsed;
  return raw;
}

export function hasStoredSession(): boolean {
  return !!getToken();
}

function jsonPost(path: string, body: unknown): Promise<Response> {
  return fetch(`${baseUrl()}${path}`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
}

/** No token is stored here on purpose: the account is not usable until confirmed. */
export async function register(req: RegisterRequest): Promise<RegisterResponse> {
  const res = await jsonPost('/auth/register', req);
  return (await parseJsonOrThrow(res)) as RegisterResponse;
}

export async function verifyEmail(req: VerifyEmailRequest): Promise<VerifyEmailResponse> {
  const res = await jsonPost('/auth/verify-email', req);
  const data = (await parseJsonOrThrow(res)) as VerifyEmailResponse;
  // Only a first, successful confirmation hands back credentials.
  if (data.token) setToken(data.token);
  return data;
}

export async function resendVerification(email: string): Promise<{ detail: string }> {
  const res = await jsonPost('/auth/resend-verification', { email });
  return (await parseJsonOrThrow(res)) as { detail: string };
}

export async function googleSignIn(credential: string): Promise<AuthResponse> {
  const res = await jsonPost('/auth/google', { credential });
  const data = (await parseJsonOrThrow(res)) as AuthResponse;
  setToken(data.token);
  return data;
}

export async function login(req: LoginRequest): Promise<AuthResponse> {
  const res = await jsonPost('/auth/login', req);
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

export interface LeagueSettingsPatch {
  max_substitutions?: number;
  defense_bonus_enabled?: boolean;
  defense_bonus_mode?: 'add_own' | 'subtract_opponent';
}

export async function updateLeagueSettings(leagueId: number, settings: LeagueSettingsPatch) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/settings`, {
    method: 'PATCH',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(settings),
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

export async function bulkAssignRoster(
  leagueId: number,
  payload:
    | { player_ids: number[]; purchase_price?: number; random_seed?: number }
    | { assignments: Array<{ team_name?: string; manager_username?: string; player_id: number; price?: number; purchase_price?: number }>; purchase_price?: number; random_seed?: number }
) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/roster/bulk-assign`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
  });
  return parseJsonOrThrow(res);
}

export async function importRosterCsv(leagueId: number, csvText?: string, file?: File | null) {
  const url = `${baseUrl()}/leagues/${leagueId}/roster/import-csv`;

  if (file) {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(url, {
      method: 'POST',
      headers: { Accept: 'application/json', ...authHeaders() },
      body: formData,
    });
    return parseJsonOrThrow(res);
  }

  const res = await fetch(url, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ csv_text: csvText ?? '' }),
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

export async function getCompetitions(leagueId: number): Promise<CompetitionItem[]> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/competitions`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function updateCompetition(competitionId: number, req: CompetitionUpdateRequest): Promise<CompetitionItem> {
  const res = await fetch(`${baseUrl()}/competitions/${competitionId}`, {
    method: 'PATCH',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  return parseJsonOrThrow(res);
}

export async function deleteCompetition(competitionId: number): Promise<void> {
  const res = await fetch(`${baseUrl()}/competitions/${competitionId}`, {
    method: 'DELETE',
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  if (res.status === 204) return;
  await parseJsonOrThrow(res);
}

export async function getRealSeasons(): Promise<RealSeasonItem[]> {
  const res = await fetch(`${baseUrl()}/real-seasons`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function setLeagueReferenceSeason(
  leagueId: number,
  referenceSeasonId: number | null
): Promise<{ league_id: number; reference_season: ReferenceSeason | null }> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/reference-season`, {
    method: 'PATCH',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ reference_season_id: referenceSeasonId }),
  });
  return parseJsonOrThrow(res);
}

export async function scheduleCompetition(
  competitionId: number,
  payload: {
    starts_at?: string | null;
    ends_at?: string | null;
    start_matchday?: number | null;
    end_matchday?: number | null;
    round_mapping?: Record<string, number>;
  } = {}
): Promise<CompetitionScheduleApplyResult> {
  const res = await fetch(`${baseUrl()}/competitions/${competitionId}/schedule`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
  });
  return parseJsonOrThrow(res);
}

export async function previewCompetitionSchedule(
  competitionId: number,
  payload: {
    starts_at?: string | null;
    ends_at?: string | null;
    start_matchday?: number | null;
    end_matchday?: number | null;
  } = {}
): Promise<CompetitionSchedulePreview> {
  const res = await fetch(`${baseUrl()}/competitions/${competitionId}/schedule/preview`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
  });
  return parseJsonOrThrow(res);
}

export async function addCompetitionRule(competitionId: number, req: QualificationRuleCreateRequest) {
  const res = await fetch(`${baseUrl()}/competitions/${competitionId}/rules`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  return parseJsonOrThrow(res);
}

export async function resolveCompetitionDependencies(competitionId: number) {
  const res = await fetch(`${baseUrl()}/competitions/${competitionId}/resolve`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({}),
  });
  return parseJsonOrThrow(res);
}

export async function getCompetitionStages(competitionId: number): Promise<CompetitionStageItem[]> {
  const res = await fetch(`${baseUrl()}/competitions/${competitionId}/stages`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function createCompetitionStage(
  competitionId: number,
  req: CompetitionStageCreateRequest
): Promise<CompetitionStageItem> {
  const res = await fetch(`${baseUrl()}/competitions/${competitionId}/stages/create`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  return parseJsonOrThrow(res);
}

export async function updateCompetitionStage(
  stageId: number,
  req: CompetitionStageUpdateRequest
): Promise<CompetitionStageItem> {
  const res = await fetch(`${baseUrl()}/stages/${stageId}`, {
    method: 'PATCH',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  return parseJsonOrThrow(res);
}

export async function deleteCompetitionStage(stageId: number): Promise<void> {
  const res = await fetch(`${baseUrl()}/stages/${stageId}`, {
    method: 'DELETE',
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  if (res.status === 204) return;
  await parseJsonOrThrow(res);
}

export async function addCompetitionStageRule(
  stageId: number,
  req: CompetitionStageRuleCreateRequest
): Promise<CompetitionStageRuleCreateResult> {
  const res = await fetch(`${baseUrl()}/stages/${stageId}/rules`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  return parseJsonOrThrow(res);
}

export async function getCompetitionPrizes(competitionId: number): Promise<CompetitionPrizeItem[]> {
  const res = await fetch(`${baseUrl()}/competitions/${competitionId}/prizes`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function createCompetitionPrize(
  competitionId: number,
  req: CompetitionPrizeCreateRequest
): Promise<CompetitionPrizeItem> {
  const res = await fetch(`${baseUrl()}/competitions/${competitionId}/prizes`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  return parseJsonOrThrow(res);
}

export async function deleteCompetitionPrize(prizeId: number): Promise<void> {
  const res = await fetch(`${baseUrl()}/prizes/${prizeId}`, {
    method: 'DELETE',
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  if (res.status === 204) return;
  await parseJsonOrThrow(res);
}

export async function buildDefaultCompetitionStages(
  competitionId: number,
  allowRepechage = false,
  randomSeed = 42,
  doubleRound = false
) {
  const res = await fetch(`${baseUrl()}/competitions/${competitionId}/stages/default-build`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ allow_repechage: allowRepechage, random_seed: randomSeed, double_round: doubleRound }),
  });
  return parseJsonOrThrow(res);
}

export async function resolveCompetitionStage(stageId: number, randomSeed = 42) {
  const res = await fetch(`${baseUrl()}/stages/${stageId}/resolve`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ random_seed: randomSeed }),
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

export async function getLeagueFixtures(leagueId: number, competitionId?: number): Promise<LeagueFixtureItem[]> {
  const params = new URLSearchParams();
  if (competitionId) params.set('competition_id', String(competitionId));
  const suffix = params.toString() ? `?${params.toString()}` : '';
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/fixtures${suffix}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function getLeagueStandings(
  leagueId: number,
  competitionId?: number,
): Promise<{ competition_id: number | null; standings: LeagueStandingRow[] }> {
  const qs = competitionId ? `?competition_id=${competitionId}` : '';
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/standings${qs}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function getCompetitionStructure(
  leagueId: number,
  competitionId: number,
): Promise<import('../types/league').CompetitionStructure> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/competitions/${competitionId}/structure`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function getFixtureDetail(
  fixtureId: number | string,
): Promise<SimFixtureDetail | ClassicFixtureDetail> {
  const res = await fetch(`${baseUrl()}/fixtures/${fixtureId}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

// Real reference-championship (Serie A) calendar + results.
export async function getRealFixtures(
  leagueId: number,
  matchday?: number,
): Promise<RealFixturesResponse> {
  const qs = matchday ? `?matchday=${matchday}` : '';
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/real-fixtures${qs}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

// Vote-relevant detail of a real match (pagella), shaped as a classic fixture.
export async function getRealMatchDetail(
  leagueId: number,
  matchId: number | string,
): Promise<ClassicFixtureDetail> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/real-matches/${matchId}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

// Full player pool of the league's reference championship (the "listone").
export async function getChampionshipPlayers(
  leagueId: number,
): Promise<ChampionshipPlayersResponse> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/championship-players`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function getTeamLineup(
  leagueId: number,
  matchday?: number | null,
  competition?: number | null,
): Promise<TeamLineupContext> {
  const params = new URLSearchParams();
  if (matchday != null) params.set('matchday', String(matchday));
  if (competition != null) params.set('competition', String(competition));
  const q = params.toString() ? `?${params.toString()}` : '';
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/lineup${q}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function saveTeamLineup(
  leagueId: number,
  req: SaveTeamLineupRequest,
): Promise<{ ok: boolean; saved_competitions: number }> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/lineup/save`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  return parseJsonOrThrow(res);
}

export async function syncLeagueMatchdays(leagueId: number): Promise<{ fixtures_linked: number; matchdays_touched: number }> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/matchdays/sync`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({}),
  });
  return parseJsonOrThrow(res);
}

export async function getLeagueMatchdays(leagueId: number): Promise<LeagueMatchdayItem[]> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/matchdays`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function concludeLeagueMatchday(leagueId: number, fantasyMatchdayId: number, force = false) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/matchdays/${fantasyMatchdayId}/conclude`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ force }),
  });
  return parseJsonOrThrow(res);
}

export async function searchPlayers(q: string, leagueId?: number, limit = 20): Promise<PlayerSearchItem[]> {
  const params = new URLSearchParams();
  params.set('q', q);
  params.set('limit', String(limit));
  if (leagueId) params.set('league_id', String(leagueId));

  const res = await fetch(`${baseUrl()}/players/search?${params.toString()}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function getAuctionState(auctionId: number): Promise<AuctionState> {
  const res = await fetch(`${baseUrl()}/auctions/${auctionId}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}
