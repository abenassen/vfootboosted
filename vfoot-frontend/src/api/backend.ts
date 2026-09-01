import type {
  DecideResponse,
  MaintenanceState,
  ProposalDetail,
} from '../types/maintenance';
import type { LeagueDecision, LeagueDecisionsResponse } from '../types/decisions';
import type { NewsResponse } from '../types/news';
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
  PasswordChangeRequest,
  ProfileUpdateRequest,
  RegisterRequest,
  RegisterResponse,
  VerifyEmailRequest,
  VerifyEmailResponse,
} from '../types/auth';
import type {
  ActiveAuctionInfo,
  AuctionRosters,
  AuctionState,
  ClassicRole,
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
  CompetitionWizardPlan,
  CompetitionWizardRequest,
  CompetitionWizardResult,
  CreateLeagueRequest,
  JoinLeagueRequest,
  LeagueDetail,
  ManagerHonours,
  ManagerProfile,
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
import type { ClassicFixtureDetail, VoteLedger } from '../types/classic';
import type {
  ChampionshipPlayersResponse,
  ProbableLineups,
  RealFixturesResponse,
  RealScope,
} from '../types/realChampionship';
import type { SaveTeamLineupRequest, TeamLineupContext } from '../types/lineup';
import type {
  MarketActive,
  MarketDiscardPreview,
  MarketRecoveryMode,
  MarketSessionHistory,
} from '../types/market';

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

/** Il server dice che la rosa su cui la pagina sta lavorando non è più quella
 *  vera: fra il caricamento e l'invio qualcosa l'ha cambiata (una validazione di
 *  mercato). Il rimedio è RICARICARE, non ritentare — lo stesso invio verrebbe
 *  rifiutato uguale, e insistere disferebbe la riparazione già applicata.
 *
 *  Torna anche i nomi, perché «la tua rosa è cambiata» senza dire CHI non è un
 *  avviso, è un enigma: l'allenatore deve poter riconoscere il giocatore che sta
 *  guardando sullo schermo. `null` quando l'errore è un altro. */
export function rosterChanged(e: unknown): { detail: string; names: string[] } | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  try {
    const parsed = JSON.parse(e.detail) as {
      roster_changed?: unknown; detail?: unknown; errors?: unknown;
    };
    if (parsed?.roster_changed !== true) return null;
    return {
      detail: typeof parsed.detail === 'string' ? parsed.detail : e.message,
      names: Array.isArray(parsed.errors) ? parsed.errors.map(String) : [],
    };
  } catch {
    return null;
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

/** Di quanto l'orologio del server e' avanti rispetto a quello di questo browser.
 *
 *  Zero quasi sempre, e diverso da zero solo quando il backend gira con l'orologio
 *  simulato (VFOOT_FAKE_NOW): li' il server vive mesi avanti, e un conto alla
 *  rovescia calcolato con `Date.now()` misurerebbe fra una scadenza simulata e un
 *  adesso reale — mesi, invece dei minuti che l'utente si aspetta.
 *
 *  Si aggiorna da se' a ogni risposta, quindi non puo' invecchiare, e in assenza
 *  dell'intestazione resta zero: senza orologio simulato nulla cambia. */
let serverSkewMs = 0;

/** L'adesso del SERVER in millisecondi. Da usare ovunque si confronti il tempo con
 *  una data che arriva dal server; `Date.now()` resta giusto per tutto il resto. */
export function serverNow(): number {
  return Date.now() + serverSkewMs;
}

function noteServerClock(res: Response): void {
  const stamp = res.headers.get('X-Vfoot-Now');
  if (!stamp) return;
  const t = new Date(stamp).getTime();
  if (!Number.isNaN(t)) serverSkewMs = t - Date.now();
}

async function parseJsonOrThrow(res: Response): Promise<any> {
  noteServerClock(res);
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

/** POST with NO credentials. For the auth endpoints only: they are the ones you
 *  call while signed out, and sending a stale token there would have DRF reject
 *  the request before the view ever sees the login attempt. */
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

/** POST as the signed-in user. Everything that is not an auth endpoint wants
 *  this one — without the token the request comes back 401, which the UI reports
 *  as an expired session, so a missing header looks exactly like being logged
 *  out and nothing on the page can be acted on. */
function authedPost(path: string, body: unknown): Promise<Response> {
  return fetch(`${baseUrl()}${path}`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...authHeaders(),
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

export async function requestPasswordReset(email: string): Promise<{ detail: string }> {
  const res = await jsonPost('/auth/password-reset', { email });
  return (await parseJsonOrThrow(res)) as { detail: string };
}

export async function confirmPasswordReset(req: {
  uid: string;
  token: string;
  new_password: string;
  new_password_confirm: string;
}): Promise<AuthResponse> {
  const res = await jsonPost('/auth/password-reset/confirm', req);
  const data = (await parseJsonOrThrow(res)) as AuthResponse;
  // The reset ends signed in: the link already proved the address, and asking
  // for the password just chosen would be asking twice for the same thing.
  setToken(data.token);
  return data;
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

export async function updateProfile(patch: ProfileUpdateRequest): Promise<AuthUser> {
  const res = await fetch(`${baseUrl()}/auth/me`, {
    method: 'PATCH',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(patch),
  });
  const data = (await parseJsonOrThrow(res)) as { user: AuthUser };
  return data.user;
}

export async function changePassword(req: PasswordChangeRequest): Promise<AuthUser> {
  const res = await fetch(`${baseUrl()}/auth/password`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  // The server rotates the token on password change; keep the new one so the
  // session survives without a re-login.
  const data = (await parseJsonOrThrow(res)) as { token: string; user: AuthUser };
  setToken(data.token);
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
    forgetSelections();
  }
}

/** Quale lega e quale competizione si stava guardando. Sopravvivevano al logout,
 * e sono di chi esce, non del browser: sullo stesso computer — due amici, o un
 * telefono passato di mano — il secondo entrava e la prima pagina gli chiedeva
 * il dettaglio della lega del primo, cioe' un «Not a member of this league» in
 * rosso su una lega di cui non sa niente. */
function forgetSelections(): void {
  if (typeof window === 'undefined') return;
  const store = window.localStorage;
  const doomed = Object.keys(store).filter(
    (k) => k === 'vfoot_selected_league_id' || k.startsWith('vfoot_selected_competition_'),
  );
  doomed.forEach((k) => store.removeItem(k));
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

export async function joinLeague(
  req: JoinLeagueRequest,
): Promise<{ league_id: number; team_id: number | null; name: string; already_member?: boolean }> {
  const res = await fetch(`${baseUrl()}/leagues/join`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  return parseJsonOrThrow(res);
}

/** Cosa c'è dietro un codice d'invito, prima di entrarci. Senza sessione risponde
 *  lo stesso (chi ha il codice può entrare comunque): `already_member` è la sola
 *  parte che dipende da chi chiede, e senza token è sempre falsa. */
export interface LeagueInvitePreview {
  league_id: number;
  invite_code: string;
  name: string;
  mode: 'aura' | 'classic';
  teams: number;
  reference_season: string | null;
  admin_username: string | null;
  already_member: boolean;
  team_name: string | null;
}

export async function getLeagueInvite(code: string): Promise<LeagueInvitePreview> {
  const res = await fetch(`${baseUrl()}/leagues/invite/${encodeURIComponent(code)}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

/** Rename the caller's own team in a league and/or set its crest. Both fields are
 *  optional: saving a new name must not overwrite a crest the user never opened. */
export async function updateMyTeam(
  leagueId: number,
  patch: { name?: string; crest?: string },
): Promise<{ team_id: number; name: string; crest: string }> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/team`, {
    method: 'PATCH',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(patch),
  });
  return parseJsonOrThrow(res);
}

/** Where the bytes of an uploaded crest live. Built from the hash, so it is
 *  immutable by construction: that content is at that address and nowhere else,
 *  which is what lets the server answer with a one-year immutable cache.
 *
 *  No token is attached, and none could be: this URL ends up in an <image> tag,
 *  which cannot send an Authorization header. What protects it is the address
 *  itself — sixty-four hex digits nobody guesses. */
export function crestImageUrl(hash: string): string {
  return `${baseUrl()}/crest-images/${hash}`;
}

/** Upload an image and get back its hash, to be written into a crest descriptor.
 *
 *  Deliberately NOT part of saving the team: the two are separate gestures, so
 *  an upload the user then abandons leaves nothing half-applied. What comes back
 *  is a claim the descriptor will carry — the server does not record who uses
 *  which image, and does not need to. */
export async function uploadCrestImage(file: Blob): Promise<{ hash: string; bytes: number }> {
  const form = new FormData();
  form.append('file', file, 'stemma.webp');
  const res = await fetch(`${baseUrl()}/crest-images`, {
    method: 'POST',
    // No Content-Type here on purpose: the browser has to set it, because only
    // it knows the multipart boundary it just generated.
    headers: { Accept: 'application/json', ...authHeaders() },
    body: form,
  });
  return parseJsonOrThrow(res);
}

/** "Questo stemma non va bene": any member of the league may say it. */
export async function reportCrestImage(
  leagueId: number,
  hash: string,
  reason?: string,
): Promise<{ id: number; created: boolean; detail: string }> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/crest-reports`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ hash, reason: reason ?? '' }),
  });
  return parseJsonOrThrow(res);
}

/** The league admin takes an image out of circulation. Nothing else has to
 *  happen: the descriptors that named it keep their composed layers, and those
 *  are what gets drawn from the next render on. */
export async function revokeCrestImage(
  leagueId: number,
  hash: string,
  reason?: string,
): Promise<{ hash: string; revoked: boolean }> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/crest-revoke`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ hash, reason: reason ?? '' }),
  });
  return parseJsonOrThrow(res);
}

export interface LeagueActivityItem {
  /** `acquisto` is the FANTASY market (a manager buying); the other two are the
   *  REAL one, and they are separate because they answer different questions:
   *  `mercato_reale` is a player ENTERING the listone (someone you could not own
   *  before), `trasferimento_reale` is one already in it CHANGING club (someone
   *  you may own right now). */
  kind:
    | 'acquisto'
    /** Scambio fra due allenatori: i contratti cambiano squadra col loro prezzo.
     *  Non e' un `acquisto` — nessuno ha speso crediti per prendere quel
     *  giocatore — ed e' per questo che ha un tipo suo. */
    | 'scambio'
    /** Crediti dati (o tolti) dall'admin fuori da asta e mercato. */
    | 'concessione'
    | 'mercato_reale'
    | 'trasferimento_reale'
    | 'decisione'
    | 'giornata'
    | 'competizione'
    | 'premio';
  at: string | null;
  text: string;
  detail: string | null;
  team_id: number | null;
  crest: string | null;
  /** Notizia che merita di essere vista anche da chi apre l'app dopo giorni. Un
   *  premio lo è da sé; il flag esiste per notizia, non per tipo. */
  important?: boolean;
  /** In evidenza ADESSO: importante e ancora fresca. La precedenza scade da sola
   *  (v. NEWS_PIN_DAYS lato server), così una notizia in cima non diventa
   *  l'arredamento su cui si smette di posare gli occhi. */
  pinned?: boolean;
}

/** L'albo d'oro di UNA lega, e se la lega è finita. */
export interface LeagueHonoursBoard {
  /** Ogni competizione della lega è chiusa: non c'è più niente da giocare. */
  is_over: boolean;
  competitions_total: number;
  competitions_finished: number;
  finished_at: string | null;
  awards: LeagueAwardItem[];
}

export interface LeagueAwardItem {
  prize_id: number;
  name: string;
  icon: string;
  condition_label: string;
  competition_id: number;
  competition_name: string;
  competition_format: string;
  winners: { team_id: number; name: string | null; crest: string }[];
  at: string | null;
}

export async function getLeagueHonours(leagueId: number): Promise<LeagueHonoursBoard> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/honours`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

/** Recent goings-on in the league, newest first. */
export async function getLeagueActivity(leagueId: number, limit = 12): Promise<LeagueActivityItem[]> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/activity?limit=${limit}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

/** The albo d'oro of one manager — everything he has won, in every league we
 *  share with him. 404 when we share none: see ManagerHonoursView. */
export async function getManagerHonours(userId: number): Promise<ManagerHonours> {
  const res = await fetch(`${baseUrl()}/managers/${userId}/honours`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

/** The public card of one manager: who he is and which of our leagues he plays
 *  in. Same visibility rule as the albo d'oro — 404 when we share none. */
export async function getManagerProfile(userId: number): Promise<ManagerProfile> {
  const res = await fetch(`${baseUrl()}/managers/${userId}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
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

export interface LeagueSettingsPatch {
  max_substitutions?: number;
  defense_bonus_enabled?: boolean;
  defense_bonus_mode?: 'add_own' | 'subtract_opponent';
  /** Su quale formazione si contano i 4 difensori: `starters` (quella schierata)
   *  o `effective` (quella acquisita, difensori con voto a fine giornata). */
  defense_bonus_gate?: 'starters' | 'effective';
  /** Voto d'ufficio per un buco in formazione (titolare senza voto e senza
   *  rimpiazzo in panchina). 0 = spento. Massimo 6. */
  sv_office_vote?: number;
  keeper_clean_sheet_enabled?: boolean;
  /** Punti di fantavoto a chi gioca in casa. 0 = spento. Si applica solo dove la
   *  partita ha un campo (`FantasyFixture.home_advantage`). */
  home_advantage_bonus?: number;
  enforce_lineup_deadline?: boolean;
  /** Che cosa si blocca, quando la scadenza e' attiva: tutta la formazione al primo
   *  calcio d'inizio, o ogni giocatore all'inizio della sua partita. */
  lineup_lock_mode?: 'matchday' | 'own' | 'player';
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

export async function addRosterPlayer(
  leagueId: number, teamId: number, playerId: number, purchasePrice = 1, force = false,
) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/teams/${teamId}/roster/add`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ player_id: playerId, purchase_price: purchasePrice, force }),
  });
  return parseJsonOrThrow(res);
}

/** Chiude il contratto: incasso deciso dall'admin, assente = il prezzo pagato. */
export async function sellRosterPlayer(
  leagueId: number, teamId: number, playerId: number, salePrice?: number,
) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/teams/${teamId}/roster/sell`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ player_id: playerId, sale_price: salePrice ?? null }),
  });
  return parseJsonOrThrow(res);
}

