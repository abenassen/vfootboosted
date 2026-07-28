// Repair market (offer-based sessions on free agents, classic mode).

export type MarketRecoveryMode = 'fixed' | 'frac30' | 'frac50' | 'frac75';
export type MarketSessionStatus = 'open' | 'suspended' | 'closed';
export type MarketOfferStatus =
  | 'leading'
  | 'outbid'
  | 'accepted'
  | 'settled'
  | 'rejected'
  | 'cancelled';

export interface MarketSessionInfo {
  id: number;
  name: string;
  status: MarketSessionStatus;
  opens_at: string | null;
  closes_at: string | null;
  credit_recovery_mode: MarketRecoveryMode;
  fixed_recovery_amount: number;
}

export interface MarketLeading {
  offer_id: number;
  amount: number;
  team_id: number;
  team_name: string | null;
  deadline_at: string | null;
  mine: boolean;
}

export interface MarketFreeAgent {
  player_id: number;
  name: string | null;
  role: string | null;
  locked: boolean;
  leading: MarketLeading | null;
}

export interface MarketRosterPlayer {
  player_id: number;
  name: string | null;
  role: string | null;
  price: number;
  recovery: number;
}

export interface MarketBudget {
  remaining: number;
  reserved: number;
  available: number;
}

export interface MarketOfferRow {
  offer_id: number;
  team_id: number;
  team_name?: string | null;
  target_player_id: number;
  target_name: string | null;
  release_player_id: number;
  release_name: string | null;
  amount: number;
  recovery: number;
  role: string;
  status: MarketOfferStatus;
  deadline_at: string | null;
  created_at: string;
}

export interface MarketActive {
  session: MarketSessionInfo | null;
  is_admin: boolean;
  mode: string;
  my_team_id: number | null;
  my_budget?: MarketBudget | null;
  free_agents?: MarketFreeAgent[];
  my_roster?: MarketRosterPlayer[];
  my_offers?: MarketOfferRow[];
  admin_queue?: MarketOfferRow[];
}

export interface MarketSessionHistory extends MarketSessionInfo {
  closed_at: string | null;
  offers: MarketOfferRow[];
}
