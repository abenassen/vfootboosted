import * as backendApi from './backend';
import * as mockApi from '../mock/api';
import type { AuthResponse, AuthUser, LoginRequest, RegisterRequest } from '../types/auth';
import type {
  CompetitionTemplateRequest,
  CreateLeagueRequest,
  JoinLeagueRequest,
} from '../types/league';

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
  getLeagues: typeof backendApi.getLeagues;
  createLeague: (req: CreateLeagueRequest) => ReturnType<typeof backendApi.createLeague>;
  joinLeague: (req: JoinLeagueRequest) => ReturnType<typeof backendApi.joinLeague>;
  getLeagueDetail: typeof backendApi.getLeagueDetail;
  updateMemberRole: typeof backendApi.updateMemberRole;
  setMarketStatus: typeof backendApi.setMarketStatus;
  getTeamRoster: typeof backendApi.getTeamRoster;
  addRosterPlayer: typeof backendApi.addRosterPlayer;
  removeRosterPlayer: typeof backendApi.removeRosterPlayer;
  bulkAssignRoster: typeof backendApi.bulkAssignRoster;
  importRosterCsv: typeof backendApi.importRosterCsv;
  createCompetitionTemplate: (leagueId: number, req: CompetitionTemplateRequest) => ReturnType<typeof backendApi.createCompetitionTemplate>;
  createAuction: typeof backendApi.createAuction;
  nominateNext: typeof backendApi.nominateNext;
  placeBid: typeof backendApi.placeBid;
  closeNomination: typeof backendApi.closeNomination;
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
export const getLeagues = typedImpl.getLeagues;
export const createLeague = typedImpl.createLeague;
export const joinLeague = typedImpl.joinLeague;
export const getLeagueDetail = typedImpl.getLeagueDetail;
export const updateMemberRole = typedImpl.updateMemberRole;
export const setMarketStatus = typedImpl.setMarketStatus;
export const getTeamRoster = typedImpl.getTeamRoster;
export const addRosterPlayer = typedImpl.addRosterPlayer;
export const removeRosterPlayer = typedImpl.removeRosterPlayer;
export const bulkAssignRoster = typedImpl.bulkAssignRoster;
export const importRosterCsv = typedImpl.importRosterCsv;
export const createCompetitionTemplate = typedImpl.createCompetitionTemplate;
export const createAuction = typedImpl.createAuction;
export const nominateNext = typedImpl.nominateNext;
export const placeBid = typedImpl.placeBid;
export const closeNomination = typedImpl.closeNomination;
