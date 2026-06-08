// Client for the read-only historical Vfoot league dry-run simulation.
//
// The simulation is always served by the Django backend artifact, independent
// of the mock/backend product switch, so this module talks to the backend
// directly (mirroring api/backend.ts base-url + auth conventions).

import type { SimFixtureDetail, SimFixtureSummary, SimOverview } from '../types/simulation';

const DEFAULT_BASE_URL = 'http://localhost:8000/api/v1';
const TOKEN_STORAGE_KEY = 'vfoot_auth_token';

function baseUrl(): string {
  const v = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
  const url = v && v.length > 0 ? v : DEFAULT_BASE_URL;
  return url.replace(/\/+$/, '');
}

function authHeaders(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const token = window.localStorage.getItem(TOKEN_STORAGE_KEY);
  return token ? { Authorization: `Token ${token}` } : {};
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${baseUrl()}${path}`, {
    headers: { Accept: 'application/json', ...authHeaders() },
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === 'string') detail = body.detail;
    } catch {
      // ignore parse failure, keep generic message
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const ROOT = '/simulations/historical-vfoot/latest';

export function getSimulationOverview(): Promise<SimOverview> {
  return getJson<SimOverview>(ROOT);
}

export function getSimulationFixtures(): Promise<SimFixtureSummary[]> {
  return getJson<SimFixtureSummary[]>(`${ROOT}/fixtures`);
}

export function getSimulationFixtureDetail(fixtureId: number): Promise<SimFixtureDetail> {
  return getJson<SimFixtureDetail>(`${ROOT}/fixtures/${fixtureId}`);
}
