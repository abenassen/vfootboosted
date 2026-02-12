import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { getLeagues } from '../api';
import type { LeagueSummary } from '../types/league';

type LeagueContextValue = {
  leagues: LeagueSummary[];
  loading: boolean;
  selectedLeagueId: number | null;
  selectedLeague: LeagueSummary | null;
  setSelectedLeagueId: (leagueId: number | null) => void;
  refreshLeagues: () => Promise<void>;
};

const STORAGE_KEY = 'vfoot_selected_league_id';
const LeagueContext = createContext<LeagueContextValue | undefined>(undefined);

export function LeagueProvider({ children }: { children: React.ReactNode }) {
  const [leagues, setLeagues] = useState<LeagueSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedLeagueId, setSelectedLeagueIdState] = useState<number | null>(() => {
    if (typeof window === 'undefined') return null;
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  });

  const setSelectedLeagueId = useCallback((leagueId: number | null) => {
    setSelectedLeagueIdState(leagueId);
    if (typeof window === 'undefined') return;
    if (!leagueId) {
      window.localStorage.removeItem(STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(STORAGE_KEY, String(leagueId));
  }, []);

  const refreshLeagues = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getLeagues();
      setLeagues(data);
      if (!data.length) {
        setSelectedLeagueId(null);
        return;
      }

      const selectedStillValid = selectedLeagueId && data.some((l) => l.league_id === selectedLeagueId);
      if (!selectedStillValid) {
        setSelectedLeagueId(data[0].league_id);
      }
    } finally {
      setLoading(false);
    }
  }, [selectedLeagueId, setSelectedLeagueId]);

  useEffect(() => {
    void refreshLeagues().catch(() => {
      setLeagues([]);
      setLoading(false);
    });
  }, [refreshLeagues]);

  const selectedLeague = useMemo(
    () => leagues.find((l) => l.league_id === selectedLeagueId) ?? null,
    [leagues, selectedLeagueId]
  );

  const value = useMemo(
    () => ({
      leagues,
      loading,
      selectedLeagueId,
      selectedLeague,
      setSelectedLeagueId,
      refreshLeagues,
    }),
    [leagues, loading, refreshLeagues, selectedLeague, selectedLeagueId, setSelectedLeagueId]
  );

  return <LeagueContext.Provider value={value}>{children}</LeagueContext.Provider>;
}

export function useLeagueContext() {
  const ctx = useContext(LeagueContext);
  if (!ctx) throw new Error('useLeagueContext must be used within LeagueProvider');
  return ctx;
}
