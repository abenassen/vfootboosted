import { Link } from 'react-router-dom';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Card, SectionTitle } from '../components/ui';
import SetupBanner from '../components/SetupBanner';
import Crest from '../components/Crest';
import LeagueHome from '../components/LeagueHome';
import NewcomerHome from '../components/NewcomerHome';
import InviteShare from '../components/InviteShare';
import { useCompetitionContext } from '../league/CompetitionContext';

// This page no longer fetches the standings or the fixtures. Both existed only to
// feed the identity card above, and both are fetched again by LeagueHome right
// below — the standings call in particular is the one that had to GUESS a
// competition (see LeagueStandingsView: "the first round-robin, by id").
export default function DashboardPage() {
  const { leagues, selectedLeagueId, selectedLeague } = useLeagueContext();
  const { competitions, loading: competitionsLoading } = useCompetitionContext();

  // NESSUNA LEGA. La cosa da fare resta una — crearne o entrare in una — ma non è
  // più l'unica cosa possibile: il campionato vero, il suo listone e la pagina che
  // spiega i voti non appartengono a nessuna lega, e sono esattamente quello che
  // uno vuole guardare PRIMA di decidere se giocare qui (v. ChampionshipContext).
  // Finché non c'erano, questa pagina era un vicolo cieco con un bottone in mezzo.
  if (!leagues.length) return <NewcomerHome />;
  if (!selectedLeagueId) {
    return (
      <div className="space-y-4">
        <SetupBanner />
        <Card className="p-4 text-sm text-ink-soft">Seleziona una lega dal selettore in alto.</Card>
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
      {/* SOLO DA TABLET IN SU. Su un telefono questa scheda dice, in ottantotto
          pixel più il margine, le tre cose che l'intestazione della app scrive già
          due centimetri più in alto: stemma, nome della lega, nome della squadra.
          Là non costa niente perché la barra c'è comunque; qui stava davanti alla
          cosa per cui si apre l'app. In largo invece la barra laterale non ripete
          la squadra, e la scheda resta l'unica a dire chi sei in questa lega. */}
      <Card className="vf-hero hidden border-transparent p-4 md:block">
        <div className="flex flex-wrap items-end justify-between gap-3">
          {/* Lo stemma, che qui mancava. È l'unica pagina della lega che diceva
              il nome della squadra senza mostrarla: la rosa ce l'ha, il
              calendario ce l'ha su ogni riga, i partecipanti pure — e proprio
              l'intestazione, dove si legge chi sei in questa lega, no. */}
          <div className="flex items-center gap-3">
            <Crest
              descriptor={selectedLeague?.team_crest}
              teamName={myName}
              size={52}
              className={myName ? undefined : 'opacity-40'}
            />
            <div className="min-w-0">
              <SectionTitle className="text-white/75">{selectedLeague?.name}</SectionTitle>
              <div className="mt-1 font-cond text-3xl font-bold uppercase leading-none tracking-wide">{myName ?? 'Spettatore'}</div>
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
              {myName ? null : <div className="text-sm text-white/75">Nessuna squadra associata</div>}
            </div>
          </div>
          {/* No "Formazione" button here any more: with a championship and a cup
              running together it could only guess which one you meant. The
              shortcuts now sit on each next match, named after its competition. */}
          {/* No "Mercato aperto" badge here. It used to read a league flag
              (market_open) that did not mean the market was running — on a league
              that had not even held its auction it announced an open market that
              did not exist. That flag is gone; the real state of the auction and
              of the offer market is shown by LeagueHome, and only when there is
              one. */}
        </div>
      </Card>

      {/* UNA LEGA SENZA COMPETIZIONI HA UNA HOME BIANCA, e lo era per davvero:
          `LeagueHome` si tira indietro quando non c'è niente da giocare — ha
          ragione, è la vista delle competizioni — e la scheda con lo stemma qui
          sopra non si vede più sul telefono. Restava il solo banner delle
          notifiche, su una pagina che si intitola «Home lega».

          Non è un caso raro né un errore: è come si presenta OGNI lega appena
          creata, cioè il primo schermo che vede chi ne apre una. Quindi qui si
          dice cosa manca e chi lo deve fare, che sono due risposte diverse a
          seconda di chi guarda. */}
      {!competitionsLoading && !competitions.length ? (
        <Card className="border-l-4 border-accent bg-accent/10 p-4">
          <div className="text-sm font-bold text-accent">🚧 Lega in costruzione</div>
          <p className="mt-1 text-sm text-ink-soft">
            <b>{selectedLeague?.name}</b> non ha ancora una competizione, e finché non ce n'è una non
            c'è niente da giocare: calendario, classifica e formazione nascono tutti da lì.
          </p>
          {selectedLeague?.role === 'admin' ? (
            <>
              {/* L'ordine conta ed è una dipendenza vera, non una convenzione: il
                  calendario si genera dalle squadre presenti in quel momento, per
                  cui una competizione creata da soli nasce senza partite. È la
                  stessa cosa che dice la checklist in Gestione lega, detta qui
                  perché è qui che si arriva per primi. */}
              <div className="mt-3 rounded-xl border border-line bg-surface p-3">
                <div className="text-xs font-bold uppercase tracking-wide text-ink-faint">
                  1 — Fai entrare gli altri
                </div>
                <div className="mt-2">
                  <InviteShare
                    code={selectedLeague.invite_code}
                    leagueName={selectedLeague.name}
                    compact
                  />
                </div>
                <div className="mt-2 text-xs text-ink-faint">
                  Prima loro, poi la competizione: il calendario si costruisce sulle squadre presenti
                  quando lo generi, quindi creandola adesso resterebbe senza partite.
                </div>
              </div>
              <Link
                to="/league-admin?tab=league"
                className="mt-3 flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-bold text-white shadow-card hover:opacity-90 active:scale-[0.99]"
              >
                2 — Crea la competizione →
              </Link>
            </>
          ) : (
            <div className="mt-3 text-sm text-ink-faint">
              La crea l'amministratore della lega. Appena c'è, questa pagina si riempie da sola —
              nel frattempo il listone e il campionato di riferimento sono già consultabili dal menu.
            </div>
          )}
        </Card>
      ) : null}

      {/* Everything the old "Lega" page was for, and the part of it that was not
          a shortcut to somewhere else: what is being played right now in each
          competition, how each stands, and who is in the league. */}
      <LeagueHome competitions={competitions} />

    </div>
  );
}
