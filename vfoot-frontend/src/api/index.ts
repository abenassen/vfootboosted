import * as backendApi from './backend';
import * as mockApi from '../mock/api';
import type {
  AuthResponse,
  AuthUser,
  LoginRequest,
  RegisterRequest,
  RegisterResponse,
} from '../types/auth';
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
  CompetitionWizardPlan,
  CompetitionWizardRequest,
  CompetitionWizardResult,
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

/** L'adesso del server, per i conti alla rovescia. Non passa dallo switch mock /
 *  backend: e' una proprieta' della connessione, non dei dati, e sotto il provider
 *  mock non c'e' nessun server da cui divergere — vale `Date.now()`. */
export const serverNow = backendApi.serverNow;

const impl = apiProvider === 'backend' ? backendApi : mockApi;

type ApiImpl = {
  hasStoredSession: () => boolean;
  register: (req: RegisterRequest) => Promise<RegisterResponse>;
  login: (req: LoginRequest) => Promise<AuthResponse>;
  getCurrentUser: () => Promise<AuthUser>;
  updateProfile: typeof backendApi.updateProfile;
  changePassword: typeof backendApi.changePassword;
  logout: () => Promise<void>;
  getLineupContext: typeof backendApi.getLineupContext;
  saveLineup: typeof backendApi.saveLineup;
  getMatches: typeof backendApi.getMatches;
  getMatchDetail: typeof backendApi.getMatchDetail;
  getLeagues: typeof backendApi.getLeagues;
  createLeague: (req: CreateLeagueRequest) => ReturnType<typeof backendApi.createLeague>;
  joinLeague: (req: JoinLeagueRequest) => ReturnType<typeof backendApi.joinLeague>;
  getLeagueInvite: typeof backendApi.getLeagueInvite;
  getLeagueDetail: typeof backendApi.getLeagueDetail;
  updateMyTeam: typeof backendApi.updateMyTeam;
  getLeagueActivity: typeof backendApi.getLeagueActivity;
  getManagerHonours: typeof backendApi.getManagerHonours;
  getManagerProfile: typeof backendApi.getManagerProfile;
  updateMemberRole: typeof backendApi.updateMemberRole;
  updateLeagueSettings: typeof backendApi.updateLeagueSettings;
  getTeamRoster: typeof backendApi.getTeamRoster;
  addRosterPlayer: typeof backendApi.addRosterPlayer;
  sellRosterPlayer: typeof backendApi.sellRosterPlayer;
  voidRosterSlot: typeof backendApi.voidRosterSlot;
  bulkAssignRoster: typeof backendApi.bulkAssignRoster;
  importRosterCsv: typeof backendApi.importRosterCsv;
  importRosterXlsx: typeof backendApi.importRosterXlsx;
  createCompetitionTemplate: (leagueId: number, req: CompetitionTemplateRequest) => ReturnType<typeof backendApi.createCompetitionTemplate>;
  createCompetitionGuided: (leagueId: number, req: CompetitionWizardRequest) => Promise<CompetitionWizardResult>;
  previewCompetitionPlan: (
    leagueId: number,
    req: Omit<CompetitionWizardRequest, 'name' | 'prizes' | 'points' | 'start_matchday' | 'end_matchday'>
  ) => Promise<CompetitionWizardPlan>;
  getCompetitions: (leagueId: number) => Promise<CompetitionItem[]>;
  updateCompetition: (competitionId: number, req: CompetitionUpdateRequest) => Promise<CompetitionItem>;
  deleteCompetition: (competitionId: number) => Promise<void>;
  scheduleCompetition: typeof backendApi.scheduleCompetition;
  previewCompetitionSchedule: typeof backendApi.previewCompetitionSchedule;
  getRealSeasons: typeof backendApi.getRealSeasons;
  setLeagueReferenceSeason: typeof backendApi.setLeagueReferenceSeason;
  addCompetitionRule: (competitionId: number, req: QualificationRuleCreateRequest) => Promise<unknown>;
  resolveCompetitionDependencies: (competitionId: number) => Promise<unknown>;
  getCompetitionStages: (competitionId: number) => Promise<CompetitionStageItem[]>;
  createCompetitionStage: (competitionId: number, req: CompetitionStageCreateRequest) => Promise<CompetitionStageItem>;
  updateCompetitionStage: (stageId: number, req: CompetitionStageUpdateRequest) => Promise<CompetitionStageItem>;
  deleteCompetitionStage: (stageId: number) => Promise<void>;
  addCompetitionStageRule: (stageId: number, req: CompetitionStageRuleCreateRequest) => Promise<CompetitionStageRuleCreateResult>;
  getCompetitionPrizes: (competitionId: number) => Promise<CompetitionPrizeItem[]>;
  createCompetitionPrize: (competitionId: number, req: CompetitionPrizeCreateRequest) => Promise<CompetitionPrizeItem>;
  deleteCompetitionPrize: (prizeId: number) => Promise<void>;
  buildDefaultCompetitionStages: (
    competitionId: number,
    allowRepechage?: boolean,
    randomSeed?: number,
    legs?: number
  ) => Promise<unknown>;
  resolveCompetitionStage: (stageId: number, randomSeed?: number) => Promise<unknown>;
  createAuction: typeof backendApi.createAuction;
  getActiveAuction: typeof backendApi.getActiveAuction;
  nominatePlayer: typeof backendApi.nominatePlayer;
  assignPlayer: typeof backendApi.assignPlayer;
  placeBid: typeof backendApi.placeBid;
  closeNomination: typeof backendApi.closeNomination;
  cancelNomination: typeof backendApi.cancelNomination;
  revertNomination: typeof backendApi.revertNomination;
  voidBid: typeof backendApi.voidBid;
  undoLastAuctionAction: typeof backendApi.undoLastAuctionAction;
  closeAuctionSession: typeof backendApi.closeAuctionSession;
  auctionSocketUrl: typeof backendApi.auctionSocketUrl;
  liveSocketUrl: typeof backendApi.liveSocketUrl;
  searchPlayers: (q: string, leagueId?: number, limit?: number) => Promise<PlayerSearchItem[]>;
  getAuctionState: (auctionId: number) => Promise<AuctionState>;
  getLeagueFixtures: (leagueId: number, competitionId?: number) => Promise<LeagueFixtureItem[]>;
  getLeagueStandings: typeof backendApi.getLeagueStandings;
  getCompetitionStructure: typeof backendApi.getCompetitionStructure;
  getFixtureDetail: typeof backendApi.getFixtureDetail;
  getRealFixtures: typeof backendApi.getRealFixtures;
  getRealMatchDetail: typeof backendApi.getRealMatchDetail;
  getChampionshipPlayers: typeof backendApi.getChampionshipPlayers;
  getTeamLineup: typeof backendApi.getTeamLineup;
  saveTeamLineup: typeof backendApi.saveTeamLineup;
  syncLeagueMatchdays: (leagueId: number) => Promise<{ fixtures_linked: number; matchdays_touched: number }>;
  getLeagueMatchdays: (leagueId: number) => Promise<LeagueMatchdayItem[]>;
  concludeLeagueMatchday: (leagueId: number, fantasyMatchdayId: number, force?: boolean, lineupResolutions?: Record<string, 'forfait' | 'previous'>) => Promise<unknown>;
  recomputeLeagueMatchday: (leagueId: number, fantasyMatchdayId: number, use?: 'current' | 'snapshot', force?: boolean, lineupResolutions?: Record<string, 'forfait' | 'previous'>) => Promise<unknown>;
  setLeagueMatchdayAwaiting: (leagueId: number, fantasyMatchdayId: number, awaiting?: boolean, reason?: string) => Promise<unknown>;
  getLeagueDecisions: typeof backendApi.getLeagueDecisions;
  voteLeagueDecision: typeof backendApi.voteLeagueDecision;
  resolveLeagueDecision: typeof backendApi.resolveLeagueDecision;
  consultLeagueDecision: typeof backendApi.consultLeagueDecision;
  acceptAllLeagueDecisions: typeof backendApi.acceptAllLeagueDecisions;
  getPushConfig: typeof backendApi.getPushConfig;
  subscribePush: typeof backendApi.subscribePush;
  unsubscribePush: typeof backendApi.unsubscribePush;
};

