import * as backendApi from './backend';
import * as mockApi from '../mock/api';
import type { AuthResponse, AuthUser, LoginRequest, RegisterRequest } from '../types/auth';
import type {
  AuctionState,
  CompetitionItem,
  CompetitionPrizeCreateRequest,
  CompetitionPrizeItem,
  CompetitionScheduleApplyResult,
  CompetitionSchedulePreview,
  CompetitionStageCreateRequest,
  CompetitionStageRuleCreateResult,
  CompetitionStageUpdateRequest,
  CompetitionStageRuleCreateRequest,
  CompetitionStageItem,
  CompetitionUpdateRequest,
  CompetitionTemplateRequest,
  CreateLeagueRequest,
  JoinLeagueRequest,
  LeagueFixtureItem,
  LeagueMatchdayItem,
  PlayerSearchItem,
  QualificationRuleCreateRequest,
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
  getCompetitions: (leagueId: number) => Promise<CompetitionItem[]>;
  updateCompetition: (competitionId: number, req: CompetitionUpdateRequest) => Promise<CompetitionItem>;
  scheduleCompetition: (
    competitionId: number,
    payload?: { starts_at?: string | null; ends_at?: string | null; round_mapping?: Record<string, number> }
  ) => Promise<CompetitionScheduleApplyResult>;
  previewCompetitionSchedule: (
    competitionId: number,
    payload?: { starts_at?: string | null; ends_at?: string | null }
  ) => Promise<CompetitionSchedulePreview>;
  addCompetitionRule: (competitionId: number, req: QualificationRuleCreateRequest) => Promise<unknown>;
  resolveCompetitionDependencies: (competitionId: number) => Promise<unknown>;
  getCompetitionStages: (competitionId: number) => Promise<CompetitionStageItem[]>;
  createCompetitionStage: (competitionId: number, req: CompetitionStageCreateRequest) => Promise<CompetitionStageItem>;
  updateCompetitionStage: (stageId: number, req: CompetitionStageUpdateRequest) => Promise<CompetitionStageItem>;
  addCompetitionStageRule: (stageId: number, req: CompetitionStageRuleCreateRequest) => Promise<CompetitionStageRuleCreateResult>;
  getCompetitionPrizes: (competitionId: number) => Promise<CompetitionPrizeItem[]>;
  createCompetitionPrize: (competitionId: number, req: CompetitionPrizeCreateRequest) => Promise<CompetitionPrizeItem>;
  deleteCompetitionPrize: (prizeId: number) => Promise<void>;
  buildDefaultCompetitionStages: (competitionId: number, allowRepechage?: boolean, randomSeed?: number) => Promise<unknown>;
  resolveCompetitionStage: (stageId: number, randomSeed?: number) => Promise<unknown>;
  createAuction: typeof backendApi.createAuction;
  nominateNext: typeof backendApi.nominateNext;
  placeBid: typeof backendApi.placeBid;
  closeNomination: typeof backendApi.closeNomination;
  searchPlayers: (q: string, leagueId?: number, limit?: number) => Promise<PlayerSearchItem[]>;
  getAuctionState: (auctionId: number) => Promise<AuctionState>;
  getLeagueFixtures: (leagueId: number, competitionId?: number) => Promise<LeagueFixtureItem[]>;
  syncLeagueMatchdays: (leagueId: number) => Promise<{ fixtures_linked: number; matchdays_touched: number }>;
  getLeagueMatchdays: (leagueId: number) => Promise<LeagueMatchdayItem[]>;
  concludeLeagueMatchday: (leagueId: number, fantasyMatchdayId: number, force?: boolean) => Promise<unknown>;
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
export const getCompetitions = typedImpl.getCompetitions;
export const updateCompetition = typedImpl.updateCompetition;
export const scheduleCompetition = typedImpl.scheduleCompetition;
export const previewCompetitionSchedule = typedImpl.previewCompetitionSchedule;
export const addCompetitionRule = typedImpl.addCompetitionRule;
export const resolveCompetitionDependencies = typedImpl.resolveCompetitionDependencies;
export const getCompetitionStages = typedImpl.getCompetitionStages;
export const createCompetitionStage = typedImpl.createCompetitionStage;
export const updateCompetitionStage = typedImpl.updateCompetitionStage;
export const addCompetitionStageRule = typedImpl.addCompetitionStageRule;
export const getCompetitionPrizes = typedImpl.getCompetitionPrizes;
export const createCompetitionPrize = typedImpl.createCompetitionPrize;
export const deleteCompetitionPrize = typedImpl.deleteCompetitionPrize;
export const buildDefaultCompetitionStages = typedImpl.buildDefaultCompetitionStages;
export const resolveCompetitionStage = typedImpl.resolveCompetitionStage;
export const createAuction = typedImpl.createAuction;
export const nominateNext = typedImpl.nominateNext;
export const placeBid = typedImpl.placeBid;
export const closeNomination = typedImpl.closeNomination;
export const searchPlayers = typedImpl.searchPlayers;
export const getAuctionState = typedImpl.getAuctionState;
export const getLeagueFixtures = typedImpl.getLeagueFixtures;
export const syncLeagueMatchdays = typedImpl.syncLeagueMatchdays;
export const getLeagueMatchdays = typedImpl.getLeagueMatchdays;
export const concludeLeagueMatchday = typedImpl.concludeLeagueMatchday;
