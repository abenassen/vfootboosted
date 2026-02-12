import type {
  LineupContextResponse,
  MatchDetailResponse,
  MatchListItem,
  SaveLineupRequest,
  SaveLineupResponse,
} from '../types/contracts';
import type { AuthResponse, AuthUser, LoginRequest, RegisterRequest } from '../types/auth';

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
