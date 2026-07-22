import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { getCompetitions } from '../api';
import type { CompetitionItem } from '../types/league';
import { useLeagueContext } from './LeagueContext';

// The CURRENT competition within the active league. Mirrors LeagueContext: the
// menu pages (Partite, Classifica, …) read this so they specialise to the selected
// competition. Resets/defaults when the league changes; remembered per league.
type CompetitionContextValue = {
  competitions: CompetitionItem[];
  loading: boolean;
  selectedCompetitionId: number | null;
  selectedCompetition: CompetitionItem | null;
  setSelectedCompetitionId: (id: number | null) => void;
  refreshCompetitions: () => Promise<void>;
};

const CompetitionContext = createContext<CompetitionContextValue | undefined>(undefined);
const storageKey = (leagueId: number) => `vfoot_selected_competition_${leagueId}`;

export function CompetitionProvider({ children }: { children: React.ReactNode }) {
  const { selectedLeagueId } = useLeagueContext();
  const [competitions, setCompetitions] = useState<CompetitionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedCompetitionId, setSelectedIdState] = useState<number | null>(null);

  const setSelectedCompetitionId = useCallback(
    (id: number | null) => {
      setSelectedIdState(id);
      if (typeof window === 'undefined' || !selectedLeagueId) return;
      if (id) window.localStorage.setItem(storageKey(selectedLeagueId), String(id));
      else window.localStorage.removeItem(storageKey(selectedLeagueId));
    },
    [selectedLeagueId],
  );

  const refreshCompetitions = useCallback(async () => {
    if (!selectedLeagueId) {
      setCompetitions([]);
      setSelectedIdState(null);
      return;
    }
    setLoading(true);
    try {
      const data = await getCompetitions(selectedLeagueId);
      setCompetitions(data);
      // default: the remembered competition for this league if still present, else
      // the first one.
      const remembered =
        typeof window !== 'undefined' ? Number(window.localStorage.getItem(storageKey(selectedLeagueId))) : NaN;
      const valid = data.find((c) => c.competition_id === remembered) ?? data[0] ?? null;
      setSelectedIdState(valid ? valid.competition_id : null);
    } catch {
      setCompetitions([]);
      setSelectedIdState(null);
    } finally {
      setLoading(false);
    }
  }, [selectedLeagueId]);

  useEffect(() => {
    void refreshCompetitions();
  }, [refreshCompetitions]);

  const selectedCompetition = useMemo(
    () => competitions.find((c) => c.competition_id === selectedCompetitionId) ?? null,
    [competitions, selectedCompetitionId],
  );

  const value = useMemo(
    () => ({
      competitions,
      loading,
      selectedCompetitionId,
      selectedCompetition,
      setSelectedCompetitionId,
      refreshCompetitions,
    }),
    [competitions, loading, selectedCompetitionId, selectedCompetition, setSelectedCompetitionId, refreshCompetitions],
  );

  return <CompetitionContext.Provider value={value}>{children}</CompetitionContext.Provider>;
}

export function useCompetitionContext() {
  const ctx = useContext(CompetitionContext);
  if (!ctx) throw new Error('useCompetitionContext must be used within CompetitionProvider');
  return ctx;
}