/** Cancella il contratto, come se non fosse mai stato firmato. */
export async function voidRosterSlot(leagueId: number, teamId: number, slotId: number) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/teams/${teamId}/roster/void`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ slot_id: slotId }),
  });
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

// Re-upload the filled listone .xlsx to assign rosters in one shot.
export async function importRosterXlsx(leagueId: number, file: File) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/roster/import-xlsx`, {
    method: 'POST',
    headers: { Accept: 'application/json', ...authHeaders() },
    body: formData,
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

/** Guided creation: one call builds shape, field, calendar and prizes together. */
export async function createCompetitionGuided(
  leagueId: number,
  req: CompetitionWizardRequest
): Promise<CompetitionWizardResult> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/competitions/wizard`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(req),
  });
  return parseJsonOrThrow(res);
}

export async function previewCompetitionPlan(
  leagueId: number,
  req: Omit<CompetitionWizardRequest, 'name' | 'prizes' | 'points' | 'start_matchday' | 'end_matchday'>
): Promise<CompetitionWizardPlan> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/competitions/wizard/preview`, {
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

/** Le edizioni dei campionati veri. `openOnly` tiene solo quelle ancora in corso:
 *  è quello che vuole chi deve SCEGLIERNE una — una lega si lega a un campionato
 *  che si sta giocando, e «il campionato» da consultare è quello di quest'anno. */
export async function getRealSeasons(openOnly = false): Promise<RealSeasonItem[]> {
  const res = await fetch(`${baseUrl()}/real-seasons${openOnly ? '?open=1' : ''}`, {
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
  legs = 1
) {
  const res = await fetch(`${baseUrl()}/competitions/${competitionId}/stages/default-build`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ allow_repechage: allowRepechage, random_seed: randomSeed, legs }),
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

function auctionPost(path: string, body: Record<string, unknown> = {}) {
  return fetch(`${baseUrl()}${path}`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  }).then(parseJsonOrThrow);
}

/* ------------------------------------------------------------------ *
 * Economia di lega: crediti dati dall'admin, e scambi fra allenatori.
 * ------------------------------------------------------------------ */

/** Una concessione = UN gesto dell'admin, anche quando ha toccato dieci squadre
 *  (il server le raggruppa per `batch`). */
export interface BudgetGrantRow {
  batch: string;
  amount: number;
  reason: string;
  at: string | null;
  teams: { team_id: number; name: string }[];
  /** Data a piu' di una squadra: in lista si dice "a tutti". */
  everyone: boolean;
}

export interface TradeSidePlayer {
  player_id: number;
  name: string | null;
  price: number;
  role: string | null;
}

export interface TradeRow {
  trade_id: number;
  at: string | null;
  team_a_id: number;
  team_b_id: number;
  team_a_name?: string;
  team_b_name?: string;
  note: string;
  a: TradeSidePlayer[];
  b: TradeSidePlayer[];
  cash: { amount: number; from: 'a' | 'b' } | null;
  /** Il pareggio dei contratti: i crediti passati da una parte all'altra perche'
   *  i due residui non si muovessero. Non lo decide nessuno — lo fa lo scambio. */
  settlement?: { amount: number; from: 'a' | 'b' } | null;
}

export interface TradeRequest {
  team_a: number;
  team_b: number;
  players_a: number[];
  players_b: number[];
  cash_amount?: number;
  cash_from?: 'a' | 'b';
  note?: string;
}

export async function getBudgetGrants(leagueId: number): Promise<{ grants: BudgetGrantRow[] }> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/budget/grants`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function grantCredits(
  leagueId: number,
  opts: { amount: number; reason?: string; team_ids?: number[] },
): Promise<{ batch: string; teams: number; amount: number }> {
  return auctionPost(`/leagues/${leagueId}/budget/grants`, opts);
}

export async function revokeBudgetGrant(
  leagueId: number, batch: string,
): Promise<{ revoked: number }> {
  return auctionPost(`/leagues/${leagueId}/budget/grants/${batch}/revoke`);
}

export async function getTrades(leagueId: number): Promise<{ trades: TradeRow[] }> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/trades`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

/** Lo stesso controllo del salvataggio, senza scrivere: serve a dire NO mentre
 *  si compone, invece che dopo aver premuto. */
export async function checkTrade(
  leagueId: number, body: TradeRequest,
): Promise<{
  ok: boolean; reason: string; remaining_a: number; remaining_b: number;
  /** Crediti che passano da A a B per pareggiare i contratti (negativo: da B ad A). */
  settlement: number;
}> {
  return auctionPost(`/leagues/${leagueId}/trades/check`, body as unknown as Record<string, unknown>);
}

export async function createTrade(
  leagueId: number, body: TradeRequest,
): Promise<{ trade_id: number; remaining_a: number | null; remaining_b: number | null }> {
  return auctionPost(`/leagues/${leagueId}/trades`, body as unknown as Record<string, unknown>);
}

export async function createAuction(leagueId: number, playerIds?: number[]) {
  return auctionPost(`/leagues/${leagueId}/auctions`, playerIds?.length ? { player_ids: playerIds } : {});
}

export interface AuctionPoolPlayer {
  player_id: number;
  name: string;
  full_name: string;
  role: string | null;
  /** Il club vero: distingue due omonimi, che in un listone da 660 capitano. */
  team: string | null;
  /** False for someone outside the drawn order — added to the listone after the
   *  auction started, or already gone round once. Still callable by name. */
  in_draw_order: boolean;
}

/** Everyone still callable in this auction. Fetched once and re-fetched only when
 *  the pool shrinks, so the banditore's search costs no request per keystroke. */
export async function getAuctionPool(auctionId: number): Promise<AuctionPoolPlayer[]> {
  const res = await fetch(`${baseUrl()}/auctions/${auctionId}/pool`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function getActiveAuction(leagueId: number): Promise<ActiveAuctionInfo> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/active-auction`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export type NominateMode = 'manual' | 'random' | 'random_role';

export async function nominatePlayer(
  auctionId: number,
  opts: { mode: NominateMode; player_id?: number; role?: ClassicRole },
) {
  return auctionPost(`/auctions/${auctionId}/nominate`, opts);
}

export async function assignPlayer(auctionId: number, playerId: number, teamId: number, price: number) {
  return auctionPost(`/auctions/${auctionId}/assign`, { player_id: playerId, team_id: teamId, price });
}

export async function placeBid(nominationId: number, amount: number, teamId?: number) {
  return auctionPost(`/nominations/${nominationId}/bid`, teamId ? { amount, team_id: teamId } : { amount });
}

export async function closeNomination(nominationId: number) {
  return auctionPost(`/nominations/${nominationId}/close`);
}

export async function cancelNomination(nominationId: number) {
  return auctionPost(`/nominations/${nominationId}/cancel`);
}

/** «Nessuno lo vuole»: chiude la chiamata senza venderlo e lo toglie dal giro.
 *  Diverso da `cancelNomination`, che invece lo rimette nel sacchetto. */
export async function markNominationUnsold(nominationId: number) {
  return auctionPost(`/nominations/${nominationId}/unsold`);
}

export async function revertNomination(nominationId: number) {
  return auctionPost(`/nominations/${nominationId}/revert`);
}

export async function voidBid(bidId: number) {
  return auctionPost(`/bids/${bidId}/void`);
}

export async function undoLastAuctionAction(auctionId: number) {
  return auctionPost(`/auctions/${auctionId}/undo-last`);
}

export async function closeAuctionSession(auctionId: number) {
  return auctionPost(`/auctions/${auctionId}/close-session`);
}

// --- Repair market (offer-based sessions on free agents) -------------------

export async function getMarketActive(leagueId: number): Promise<MarketActive> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/market/active`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function getMarketSessions(
  leagueId: number,
): Promise<{ sessions: MarketSessionHistory[] }> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/market/sessions`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function createMarketSession(
  leagueId: number,
  opts: {
    name?: string;
    credit_recovery_mode: MarketRecoveryMode;
    fixed_recovery_amount?: number;
    /** Apertura programmata; omessa = il mercato apre subito. */
    opens_at?: string | null;
    closes_at?: string | null;
  },
): Promise<{ session_id: number; opens_at: string }> {
  return auctionPost(`/leagues/${leagueId}/market/sessions/create`, opts);
}

export async function controlMarketSession(
  leagueId: number,
  sessionId: number,
  action: 'suspend' | 'resume' | 'close',
) {
  return auctionPost(`/leagues/${leagueId}/market/sessions/${sessionId}/${action}`);
}

export async function placeMarketOffer(
  leagueId: number,
  targetPlayerId: number,
  releasePlayerId: number,
  amount: number,
): Promise<{ offer_id: number; deadline_at: string }> {
  return auctionPost(`/leagues/${leagueId}/market/offers`, {
    target_player_id: targetPlayerId,
    release_player_id: releasePlayerId,
    amount,
  });
}

/** Cosa succede se l'admin toglie di mezzo questa offerta: non decide niente,
 *  guarda soltanto se sotto ne resta un'altra e in che stato. */
export async function getMarketDiscardPreview(
  leagueId: number,
  offerId: number,
  action: 'reject' | 'cancel',
): Promise<MarketDiscardPreview> {
  const res = await fetch(
    `${baseUrl()}/leagues/${leagueId}/market/offers/${offerId}/${action}`,
    { headers: { Accept: 'application/json', ...authHeaders() } },
  );
  return parseJsonOrThrow(res);
}

export async function adminMarketOffer(
  leagueId: number,
  offerId: number,
  action: 'accept' | 'reject' | 'cancel',
  /** Che fare dell'offerta che questa aveva superato. Obbligatoria (il server
   *  risponde 409 senza) quando l'offerta era un rilancio: e' una decisione
   *  dell'admin, non un default. */
  restorePrevious?: boolean,
) {
  return auctionPost(
    `/leagues/${leagueId}/market/offers/${offerId}/${action}`,
    restorePrevious === undefined ? {} : { restore_previous: restorePrevious },
  );
}

/** ws(s):// base for this deployment, with the DRF token appended as a query param. */
function socketUrl(path: string): string {
  const token = getToken() ?? '';
  // Strip the API suffix; in production baseUrl is RELATIVE ('/api/v1' -> ''), so
  // derive scheme+host from the current page (WebSocket needs an absolute URL).
  let httpBase = baseUrl().replace(/\/api\/v1$/, '');
  if (!/^https?:\/\//i.test(httpBase) && typeof window !== 'undefined') {
    httpBase = `${window.location.protocol}//${window.location.host}${httpBase}`;
  }
  const wsBase = httpBase.replace(/^http/i, 'ws');
  return `${wsBase}${path}?token=${encodeURIComponent(token)}`;
}

/** ws(s):// URL for the live auction room, carrying the DRF token in the query string. */
export function auctionSocketUrl(auctionId: number): string {
  return socketUrl(`/ws/auctions/${auctionId}/`);
}

/** ws(s):// URL for a league's matchday in progress: votes moving, matches ending. */
export function liveSocketUrl(leagueId: number): string {
  return socketUrl(`/ws/leagues/${leagueId}/live/`);
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

// `projection` chiede la SECONDA lettura di un turno in corso: «se la giornata
// finisse adesso?». Stesso endpoint e stesse regole di lega — è il motore vero a
// rispondere, non un conto rifatto qui — e non scrive niente: chiederla non
// cambia il punteggio che la pagina mostra con l'interruttore spento.
export async function getFixtureDetail(
  fixtureId: number | string,
  opts?: { projection?: boolean },
): Promise<SimFixtureDetail | ClassicFixtureDetail> {
  const qs = opts?.projection ? '?projection=1' : '';
  const res = await fetch(`${baseUrl()}/fixtures/${fixtureId}${qs}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

// Real championship (Serie A) calendar + results. Lo `scope` dice se lo si sta
// chiedendo da dentro una lega o da fuori: v. RealScope.
export async function getRealFixtures(
  scope: RealScope,
  matchday?: number,
): Promise<RealFixturesResponse> {
  const qs = matchday ? `?matchday=${matchday}` : '';
  const path =
    'league' in scope
      ? `/leagues/${scope.league}/real-fixtures`
      : `/real-seasons/${scope.season}/fixtures`;
  const res = await fetch(`${baseUrl()}${path}${qs}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

// Vote-relevant detail of a real match (pagella), shaped as a classic fixture.
export async function getNews(): Promise<NewsResponse> {
  const res = await fetch(`${baseUrl()}/news`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

/** «Ho letto fino a questa». L'id è quello della novità più recente CHE ABBIAMO
 *  MOSTRATO, non «adesso»: fra il caricamento della pagina e il click può uscirne
 *  un'altra, e il server non ha modo di sapere cosa c'era davanti a chi legge. */
export async function markNewsSeen(newsId: number): Promise<void> {
  await fetch(`${baseUrl()}/news/seen`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body: JSON.stringify({ id: newsId }),
  });
}

export async function getProbableLineups(
  matchId: number | string,
): Promise<ProbableLineups | null> {
  const res = await fetch(`${baseUrl()}/real-matches/${matchId}/probable-lineups`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  // Il 404 qui non e' un errore: e' «non ancora». Finche' il nostro motore non ha
  // storia e SofaScore non ha scritto, la cosa onesta e' non mostrare niente —
  // e chi chiama deve poterlo distinguere da una rete caduta.
  if (res.status === 404) return null;
  return parseJsonOrThrow(res);
}

export async function getRealMatchDetail(
  scope: RealScope,
  matchId: number | string,
): Promise<ClassicFixtureDetail> {
  const path =
    'league' in scope
      ? `/leagues/${scope.league}/real-matches/${matchId}`
      : `/real-seasons/${scope.season}/matches/${matchId}`;
  const res = await fetch(`${baseUrl()}${path}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

// Le voci che il pannello del voto non mostra, per un giocatore di una giornata.
// Chiamata a parte e non pezzo del tabellino: quello porta ventidue giocatori e si
// ricarica a ogni spinta live, questo elenco lo vuole solo chi apre "altre N voci".
export async function getVoteLedger(
  scope: RealScope,
  matchday: number,
  playerId: number,
): Promise<VoteLedger> {
  const path =
    'league' in scope
      ? `/leagues/${scope.league}/vote-ledger/${matchday}/${playerId}`
      : `/real-seasons/${scope.season}/vote-ledger/${matchday}/${playerId}`;
  const res = await fetch(`${baseUrl()}${path}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

// Full player pool of a championship (the "listone"). Chiesto per lega porta con
// sé i proprietari e i ruoli congelati; per stagione è il solo listone.
export async function getChampionshipPlayers(
  scope: RealScope,
): Promise<ChampionshipPlayersResponse> {
  const path =
    'league' in scope
      ? `/leagues/${scope.league}/championship-players`
      : `/real-seasons/${scope.season}/players`;
  const res = await fetch(`${baseUrl()}${path}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function getTeamLineup(
  leagueId: number,
  matchday?: number | null,
  competition?: number | null,
  teamId?: number | null,
  /** «now» chiede la rosa POSSEDUTA invece di quella schierabile in giornata:
   *  la pagina Rose vuole i contratti, la formazione chi puo' giocare. */
  rosterScope?: 'now' | null,
): Promise<TeamLineupContext> {
  const params = new URLSearchParams();
  if (matchday != null) params.set('matchday', String(matchday));
  if (competition != null) params.set('competition', String(competition));
  if (teamId != null) params.set('team_id', String(teamId));
  if (rosterScope) params.set('roster', rosterScope);
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

export async function concludeLeagueMatchday(
  leagueId: number,
  fantasyMatchdayId: number,
  force = false,
  lineupResolutions?: Record<string, 'forfait' | 'previous'>,
) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/matchdays/${fantasyMatchdayId}/conclude`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ force, lineup_resolutions: lineupResolutions ?? {} }),
  });
  return parseJsonOrThrow(res);
}

// Re-score a CONCLUDED classic matchday. use: 'current' = live rules (updates the
// snapshot); 'snapshot' = the frozen rules (e.g. after a vote fix).
/** Un premio che ha cambiato mano per effetto di un ricalcolo. */
export interface PrizeChange {
  prize_id: number;
  name: string;
  icon: string;
  competition_name: string;
  now: string[];
  before: string[];
}

export interface RecomputeResult {
  fantasy_matchday_id: number;
  recomputed_with: 'current' | 'snapshot';
  fixtures_scored: number;
  fixtures_total: number;
  /** Vuoto quasi sempre: una rettifica che sposta un trofeo e' rara e va detta. */
  prizes_changed?: PrizeChange[];
}

export async function recomputeLeagueMatchday(
  leagueId: number,
  fantasyMatchdayId: number,
  use: 'current' | 'snapshot' = 'current',
  force = false,
  lineupResolutions?: Record<string, 'forfait' | 'previous'>,
) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/matchdays/${fantasyMatchdayId}/recompute`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ use, force, lineup_resolutions: lineupResolutions ?? {} }),
  });
  return parseJsonOrThrow(res);
}

// Park a matchday as "awaiting" (a postponed match: the league moves on and this
// round is scored when the recovery is played), or bring it back to the ledger.
export async function setLeagueMatchdayAwaiting(
  leagueId: number,
  fantasyMatchdayId: number,
  awaiting = true,
  reason = '',
) {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/matchdays/${fantasyMatchdayId}/await`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ awaiting, reason }),
  });
  return parseJsonOrThrow(res);
}

export interface OfficeVoteMatch {
  match_id: number;
  home: string;
  away: string;
  status: string;
  kickoff: string | null;
  /** The vote this league has imposed on the match, or null if it is waiting. */
  office_vote: number | null;
  reason: string;
}

// The matches of a matchday with no final data, and this league's ruling on each.
export async function getMatchdayOfficeVotes(
  leagueId: number,
  fantasyMatchdayId: number,
): Promise<{ fantasy_matchday_id: number; matches: OfficeVoteMatch[] }> {
  const res = await fetch(
    `${baseUrl()}/leagues/${leagueId}/matchdays/${fantasyMatchdayId}/office-votes`,
    { headers: { Accept: 'application/json', ...authHeaders() } },
  );
  return parseJsonOrThrow(res);
}

export async function setMatchdayOfficeVotes(
  leagueId: number,
  fantasyMatchdayId: number,
  matchIds: number[],
  voto = 6,
  reason = '',
  remove = false,
): Promise<{ matches: OfficeVoteMatch[] }> {
  const res = await fetch(
    `${baseUrl()}/leagues/${leagueId}/matchdays/${fantasyMatchdayId}/office-votes`,
    {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ match_ids: matchIds, voto, reason, remove }),
    },
  );
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

/** Le rose della lega per la sala d'asta. Si rilegge quando `rosters_rev` dello
 *  stato cambia, non a ogni offerta: e' il motivo per cui sta fuori dallo stato. */
export async function getAuctionRosters(auctionId: number): Promise<AuctionRosters> {
  const res = await fetch(`${baseUrl()}/auctions/${auctionId}/rosters`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

// --- league decisions -------------------------------------------------------

export async function getLeagueDecisions(
  leagueId: number,
  status: 'open' | 'all' = 'open',
): Promise<LeagueDecisionsResponse> {
  const res = await fetch(`${baseUrl()}/leagues/${leagueId}/decisions?status=${status}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function voteLeagueDecision(
  leagueId: number,
  decisionId: number,
  option: string,
): Promise<LeagueDecision> {
  const res = await authedPost(`/leagues/${leagueId}/decisions/${decisionId}/vote`, { option });
  return parseJsonOrThrow(res);
}

export async function resolveLeagueDecision(
  leagueId: number,
  decisionId: number,
  option: string,
): Promise<LeagueDecision> {
  const res = await authedPost(`/leagues/${leagueId}/decisions/${decisionId}/resolve`, { option });
  return parseJsonOrThrow(res);
}

export async function consultLeagueDecision(
  leagueId: number,
  decisionId: number,
  open: boolean,
): Promise<LeagueDecision> {
  const res = await authedPost(`/leagues/${leagueId}/decisions/${decisionId}/consult`, { open });
  return parseJsonOrThrow(res);
}

export async function acceptAllLeagueDecisions(
  leagueId: number,
): Promise<{ resolved: number; blocked_reason: string | null }> {
  const res = await authedPost(`/leagues/${leagueId}/decisions/accept-all`, {});
  return parseJsonOrThrow(res);
}

/** L'admin apre una domanda su un ruolo che per noi era deciso. `created` è falso
 *  se la domanda c'era già: premere due volte non accumula code. */
export async function openRoleDecision(
  leagueId: number,
  playerId: number,
): Promise<LeagueDecision & { created: boolean }> {
  const res = await authedPost(`/leagues/${leagueId}/decisions/open`, { player_id: playerId });
  return parseJsonOrThrow(res);
}

// --- Web Push ---------------------------------------------------------------

/** Public: the VAPID key identifies this server to the push service, it does not
 *  authorise anything, and the browser needs it before it can even subscribe. */
export async function getPushConfig(): Promise<{ enabled: boolean; public_key: string }> {
  const res = await fetch(`${baseUrl()}/push/config`, {
    headers: { Accept: 'application/json' },
  });
  return parseJsonOrThrow(res);
}

export async function subscribePush(subscription: {
  endpoint: string;
  keys: Record<string, string>;
}): Promise<{ id: number }> {
  const res = await authedPost('/push/subscribe', { subscription });
  return parseJsonOrThrow(res);
}

export async function unsubscribePush(endpoint: string): Promise<{ removed: number }> {
  const res = await authedPost('/push/unsubscribe', { endpoint });
  return parseJsonOrThrow(res);
}

// --- Segnalazioni --------------------------------------------------------------

export type FeedbackKind = 'bug' | 'idea' | 'altro';

/** Manda una segnalazione. Il contesto (dove eri, che schermo) lo mette questa
 *  funzione, non chi la chiama: è il dato che serve a riprodurre un problema ed è
 *  quello che nessuno pensa a scrivere. Il browser lo legge il server dalla sua
 *  intestazione. */
export async function sendFeedback(kind: FeedbackKind, message: string): Promise<{ id: number }> {
  const res = await authedPost('/feedback', {
    kind,
    message,
    page: typeof window === 'undefined' ? '' : `${window.location.pathname}${window.location.search}`,
    viewport:
      typeof window === 'undefined' ? '' : `${window.innerWidth}x${window.innerHeight}`,
  });
  return parseJsonOrThrow(res);
}

// --- Manutenzione del sito (solo staff) --------------------------------------

/** Read the maintenance state: the verdict, what is waiting, recent agent passes.
 *
 *  Answers 403 for anyone who is not staff. The `is_staff` flag on the auth user
 *  only decides whether the menu OFFERS this page; the gate is here. */
export async function getMaintenanceState(): Promise<MaintenanceState> {
  const res = await fetch(`${baseUrl()}/maintenance/state/`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

export async function getMaintenanceProposal(id: number): Promise<ProposalDetail> {
  const res = await fetch(`${baseUrl()}/maintenance/proposals/${id}/`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  return parseJsonOrThrow(res);
}

/** Approving does NOT execute: the executor runs on its own timer, within five
 *  minutes. The response says so, so the page can be honest about it. */
export async function decideMaintenanceProposal(
  id: number,
  decision: 'approve' | 'reject',
  why?: string,
): Promise<DecideResponse> {
  const res = await authedPost(`/maintenance/proposals/${id}/decide/`, { decision, why });
  return parseJsonOrThrow(res);
}
