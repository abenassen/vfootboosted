import * as backendApi from './backend';
import * as mockApi from '../mock/api';
import type { AuthResponse, AuthUser, LoginRequest, RegisterRequest } from '../types/auth';

export type ApiProvider = 'mock' | 'backend';

function fromQueryParam(): ApiProvider | null {
  if (typeof window === 'undefined') return null;
  const value = new URLSearchParams(window.location.search).get('api');
  if (value === 'mock' || value === 'backend') return value;
  return null;
}

function fromEnv(): ApiProvider {
  const value = (import.meta.env.VITE_API_PROVIDER as string | undefined)?.toLowerCase();
  if (value === 'backend') return 'backend';
  return 'mock';
}

export const apiProvider: ApiProvider = fromQueryParam() ?? fromEnv();

const impl = apiProvider === 'backend' ? backendApi : mockApi;

type ApiImpl = {
  hasStoredSession: () => boolean;
  register: (req: RegisterRequest) => Promise<AuthResponse>;
  login: (req: LoginRequest) => Promise<AuthResponse>;
  getCurrentUser: () => Promise<AuthUser>;
  logout: () => Promise<void>;
  getLineupContext: typeof backendApi.getLineupContext;
  saveLineup: typeof backendApi.saveLineup;
  getMatches: typeof backendApi.getMatches;
  getMatchDetail: typeof backendApi.getMatchDetail;
};

const typedImpl = impl as ApiImpl;

export const hasStoredSession = typedImpl.hasStoredSession;
export const register = typedImpl.register;
export const login = typedImpl.login;
export const getCurrentUser = typedImpl.getCurrentUser;
export const logout = typedImpl.logout;

export const getLineupContext = typedImpl.getLineupContext;
export const saveLineup = typedImpl.saveLineup;
export const getMatches = typedImpl.getMatches;
export const getMatchDetail = typedImpl.getMatchDetail;
