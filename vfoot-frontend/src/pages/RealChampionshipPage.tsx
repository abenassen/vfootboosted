import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { getRealFixtures } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { useChampionship } from '../league/ChampionshipContext';
import ChampionshipPicker from '../components/ChampionshipPicker';
import { useLiveSocket } from '../hooks/useNudgeSocket';
import { Badge, Card, SectionTitle } from '../components/ui';
import { useResetOnChange, useUrlParam } from '../utils/useUrlParam';
import ProbableLineups from '../components/match/ProbableLineups';
import type { RealFixtureItem, RealFixturesResponse } from '../types/realChampionship';

// Calendar + results of a REAL championship (e.g. Serie A): a matchday selector,
// the round's fixtures with live/finished/scheduled state, each played match
// clickable to its vote-relevant pagella. Dentro una lega è il campionato su cui
// si gioca; senza lega è il campionato in corso (v. ChampionshipContext).
export default function RealChampionshipPage() {
  const { selectedLeagueId } = useLeagueContext();
  const { scope, browsing, loading: scopeLoading } = useChampionship();
  const [data, setData] = useState<RealFixturesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // LA GIORNATA STA NELL'INDIRIZZO (`?giornata=2`), non qui dentro: chi sta
  // sfogliando una giornata passata ne apre più di una partita, e tornare
  // indietro dal tabellino rimonta questa pagina da zero (v. useUrlParam).
  const [giornata, setGiornata] = useUrlParam('giornata');
  // Bumped by the socket; the only reason this page ever re-fetches on its own.
  const [tick, setTick] = useState(0);

  // Whether anything has ever been on screen, so the spinner and the error box
  // only take over a page that has nothing to show yet.
  const loadedRef = useRef(false);

  // Changing CHAMPIONSHIP drops the chosen round — it belongs to the old
  // calendar. A live nudge must NOT: you would be pulled back to the current
  // matchday every time a vote moved, which is precisely while you are most
  // likely to be reading another round. Hence two effects rather than one.
  // (`scope` regge come dipendenza perché il contesto lo memoizza: cambia
  // identità solo quando cambia davvero la lega o la stagione guardata.)
  useResetOnChange(scope, useCallback(() => setGiornata(null), [setGiornata]));

  useEffect(() => {
    if (!scope) {
      setData(null);
      return;
    }
    // Only the FIRST load blanks the page: a re-fetch pushed while you are reading
    // must not replace the calendar with "Caricamento…".
    if (!loadedRef.current) setLoading(true);
    setError(null);
    void getRealFixtures(scope)
      .then((res) => {
        setData(res);
        loadedRef.current = true;
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [scope, tick]);

  // Same nudge the match detail listens to: every live import of a match in this
  // championship refreshes the scores and the in-corso marks in place.
  useLiveSocket(selectedLeagueId ?? null, useCallback(() => setTick((n) => n + 1), []));

  const matchdays = useMemo(
    () => (data?.matchdays ?? []).map((g) => g.matchday).filter((m): m is number => m != null),
    [data],
  );
  // Una giornata che questo calendario non ha — un indirizzo copiato da un'altra
  // stagione, o scritto a mano — non svuota la pagina: vale come se non ci fosse.
  const chiesta = giornata != null ? Number(giornata) : null;
  const active =
    (chiesta != null && matchdays.includes(chiesta) ? chiesta : null) ??
    data?.current_matchday ??
    matchdays[0] ??
    null;
  const group = useMemo(
    () => data?.matchdays.find((g) => g.matchday === active) ?? null,
    [data, active],
  );

  if ((loading || scopeLoading) && !data)
    return <div className="text-sm text-ink-faint">Caricamento calendario…</div>;
  if (error && !data) return <div className="text-sm text-bad">Errore: {error}</div>;
  if (!scope)
    return (
      <div className="text-sm text-ink-faint">
        Nessun campionato in corso da mostrare.
      </div>
    );
  if (!data?.season)
    return <div className="text-sm text-ink-faint">Questa lega non ha una stagione di riferimento.</div>;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <SectionTitle>{data.season.competition}</SectionTitle>
          <Badge tone="blue">{data.season.name}</Badge>
          <span className="ml-auto">
            <ChampionshipPicker />
          </span>
        </div>
        <div className="mt-1 text-sm text-ink-soft">Calendario e risultati reali · {matchdays.length} giornate</div>
        {/* Chi non è ancora in una lega sta guardando il campionato vero da
            fuori: la riga dice che cosa ci fa qui, e dove porta un click. */}
        {browsing ? (
          <div className="mt-1 text-[11px] text-ink-faint">
            Apri una partita giocata per leggere le nostre pagelle: il voto di ogni giocatore,
            calcolato dai dati della partita.
          </div>
        ) : null}
        <div className="mt-3 flex flex-wrap gap-1">
          {matchdays.map((m) => (
            <button
              key={m}
              onClick={() => setGiornata(m)}
              className={
                m === active
                  ? 'rounded-lg bg-ink px-2.5 py-1 text-xs font-semibold text-paper'
                  : 'rounded-lg bg-surface-2 px-2.5 py-1 text-xs font-semibold text-ink-soft hover:bg-surface-2'
              }
            >
              {m}
            </button>
          ))}
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>{active != null ? `Giornata ${active}` : 'Giornata'}</SectionTitle>
        <div className="mt-2 space-y-2">
          {group?.fixtures.length ? (
            group.fixtures.map((f) => <RealFixtureRow key={f.id} f={f} />)
          ) : (
            <div className="text-sm text-ink-faint">Nessuna partita.</div>
          )}
        </div>
      </Card>
    </div>
  );
}

function fmtKickoff(iso: string | null, provisional: boolean): string {
  if (!iso || provisional) return 'Orario da definire';
  const d = new Date(iso);
  return d.toLocaleString('it-IT', {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function RealFixtureRow({ f }: { f: RealFixtureItem }) {
  const played = f.status === 'finished' || f.status === 'live';
  // Le probabili si aprono a richiesta, e solo su una partita che deve ancora
  // cominciare: una richiesta per riga sarebbe dieci richieste per aprire una
  // giornata che quasi nessuno espande.
  const [openProbable, setOpenProbable] = useState(false);
  const canProbable = f.status === 'scheduled';
  const hs = f.home_goals ?? 0;
  const as = f.away_goals ?? 0;
  const homeWin = played && hs > as;
  const awayWin = played && as > hs;

  const body = (
    <div className="flex items-center gap-3">
      <div className="flex-1 text-right">
        <span className={homeWin ? 'font-bold text-ink' : 'text-ink-soft'}>{f.home_team}</span>
      </div>
      <div className="flex items-center gap-1 rounded-lg bg-surface px-2 py-1 font-mono text-sm font-bold shadow-sm">
        {played ? (
          <>
            <span className={homeWin ? 'text-good' : 'text-ink-soft'}>{hs}</span>
            <span className="text-ink-faint">-</span>
            <span className={awayWin ? 'text-good' : 'text-ink-soft'}>{as}</span>
          </>
        ) : (
          <span className="text-ink-faint">vs</span>
        )}
      </div>
      <div className="flex-1">
        <span className={awayWin ? 'font-bold text-ink' : 'text-ink-soft'}>{f.away_team}</span>
      </div>
    </div>
  );

  return (
    <div className="rounded-xl border border-line bg-surface-2 px-3 py-2.5">
      {f.has_detail ? (
        <Link to={`/serie-a/${f.id}`} className="block transition hover:opacity-80">
          {body}
        </Link>
      ) : (
        body
      )}
      <div className="mt-1 flex items-center justify-center gap-2 text-[10px] uppercase tracking-wide text-ink-faint">
        {canProbable ? (
          <button
            type="button"
            onClick={() => setOpenProbable((v) => !v)}
            className="rounded px-1.5 py-0.5 font-semibold uppercase tracking-wide text-ink-soft hover:bg-surface"
          >
            {openProbable ? 'Nascondi probabili' : 'Probabili'}
          </button>
        ) : null}
        {f.status === 'live' ? (
          <span className="inline-flex items-center gap-1 font-bold text-bad">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-bad" />
            In corso
          </span>
        ) : f.status === 'finished' ? (
          <span>Finale{f.has_detail ? ' · voti disponibili' : ''}</span>
        ) : f.status === 'postponed' ? (
          <span className="font-semibold text-warn">Rinviata</span>
        ) : f.status === 'cancelled' ? (
          <span className="font-semibold text-bad">Annullata</span>
        ) : (
          <span>{fmtKickoff(f.kickoff, f.kickoff_provisional)}</span>
        )}
      </div>
      {canProbable && openProbable ? <ProbableLineups matchId={f.id} /> : null}
    </div>
  );
}
