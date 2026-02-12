import type { LineupContextResponse, MatchDetailResponse, MatchListItem, SaveLineupRequest, SaveLineupResponse } from '../types/contracts';
import type { AuthResponse, AuthUser, LoginRequest, RegisterRequest } from '../types/auth';
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
