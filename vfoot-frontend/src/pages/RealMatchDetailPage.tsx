import { useCallback, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getRealMatchDetail } from '../api';
import { Card } from '../components/ui';
import { ClassicMatchDetail } from '../components/match/ClassicMatchDetail';
import { useLeagueContext } from '../league/LeagueContext';
import { useLiveSocket } from '../hooks/useNudgeSocket';
import { useAsync } from '../utils/useAsync';

// Vote-relevant detail of a REAL Serie A match: the per-player pagella
// (voto puro + bonus/malus = fantavoto) for both squads, rendered with the same
// ClassicMatchDetail component used by classic fantasy fixtures. (Aura zone
// breakdown enrichment is a planned follow-up.)
export default function RealMatchDetailPage() {
  const { matchId } = useParams();
  const { selectedLeagueId } = useLeagueContext();
  // Bumped by the socket; the only reason this page ever re-fetches on its own.
  const [tick, setTick] = useState(0);
  const { data, loading, error } = useAsync(
    () =>
      selectedLeagueId && matchId
        ? getRealMatchDetail(selectedLeagueId, matchId)
        : Promise.reject(new Error('Lega o partita non selezionata')),
    [selectedLeagueId, matchId, tick],
  );
  // The tick nudges every league following this real match on each live import
  // (realdata/management/commands/tick.py), so the votes of a match being played
  // arrive here without a reload — which is the only way to read them while they
  // still mean something. The nudge carries no data: the same REST call that
  // built the page rebuilds it, so the pushed path and the reload path are one.
  useLiveSocket(selectedLeagueId ?? null, useCallback(() => setTick((n) => n + 1), []));

  // `loading && !data`, not `loading`: a re-fetch triggered by the socket must not
  // replace a page you are reading with a spinner.
  if (loading && !data) return <div className="text-sm text-ink-faint">Caricamento partita…</div>;
  // Nothing to show and no longer loading: either the fetch failed or the match
  // has no detail. A LATER failure keeps the page that is already up — a live
  // re-fetch that trips must not throw away the tabellino you were reading.
  if (!data) {
    return (
      <Card className="p-4 text-sm text-bad">
        Errore nel caricamento della partita: {error?.message ?? 'sconosciuto'}
      </Card>
    );
  }
  return <ClassicMatchDetail fixture={data} backTo="/serie-a" backLabel="← Serie A" variant="real" />;
}
