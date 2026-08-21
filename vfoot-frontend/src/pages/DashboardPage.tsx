import { Link, useLocation } from 'react-router-dom';
import clsx from 'clsx';
import { useLeagueContext } from '../league/LeagueContext';
import { Card, SectionTitle } from '../components/ui';
import SetupBanner from '../components/SetupBanner';
import Crest from '../components/Crest';
import LeagueHome from '../components/LeagueHome';
import NewcomerHome from '../components/NewcomerHome';
import FeedbackCard from '../components/FeedbackCard';
import { useCompetitionContext } from '../league/CompetitionContext';

// This page no longer fetches the standings or the fixtures. Both existed only to
// feed the identity card above, and both are fetched again by LeagueHome right
// below — the standings call in particular is the one that had to GUESS a
// competition (see LeagueStandingsView: "the first round-robin, by id").
export default function DashboardPage() {
  const { leagues, selectedLeagueId, selectedLeague } = useLeagueContext();
  const { competitions, loading: competitionsLoading } = useCompetitionContext();
  // «Sei entrato in X con Y», detto qui perché è qui che si arriva subito dopo
  // (v. JoinLeaguePage e il modulo col codice in Gestione lega): la pagina che
  // scrive la conferma non è più a schermo un istante dopo averla scritta.
  const joined = (useLocation().state as { joined?: { league: string; team: string } } | null)?.joined;

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
      {joined ? (
        <div className="rounded-xl border border-good/40 bg-good-bg px-3 py-2 text-sm font-semibold text-good">
          Sei entrato in «{joined.league}» con {joined.team}.
        </div>
      ) : null}
      {/* Above everything else on purpose: e' l'unico invito che su iOS il browser
          non fara' mai — ne' a installare, ne' ad accendere le notifiche — e sparisce
          per sempre una volta chiuso. */}
      <SetupBanner />
      {/* SOLO DA TABLET IN SU, e resta così. Su un telefono questa scheda dice le
          tre cose che l'intestazione della app scrive già due centimetri più in
          alto: stemma, nome della lega, nome della squadra. Là non costano niente
          perché la barra c'è comunque; qui stavano davanti alla cosa per cui si
          apre l'app. Adesso che lo stemma è grande la scheda è più alta, non meno,
          quindi il motivo per tenerla via dal telefono è più forte di prima — su
          un telefono lo stemma proprio si guarda nell'elenco dei partecipanti,
          dove sta accanto a quello di tutti gli altri. In largo invece la barra
          laterale non ripete la squadra, e la scheda resta l'unica a dire chi sei
          in questa lega. */}
      <Card className="vf-hero hidden border-transparent p-4 md:block">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex items-center gap-4">
            {/* GRANDE, e non a fianco del nome come una figurina. Lo stemma è la
                cosa che l'utente ha COMPOSTO — colori, fasce, o un'immagine
                caricata a mano — e in tutta la app compariva fra i ventidue e i
                cinquantadue pixel: alla dimensione di un segnaposto, cioè alla
                dimensione in cui la scelta di chi l'ha fatto non si vede. Qui c'è
                lo spazio per mostrarlo davvero, ed è l'unico punto in cui uno
                guarda il PROPRIO. Novantasei pixel (centododici in largo) sono
                sopra le tre righe di testo che gli stanno accanto, quindi cresce
                lo stemma e non la scheda.

                E porta alla rosa, che è la pagina da cui lo si cambia: prima era
                un disegno morto, e chi voleva ritoccarlo doveva sapere già dove
                andare. */}
            <Link to="/squad" title="La tua squadra — da qui si cambia lo stemma" className="shrink-0">
              <Crest
                descriptor={selectedLeague?.team_crest}
                teamName={myName}
                size={96}
                className={clsx(
                  'transition hover:scale-105 lg:h-28 lg:w-28',
                  myName ? undefined : 'opacity-40',
                )}
              />
            </Link>
            <div className="min-w-0">
              <SectionTitle className="text-white/75">{selectedLeague?.name}</SectionTitle>
              <div className="mt-1 font-cond text-4xl font-bold uppercase leading-none tracking-wide">{myName ?? 'Spettatore'}</div>
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

      {/* Everything the old "Lega" page was for, and the part of it that was not
          a shortcut to somewhere else: what is being played right now in each
          competition, how each stands, and who is in the league.

          E ANCHE la scheda «Lega in costruzione», che per un po' stava qui sopra.
          Stava nel posto sbagliato per un motivo strutturale, non estetico: una
          scheda disegnata da QUESTA pagina finisce per forza sopra tutto quello
          che disegna LeagueHome, e così un'asta accesa — che è un evento dal vivo
          — restava mille pixel sotto un elenco di cose da fare. L'ordine di una
          lega in costruzione lo decide adesso LeagueHome, che è l'unico posto da
          cui si vedono entrambe le cose. Serve solo sapere se le competizioni
          sono ancora in arrivo: senza, una lega che gioca si annuncerebbe «in
          costruzione» per il tempo di una chiamata. */}
      <LeagueHome competitions={competitions} competitionsLoading={competitionsLoading} />

      {/* In fondo, e non più in alto: non è il motivo per cui si apre l'app, ma
          la home è l'unica pagina su cui si torna sempre — quindi è l'unico posto
          in cui una segnalazione si può lasciare senza doverla prima cercare. */}
      <FeedbackCard />
    </div>
  );
}
