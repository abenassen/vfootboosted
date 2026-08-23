import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getFixtureDetail, getVoteLedger } from '../api';
import { Card } from '../components/ui';
import { MatchDetail } from '../components/match/MatchDetail';
import { ClassicMatchDetail } from '../components/match/ClassicMatchDetail';
import { useAuth } from '../auth/AuthContext';
import { useLeagueContext } from '../league/LeagueContext';
import { useCompetitionContext } from '../league/CompetitionContext';
import { useLiveSocket } from '../hooks/useNudgeSocket';
import { useAsync } from '../utils/useAsync';
import type { ClassicFixtureDetail } from '../types/classic';
import type { SimFixtureDetail } from '../types/simulation';

export default function LeagueMatchDetailPage() {
  const { matchId } = useParams();
  const { selectedLeagueId } = useLeagueContext();
  const { user } = useAuth();
  // Bumped by the socket; the only reason this page ever re-fetches on its own.
  const [tick, setTick] = useState(0);
  const { data, loading, error } = useAsync(
    () => getFixtureDetail(matchId ?? ''),
    [matchId, tick],
  );
  // The nudge carries no data: it says "something moved", and the same REST call
  // that built this page rebuilds it. One code path, whether you reloaded or the
  // server told you to.
  useLiveSocket(selectedLeagueId ?? null, useCallback(() => setTick((n) => n + 1), []));

  // Bring the shell onto THIS fixture's competition. You can reach a match from the
  // home page, which lists every competition together, so the selection made
  // elsewhere has nothing to do with what you just opened: the banner announced one
  // competition while the page showed a tie from another, and the side menu offered
  // the wrong calendar to go back to. The fixture knows which one it is; nothing was
  // telling the shell.
  const { selectedCompetitionId, setSelectedCompetitionId } = useCompetitionContext();
  const fixtureCompetitionId =
    data && 'competition_id' in data ? (data as ClassicFixtureDetail).competition_id : null;
  useEffect(() => {
    if (fixtureCompetitionId && fixtureCompetitionId !== selectedCompetitionId) {
      setSelectedCompetitionId(fixtureCompetitionId);
    }
  }, [fixtureCompetitionId, selectedCompetitionId, setSelectedCompetitionId]);

  // Le voci che il pannello del voto non mostra. Si chiedono per LEGA: la giornata
  // ce l'ha il referto, la stagione la sa la lega, e il permesso di leggerle è
  // l'appartenenza alla lega — come per ogni altra cosa di questa pagina.
  const classicData = data && 'mode' in data && data.mode === 'classic'
    ? (data as ClassicFixtureDetail)
    : null;
  const md = classicData?.real_matchday ?? null;
  const loadLedger = useMemo(
    () =>
      selectedLeagueId && md != null
        ? (playerId: number) => getVoteLedger({ league: selectedLeagueId }, md, playerId)
        : undefined,
    [selectedLeagueId, md],
  );

  if (loading && !data) return <div className="text-sm text-ink-faint">Caricamento partita…</div>;
  if ((error && !data) || (!loading && !data)) {
    // A fixture whose round has not kicked off has no detail, and the API says so
    // with a 404: that is a normal state, not a failure, and showing it in red
    // made a match simply not played yet look like a broken page. The calendar no
    // longer links these, so getting here means a bookmark or a typed URL.
    const notPlayedYet = /no rich detail/i.test(error?.message ?? '');
    if (notPlayedYet) {
      return (
        <Card className="p-6 text-center">
          <div className="text-3xl">📋</div>
          <div className="mt-2 font-bold">Partita non ancora giocata</div>
          <p className="mx-auto mt-1 max-w-sm text-sm text-ink-soft">
            Qui non c’è ancora niente da vedere. Il tabellino si riempie quando la
            giornata comincia; in una lega classic le formazioni già inviate
            compaiono anche prima, appena qualcuno schiera.
          </p>
          <Link
            to="/matches"
            className="mt-4 inline-flex rounded-xl bg-ink px-4 py-2 text-sm font-semibold text-paper hover:opacity-90"
          >
            ← Torna al calendario
          </Link>
        </Card>
      );
    }
    return <Card className="p-4 text-sm text-bad">Errore nel caricamento della partita: {error?.message ?? 'sconosciuto'}</Card>;
  }
  if (!data) return null;
  // Classic leagues carry mode:'classic' in the payload -> fantavoto detail (no zone
  // duel). Aura leagues fall through to the zone-duel MatchDetail.
  if (classicData) {
    return (
      <ClassicMatchDetail
        fixture={classicData}
        backTo="/matches"
        myUserId={user?.id ?? null}
        loadLedger={loadLedger}
      />
    );
  }
  return <MatchDetail fixture={data as SimFixtureDetail} backTo="/matches" />;
}
