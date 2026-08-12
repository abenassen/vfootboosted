import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { getRealSeasons } from '../api';
import { useLeagueContext } from './LeagueContext';
import type { RealSeasonItem } from '../types/league';
import type { RealScope } from '../types/realChampionship';

/** QUALE CAMPIONATO VERO SI STA GUARDANDO, e da che parte lo si chiede.
 *
 *  Calendario, pagelle e listone della Serie A esistono a prescindere dalle
 *  leghe: sono la stagione. Dentro una lega si chiedono per lega, perché la lega
 *  aggiunge due cose sue — chi possiede chi nel listone, e i ruoli che ha
 *  congelato — e la stagione la sceglie lei, una volta per sempre, alla nascita.
 *
 *  Fuori da ogni lega si chiedono per stagione, ed è il caso di chi si è appena
 *  iscritto: prima di questo contesto le stesse tre pagine rispondevano
 *  «Seleziona una lega», cioè il sito non aveva niente da mostrare a chi non
 *  aveva ancora fatto niente.
 *
 *  La scelta è fra i campionati IN CORSO (`?open=1`): un'edizione conclusa non è
 *  «il campionato», è l'archivio. Oggi ce n'è uno solo e il selettore non si vede
 *  nemmeno — ma il modello a più campionati c'è già nei dati, e questa è la sola
 *  cosa che serve perché il giorno che ce ne siano due la pagina lo dica.
 */
type ChampionshipContextValue = {
  /** Come chiedere il campionato al server. Null finché non si sa ancora. */
  scope: RealScope | null;
  /** Le edizioni in corso fra cui si può scegliere. Vuoto dentro una lega. */
  seasons: RealSeasonItem[];
  /** L'edizione scelta, quando si guarda senza lega. */
  season: RealSeasonItem | null;
  setSeasonId: (seasonId: number) => void;
  /** Si sta guardando da fuori: niente proprietari, niente ruoli di lega. */
  browsing: boolean;
  loading: boolean;
};

const STORAGE_KEY = 'vfoot_browse_season_id';
const ChampionshipContext = createContext<ChampionshipContextValue | undefined>(undefined);

export function ChampionshipProvider({ children }: { children: React.ReactNode }) {
  const { selectedLeagueId, loading: leaguesLoading } = useLeagueContext();
  const [seasons, setSeasons] = useState<RealSeasonItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [seasonId, setSeasonIdState] = useState<number | null>(() => {
    if (typeof window === 'undefined') return null;
    const n = Number(window.localStorage.getItem(STORAGE_KEY));
    return Number.isFinite(n) && n > 0 ? n : null;
  });

  const browsing = !leaguesLoading && !selectedLeagueId;

  const setSeasonId = useCallback((id: number) => {
    setSeasonIdState(id);
    if (typeof window !== 'undefined') window.localStorage.setItem(STORAGE_KEY, String(id));
  }, []);

  // L'elenco si carica SOLO quando serve davvero, cioè quando non c'è una lega:
  // chi ne ha una prende la stagione dalla lega e questa chiamata sarebbe una
  // domanda in più su ogni pagina, per una risposta che non guarderebbe nessuno.
  useEffect(() => {
    if (!browsing) {
      setSeasons([]);
      return;
    }
    let alive = true;
    setLoading(true);
    void getRealSeasons(true)
      .then((list) => {
        if (!alive) return;
        setSeasons(list);
        // La scelta salvata vale finché quel campionato è ancora in corso: a
        // stagione finita non si può restare fermi lì, o la pagina si aprirebbe
        // per sempre sull'anno scorso.
        setSeasonIdState((cur) =>
          cur && list.some((s) => s.id === cur) ? cur : (list[0]?.id ?? null),
        );
      })
      .catch(() => {
        if (alive) setSeasons([]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [browsing]);

  const season = useMemo(
    () => seasons.find((s) => s.id === seasonId) ?? null,
    [seasons, seasonId],
  );

  const scope = useMemo<RealScope | null>(() => {
    if (selectedLeagueId) return { league: selectedLeagueId };
    if (season) return { season: season.id };
    return null;
  }, [selectedLeagueId, season]);

  const value = useMemo(
    () => ({ scope, seasons, season, setSeasonId, browsing, loading: leaguesLoading || loading }),
    [scope, seasons, season, setSeasonId, browsing, leaguesLoading, loading],
  );

  return <ChampionshipContext.Provider value={value}>{children}</ChampionshipContext.Provider>;
}

export function useChampionship() {
  const ctx = useContext(ChampionshipContext);
  if (!ctx) throw new Error('useChampionship must be used within ChampionshipProvider');
  return ctx;
}
