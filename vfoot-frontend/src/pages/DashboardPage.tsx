import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getLeagueFixtures, getLeagueStandings } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Card, SectionTitle } from '../components/ui';
import InstallBanner from '../components/InstallBanner';
import LeagueHome from '../components/LeagueHome';
import { useCompetitionContext } from '../league/CompetitionContext';
import type { LeagueFixtureItem, LeagueStandingRow } from '../types/league';

export default function DashboardPage() {
  const { leagues, selectedLeagueId, selectedLeague } = useLeagueContext();
  const { competitions } = useCompetitionContext();
  const [standings, setStandings] = useState<LeagueStandingRow[]>([]);
  const [fixtures, setFixtures] = useState<LeagueFixtureItem[]>([]);

  useEffect(() => {
    if (!selectedLeagueId) {
      setStandings([]);
      setFixtures([]);
      return;
    }
    void getLeagueStandings(selectedLeagueId).then((r) => setStandings(r.standings)).catch(() => setStandings([]));
    void getLeagueFixtures(selectedLeagueId).then(setFixtures).catch(() => setFixtures([]));
  }, [selectedLeagueId]);

  // No league => there is exactly ONE thing to do here, so the page is that one
  // thing and nothing else. The rest of the app is hidden from the menu too (see
  // AppShell): every other page would only answer "Seleziona una lega".
  if (!leagues.length) {
    return (
      <div className="space-y-4">
        <InstallBanner />
        <Card className="p-6 text-center md:p-10">
          <div className="text-4xl">🏆</div>
          <div className="mt-3 text-2xl font-black md:text-3xl">Benvenuto in Vfoot Boosted</div>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
            Non fai ancora parte di nessuna lega. Creane una e invita i tuoi amici col
            codice che ti ritrovi, oppure entra in una lega esistente con il codice che
            ti hanno dato.
          </p>
          <Link
            to="/league-admin?tab=user"
            className="mt-6 inline-flex items-center gap-2 rounded-2xl bg-slate-900 px-6 py-4 text-base font-bold text-white shadow-card transition hover:bg-slate-800 active:scale-[0.99]"
          >
            <span className="text-xl">🏟️</span> Crea o unisciti a una lega
          </Link>
          <div className="mt-4 text-xs text-slate-500">
            Squadra, formazione, mercato e classifiche si attivano appena sei in una lega.
          </div>
        </Card>
      </div>
    );
  }
  if (!selectedLeagueId) {
    return (
      <div className="space-y-4">
        <InstallBanner />
        <Card className="p-4 text-sm text-slate-600">Seleziona una lega dal selettore in alto.</Card>
      </div>
    );
  }

  const myName = selectedLeague?.team_name ?? null;
  const myRow = myName ? standings.find((s) => s.team === myName) ?? null : null;
  const mine = fixtures.filter((f) => f.is_user_involved);
  const next = mine.filter((f) => f.status !== 'finished').sort((a, b) => a.round_no - b.round_no)[0] ?? null;
  const seasonOver = !next && mine.length > 0;

  return (
    <div className="space-y-4">
      {/* Above everything else on purpose: it is the one invitation the browser
          will never issue on iOS, and it disappears for good once dismissed. */}
      <InstallBanner />
      <Card className="p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <SectionTitle>{selectedLeague?.name}</SectionTitle>
            <div className="mt-1 text-2xl font-black">{myName ?? 'Spettatore'}</div>
            <div className="text-sm text-slate-500">
              {myRow ? `${myRow.rank}ª in classifica · ${myRow.points} pt` : 'Nessuna squadra associata'}
              {seasonOver ? ' · campionato concluso' : next ? ` · prossima: giornata ${next.round_no}` : ''}
            </div>
          </div>
          {/* No "Formazione" button here any more: with a championship and a cup
              running together it could only guess which one you meant. The
              shortcuts now sit on each next match, named after its competition. */}
          {/* No "Mercato aperto" badge here. market_open does not mean the market
              is running: it is the admin's switch for editing rosters BY HAND
              (add/remove/bulk), it defaults to true, and it guards three
              admin-only endpoints. On a league that has not even held its auction
              it announced an open market that did not exist. The real state of
              the auction and of the offer market is shown by LeagueHome, and only
              when there is one. */}
          <div className="flex flex-wrap items-center gap-2">
            {myRow ? (
              <span className="text-xs text-slate-500">
                {myRow.wins}V · {myRow.draws}N · {myRow.losses}P · media {myRow.avg_score_for.toFixed(1)}
              </span>
            ) : null}
          </div>
        </div>
      </Card>

      {/* Everything the old "Lega" page was for, and the part of it that was not
          a shortcut to somewhere else: what is being played right now in each
          competition, how each stands, and who is in the league. */}
      <LeagueHome competitions={competitions} />

    </div>
  );
}