const typedImpl = impl as ApiImpl;

export const hasStoredSession = typedImpl.hasStoredSession;
export const register = typedImpl.register;
export const login = typedImpl.login;
export const getCurrentUser = typedImpl.getCurrentUser;
export const updateProfile = typedImpl.updateProfile;
export const changePassword = typedImpl.changePassword;
export const logout = typedImpl.logout;

export const getLineupContext = typedImpl.getLineupContext;
export const saveLineup = typedImpl.saveLineup;
export const getMatches = typedImpl.getMatches;
export const getMatchDetail = typedImpl.getMatchDetail;
export const getLeagues = typedImpl.getLeagues;
export const createLeague = typedImpl.createLeague;
export const joinLeague = typedImpl.joinLeague;
export const getLeagueInvite = typedImpl.getLeagueInvite;
export const getLeagueDetail = typedImpl.getLeagueDetail;
export const updateMyTeam = typedImpl.updateMyTeam;
export const getLeagueActivity = typedImpl.getLeagueActivity;
export const getManagerHonours = typedImpl.getManagerHonours;
export const getManagerProfile = typedImpl.getManagerProfile;
export const updateMemberRole = typedImpl.updateMemberRole;
export const updateLeagueSettings = typedImpl.updateLeagueSettings;
export const getTeamRoster = typedImpl.getTeamRoster;
export const addRosterPlayer = typedImpl.addRosterPlayer;
export const sellRosterPlayer = typedImpl.sellRosterPlayer;
export const voidRosterSlot = typedImpl.voidRosterSlot;
export const bulkAssignRoster = typedImpl.bulkAssignRoster;
export const importRosterCsv = typedImpl.importRosterCsv;
export const importRosterXlsx = typedImpl.importRosterXlsx;
export const createCompetitionTemplate = typedImpl.createCompetitionTemplate;
export const createCompetitionGuided = typedImpl.createCompetitionGuided;
export const previewCompetitionPlan = typedImpl.previewCompetitionPlan;
export const getCompetitions = typedImpl.getCompetitions;
export const updateCompetition = typedImpl.updateCompetition;
export const deleteCompetition = typedImpl.deleteCompetition;
export const scheduleCompetition = typedImpl.scheduleCompetition;
export const previewCompetitionSchedule = typedImpl.previewCompetitionSchedule;
export const getRealSeasons = typedImpl.getRealSeasons;
export const setLeagueReferenceSeason = typedImpl.setLeagueReferenceSeason;
export const addCompetitionRule = typedImpl.addCompetitionRule;
export const resolveCompetitionDependencies = typedImpl.resolveCompetitionDependencies;
export const getCompetitionStages = typedImpl.getCompetitionStages;
export const createCompetitionStage = typedImpl.createCompetitionStage;
export const updateCompetitionStage = typedImpl.updateCompetitionStage;
export const deleteCompetitionStage = typedImpl.deleteCompetitionStage;
export const addCompetitionStageRule = typedImpl.addCompetitionStageRule;
export const getCompetitionPrizes = typedImpl.getCompetitionPrizes;
export const createCompetitionPrize = typedImpl.createCompetitionPrize;
export const deleteCompetitionPrize = typedImpl.deleteCompetitionPrize;
export const buildDefaultCompetitionStages = typedImpl.buildDefaultCompetitionStages;
export const resolveCompetitionStage = typedImpl.resolveCompetitionStage;
export const createAuction = typedImpl.createAuction;
export const getActiveAuction = typedImpl.getActiveAuction;
export const nominatePlayer = typedImpl.nominatePlayer;
export const assignPlayer = typedImpl.assignPlayer;
export const placeBid = typedImpl.placeBid;
export const closeNomination = typedImpl.closeNomination;
export const cancelNomination = typedImpl.cancelNomination;
export const revertNomination = typedImpl.revertNomination;
export const voidBid = typedImpl.voidBid;
export const undoLastAuctionAction = typedImpl.undoLastAuctionAction;
export const closeAuctionSession = typedImpl.closeAuctionSession;
export const auctionSocketUrl = typedImpl.auctionSocketUrl;
export const liveSocketUrl = typedImpl.liveSocketUrl;
export const searchPlayers = typedImpl.searchPlayers;
export const getAuctionState = typedImpl.getAuctionState;
export const getLeagueFixtures = typedImpl.getLeagueFixtures;
export const getLeagueStandings = typedImpl.getLeagueStandings;
export const getCompetitionStructure = typedImpl.getCompetitionStructure;
export const getFixtureDetail = typedImpl.getFixtureDetail;
export const getRealFixtures = typedImpl.getRealFixtures;
export const getRealMatchDetail = typedImpl.getRealMatchDetail;
export const getChampionshipPlayers = typedImpl.getChampionshipPlayers;
export const getTeamLineup = typedImpl.getTeamLineup;
export const saveTeamLineup = typedImpl.saveTeamLineup;
export const syncLeagueMatchdays = typedImpl.syncLeagueMatchdays;
export const getLeagueMatchdays = typedImpl.getLeagueMatchdays;
export const concludeLeagueMatchday = typedImpl.concludeLeagueMatchday;
export const recomputeLeagueMatchday = typedImpl.recomputeLeagueMatchday;
export const setLeagueMatchdayAwaiting = typedImpl.setLeagueMatchdayAwaiting;
export const getLeagueDecisions = typedImpl.getLeagueDecisions;
export const voteLeagueDecision = typedImpl.voteLeagueDecision;
export const resolveLeagueDecision = typedImpl.resolveLeagueDecision;
export const consultLeagueDecision = typedImpl.consultLeagueDecision;
export const acceptAllLeagueDecisions = typedImpl.acceptAllLeagueDecisions;
export const getPushConfig = typedImpl.getPushConfig;
export const subscribePush = typedImpl.subscribePush;
export const unsubscribePush = typedImpl.unsubscribePush;
