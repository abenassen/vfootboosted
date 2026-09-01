import { useCallback, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getRealMatchDetail, getVoteLedger } from '../api';
import { Card } from '../components/ui';
import { ClassicMatchDetail } from '../components/match/ClassicMatchDetail';
import { useLeagueContext } from '../league/LeagueContext';
import { useChampionship } from '../league/ChampionshipContext';
import { useLiveSocket } from '../hooks/useNudgeSocket';
import { useAsync } from '../utils/useAsync';

// Vote-relevant detail of a REAL Serie A match: the per-player pagella
// (voto puro + bonus/malus = fantavoto) for both squads, rendered with the same
// ClassicMatchDetail component used by classic fantasy fixtures. (Aura zone
// breakdown enrichment is a planned follow-up.)
//
// Si legge anche senza lega: i voti sono gli stessi per tutti, e cambiano solo le
// etichette dei ruoli — dentro una lega quelli che ha congelato lei, fuori quelli
// della stagione (v. classic_pagella.pagella_for_match).
export default function RealMatchDetailPage() {
  const { matchId } = useParams();
  const { selectedLeagueId } = useLeagueContext();
  const { scope } = useChampionship();
  // Bumped by the socket; the only reason this page ever re-fetches on its own.
  const [tick, setTick] = useState(0);
  const { data, loading, error } = useAsync(
    () =>
      scope && matchId
        ? getRealMatchDetail(scope, matchId)
        : Promise.reject(new Error('Campionato o partita non selezionati')),
    // `scope` è memoizzato dal contesto: cambia identità solo quando cambia la
    // lega o la stagione, non a ogni render.
    [scope, matchId, tick],
  );
  // The tick nudges every league following this real match on each live import
  // (realdata/management/commands/tick.py), so the votes of a match being played
  // arrive here without a reload — which is the only way to read them while they
  // still mean something. The nudge carries no data: the same REST call that
  // built the page rebuilds it, so the pushed path and the reload path are one.
  useLiveSocket(selectedLeagueId ?? null, useCallback(() => setTick((n) => n + 1), []));

  // Le voci che il pannello del voto non mostra: si chiedono solo quando qualcuno
  // apre quella riga, e da qui perché è la pagina a sapere in che ambito sta
  // guardando (dentro una lega o sul campionato e basta) — v. getVoteLedger.
  const md = data?.real_matchday ?? null;
  const loadLedger = useMemo(
    () =>
      scope && md != null
        ? (playerId: number) => getVoteLedger(scope, md, playerId)
        : undefined,
    [scope, md],
  );

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
  return (
    <ClassicMatchDetail
      fixture={data}
      // Si torna ALLA GIORNATA DA CUI SI È ARRIVATI, non a quella corrente: la
      // legge il referto invece di farsela passare, così vale anche per un
      // indirizzo aperto da un segnalibro. Stessa cosa che fa il tasto
      // «indietro» del browser, e per la stessa ragione (v. useUrlParam).
      backTo={md != null ? `/serie-a?giornata=${md}` : '/serie-a'}
      backLabel="← Serie A"
      variant="real"
      loadLedger={loadLedger}
    />
  );
}
