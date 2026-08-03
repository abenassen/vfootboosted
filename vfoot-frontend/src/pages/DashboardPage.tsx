import { Link } from 'react-router-dom';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Card, SectionTitle } from '../components/ui';
import SetupBanner from '../components/SetupBanner';
import LeagueHome from '../components/LeagueHome';
import { useCompetitionContext } from '../league/CompetitionContext';

// This page no longer fetches the standings or the fixtures. Both existed only to
// feed the identity card above, and both are fetched again by LeagueHome right
// below — the standings call in particular is the one that had to GUESS a
// competition (see LeagueStandingsView: "the first round-robin, by id").
export default function DashboardPage() {
  const { leagues, selectedLeagueId, selectedLeague } = useLeagueContext();
  const { competitions } = useCompetitionContext();

  // No league => there is exactly ONE thing to do here, so the page is that one
  // thing and nothing else. The rest of the app is hidden from the menu too (see
  // AppShell): every other page would only answer "Seleziona una lega".
  if (!leagues.length) {
    return (
      <div className="space-y-4">
        <SetupBanner />
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
        <SetupBanner />
        <Card className="p-4 text-sm text-slate-600">Seleziona una lega dal selettore in alto.</Card>
      </div>
    );
  }

  const myName = selectedLeague?.team_name ?? null;

  return (
    <div className="space-y-4">
      {/* Above everything else on purpose: e' l'unico invito che su iOS il browser
          non fara' mai — ne' a installare, ne' ad accendere le notifiche — e sparisce
          per sempre una volta chiuso. */}
      <SetupBanner />
      <Card className="p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <SectionTitle>{selectedLeague?.name}</SectionTitle>
            <div className="mt-1 text-2xl font-black">{myName ?? 'Spettatore'}</div>
            {/* WHO you are, and nothing else.

                Rank, points, wins and average are COMPETITION-scoped. They were
                shown here as if a league had exactly one table, and WHICH one was
                decided server-side by "the oldest round-robin, by id" — so a league
                with two championships got one of the two answers with nothing on
                screen saying which. They now live in each competition's own block,
                under its name.

                The matchday is gone too, for a different reason: LeagueHome, two
                lines below, already states BOTH clocks ("si gioca la 22 · prossima
                da schierare: la 23"). Saying it twice is how the two came to
                disagree — this line used to read "giornata 1" while that one said
                22. */}
            {myName ? null : <div className="text-sm text-slate-500">Nessuna squadra associata</div>}
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
        </div>
      </Card>

      {/* Everything the old "Lega" page was for, and the part of it that was not
          a shortcut to somewhere else: what is being played right now in each
          competition, how each stands, and who is in the league. */}
      <LeagueHome competitions={competitions} />

    </div>
  );
}
