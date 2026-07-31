import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { getLeagueFixtures } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { useCompetitionContext } from '../league/CompetitionContext';
import { competitionFormatLabel } from '../league/competitionFormat';
import { Badge, Card, SectionTitle } from '../components/ui';
import Crest from '../components/Crest';
import type { LeagueFixtureItem } from '../types/league';

// Calendar of the CURRENTLY selected competition (set via the competition switcher):
// a round selector, the round's fixtures, each clickable to the rich detail.
export default function MatchesPage() {
  const { selectedLeagueId, selectedLeague } = useLeagueContext();
  const { selectedCompetitionId, selectedCompetition } = useCompetitionContext();
  const [fixtures, setFixtures] = useState<LeagueFixtureItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState<number | null>(null);

  useEffect(() => {
    setRound(null);
    if (!selectedLeagueId || !selectedCompetitionId) {
      setFixtures([]);
      return;
    }
    setLoading(true);
    setError(null);
    void getLeagueFixtures(selectedLeagueId, selectedCompetitionId)
      .then(setFixtures)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [selectedLeagueId, selectedCompetitionId]);

  const isKnockout = selectedCompetition?.competition_type === 'knockout';
  const rounds = useMemo(() => [...new Set(fixtures.map((f) => f.round_no))].sort((a, b) => a - b), [fixtures]);
  const activeRound = round ?? rounds[0] ?? null;
  const shown = useMemo(() => fixtures.filter((f) => f.round_no === activeRound), [fixtures, activeRound]);
  const roundLabel = (r: number) => fixtures.find((f) => f.round_no === r)?.round_label ?? `Giornata ${r}`;
  const roundRealMatchday = shown.find((f) => typeof f.real_matchday === 'number')?.real_matchday ?? null;
  const myTeamName = selectedLeague?.team_name?.trim() || null;

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega per vedere le partite.</div>;
  if (!selectedCompetitionId)
    return <div className="text-sm text-slate-500">Questa lega non ha ancora competizioni.</div>;
  if (loading) return <div className="text-sm text-slate-500">Caricamento partite…</div>;
  if (error) return <div className="text-sm text-red-600">Errore: {error}</div>;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-center gap-2">
          <SectionTitle>{selectedCompetition?.name ?? 'Calendario'}</SectionTitle>
          <Badge tone={isKnockout ? 'amber' : 'blue'}>
            {selectedCompetition ? competitionFormatLabel(selectedCompetition) : ''}
          </Badge>
        </div>
        <div className="mt-1 text-sm text-slate-600">
          {fixtures.length} partite · {rounds.length} {isKnockout ? 'turni' : 'giornate'}
        </div>
        <div className="mt-3 flex flex-wrap gap-1">
          {rounds.map((r) => (
            <button
              key={r}
              onClick={() => setRound(r)}
              className={
                r === activeRound
                  ? 'rounded-lg bg-slate-900 px-2.5 py-1 text-xs font-semibold text-white'
                  : 'rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-200'
              }
            >
              {isKnockout ? roundLabel(r) : r}
            </button>
          ))}
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>{activeRound != null ? roundLabel(activeRound) : 'Giornata'}</SectionTitle>
        {/* Said once for the round, not repeated identically under every match of
            it: all the fixtures of a round share the same real matchday. */}
        {roundRealMatchday != null ? (
          <div className="mt-0.5 text-xs text-slate-500">
            Si gioca sulla giornata {roundRealMatchday} di {selectedLeague?.reference_season?.competition ?? 'Serie A'}
          </div>
        ) : null}
        <div className="mt-3 space-y-2">
          {shown.length ? (
            shown.map((f) => <FixtureRow key={f.fixture_id} f={f} myTeam={myTeamName} />)
          ) : (
            <div className="text-sm text-slate-500">Nessuna partita in questa giornata.</div>
          )}
        </div>
      </Card>
    </div>
  );
}

function FixtureRow({ f, myTeam }: { f: LeagueFixtureItem; myTeam: string | null }) {
  const finished = f.status === 'finished' && f.score;
  const hs = f.score?.home_total ?? 0;
  const as = f.score?.away_total ?? 0;
  const homeWin = !!finished && hs > as;
  const awayWin = !!finished && as > hs;
  // Both decided by the server: opening a fixture with no detail lands on a 404,
  // and a lineup needs a roster the calendar never loads.
  const openable = f.has_detail ?? f.status === 'finished';
  const canSetLineup = f.can_set_lineup ?? false;

  const body = (
    <div className="flex items-center gap-3">
      <div className="flex flex-1 items-center justify-end gap-2">
        <span className={homeWin ? 'font-bold text-slate-900' : 'text-slate-600'}>{f.home_team.name}</span>
        <Crest descriptor={f.home_team.crest} teamName={f.home_team.name} size={24} />
      </div>
      {/* A played match shows a score plate; an unplayed one used to show "vs" in
          the same white box with a shadow, which reads as a button. */}
      {finished ? (
        <div className="flex items-center gap-1 rounded-lg bg-white px-2 py-1 font-mono text-sm font-bold shadow-sm">
          <span className={homeWin ? 'text-green-600' : 'text-slate-700'}>{Math.round(hs)}</span>
          <span className="text-slate-300">-</span>
          <span className={awayWin ? 'text-green-600' : 'text-slate-700'}>{Math.round(as)}</span>
        </div>
      ) : (
        <span className="px-2 text-xs font-semibold uppercase tracking-wide text-slate-400">vs</span>
      )}
      <div className="flex flex-1 items-center gap-2">
        <Crest descriptor={f.away_team.crest} teamName={f.away_team.name} size={24} />
        <span className={awayWin ? 'font-bold text-slate-900' : 'text-slate-600'}>{f.away_team.name}</span>
      </div>
    </div>
  );

  return (
    <div
      className={clsx(
        'rounded-xl border px-3 py-2.5',
        f.is_user_involved ? 'border-slate-300 bg-white' : 'border-slate-100 bg-slate-50',
      )}
    >
      {openable ? (
        <Link to={`/matches/${f.fixture_id}`} className="block transition hover:opacity-80">
          {body}
        </Link>
      ) : (
        <div title="Il tabellino sarà disponibile a partita giocata">{body}</div>
      )}
      {canSetLineup ? (
        <div className="mt-2 flex justify-center">
          <Link
            to={`/squad/formation?competition=${f.competition_id}&matchday=${f.real_matchday}`}
            className="rounded-lg bg-slate-900 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-slate-700"
          >
            {/* Named, because on a row of two unfamiliar team names a bare
                "Imposta formazione" does not say whose match this is. */}
            Imposta la formazione di {myTeam ?? 'la tua squadra'}
          </Link>
        </div>
      ) : null}
    </div>
  );
}
