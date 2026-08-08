import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
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

/** Lascia che un LINK scelga la competizione, con `?competition=<id>`.
 *
 *  Le pagine del menu (Partite, Classifica) mostrano la competizione SELEZIONATA,
 *  e finché quella si cambiava solo dallo switcher ogni scorciatoia che ci
 *  arrivava mostrava l'ultima guardata: da tre blocchi diversi della home si
 *  finiva tutti e tre sullo stesso calendario, quello del campionato, e il link
 *  sembrava rotto quando invece era la pagina a non sapere da dove si veniva.
 *
 *  Nell'URL e non in un `onClick`, perché un indirizzo deve portare dove dice:
 *  ricaricare la pagina, aprirla in una scheda nuova o mandarla a un altro
 *  fantallenatore deve mostrare la stessa cosa. È anche la convenzione che la
 *  formazione usa già (`/squad/formation?competition=…`).
 *
 *  Il parametro si CONSUMA: la selezione ormai è nel contesto e vale anche per le
 *  altre pagine, e lasciarlo nell'indirizzo avrebbe reso lo switcher inefficace
 *  finché non si cambiava pagina — si sceglieva un'altra competizione e questo
 *  effetto la riportava indietro.
 */
export function useCompetitionFromQuery() {
  const { selectedCompetitionId, setSelectedCompetitionId, competitions } = useCompetitionContext();
  const [params, setParams] = useSearchParams();
  const wanted = Number(params.get('competition'));

  useEffect(() => {
    if (!Number.isFinite(wanted) || !wanted) return;
    // Solo quando è una competizione DI QUESTA lega: le competizioni arrivano
    // dopo il primo render, e agire prima avrebbe selezionato un id che il
    // contesto avrebbe poi scartato, lasciando la pagina vuota.
    if (!competitions.some((c) => c.competition_id === wanted)) return;
    if (wanted !== selectedCompetitionId) setSelectedCompetitionId(wanted);
    const next = new URLSearchParams(params);
    next.delete('competition');
    setParams(next, { replace: true });
  }, [wanted, competitions, selectedCompetitionId, setSelectedCompetitionId, params, setParams]);
}
