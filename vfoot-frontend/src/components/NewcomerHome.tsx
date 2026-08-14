import { Link } from 'react-router-dom';
import { Card } from './ui';
import SetupBanner from './SetupBanner';
import ChampionshipPicker from './ChampionshipPicker';
import FeedbackCard from './FeedbackCard';
import { useChampionship } from '../league/ChampionshipContext';

/** LA HOME DI CHI SI È APPENA ISCRITTO.
 *
 *  Prima era un titolo, due righe e un bottone: l'unica cosa possibile era creare
 *  una lega, e chiunque volesse capire PRIMA che sito fosse questo non aveva
 *  niente da guardare — le altre pagine rispondevano tutte «Seleziona una lega».
 *
 *  Creare (o entrare in) una lega resta l'invito principale e sta in cima da
 *  solo. Sotto, le tre pagine che si possono leggere senza avere una lega, che
 *  sono anche le tre risposte alla domanda «cosa fa questo sito»: il listone coi
 *  nostri valori, il campionato vero con le nostre pagelle, e come nasce il voto.
 *  Sono le stesse tre voci che il menu mostra a chi non ha leghe (AppShell,
 *  browseNav) — qui però ognuna dice anche perché aprirla.
 *
 *  Le prime due esistono solo se un campionato in corso c'è: senza, manderebbero
 *  a una pagina vuota, e questa è la sola cosa che il multicampionato cambia qui
 *  (il selettore compare da due edizioni in su, v. ChampionshipPicker).
 */
export default function NewcomerHome() {
  const { season, loading } = useChampionship();

  return (
    <div className="space-y-4">
      <SetupBanner />

      <Card className="p-6 text-center md:p-10">
        <div className="text-4xl">🏆</div>
        <div className="mt-3 text-2xl font-black md:text-3xl">Benvenuto in Vfoot Boosted</div>
        <p className="mx-auto mt-2 max-w-md text-sm text-ink-soft">
          Non fai ancora parte di nessuna lega. Creane una e invita i tuoi amici col codice che ti
          ritrovi, oppure entra in una lega esistente con il codice che ti hanno dato.
        </p>
        <Link
          to="/league-admin?tab=user"
          className="mt-6 inline-flex items-center gap-2 rounded-2xl bg-ink px-6 py-4 text-base font-bold text-paper shadow-card transition hover:opacity-90 active:scale-[0.99]"
        >
          <span className="text-xl">🏟️</span> Crea o unisciti a una lega
        </Link>
        <div className="mt-4 text-xs text-ink-faint">
          Squadra, formazione, mercato e classifiche si attivano appena sei in una lega.
        </div>
      </Card>

      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <div className="font-cond text-lg font-bold text-ink">Intanto puoi già guardare</div>
          <span className="ml-auto">
            <ChampionshipPicker showWhenSingle />
          </span>
        </div>
        <div className="mt-1 text-sm text-ink-soft">
          Queste pagine non hanno bisogno di una lega: sono il campionato vero e i nostri voti.
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {loading ? (
            <div className="text-sm text-ink-faint">Caricamento…</div>
          ) : (
            <>
              {season ? (
                <>
                  <Tile
                    to="/listone"
                    icon="📋"
                    title="Listone"
                    // «in Serie A» e non «della Serie A»: l'articolo giusto
                    // dipende dal nome del campionato, e il nome lo scegliamo
                    // così poco che è meglio una frase che regge comunque.
                    body={`Tutti i giocatori in ${season.competition}, con il valore che diamo loro: la media dei nostri voti, non un prezzo di listino.`}
                  />
                  <Tile
                    to="/serie-a"
                    icon="📅"
                    title={season.competition}
                    body="Calendario e risultati veri. Ogni partita giocata si apre sulle nostre pagelle, giocatore per giocatore."
                  />
                </>
              ) : null}
              <Tile
                to="/voto-puro"
                icon="🧮"
                title="Come nasce il voto"
                body="Il voto non lo assegna nessuno a mano: lo calcoliamo dai dati della partita. Qui c'è come, e dove ci allontaniamo dal fantacalcio del giornale."
              />
            </>
          )}
        </div>
      </Card>

      {/* Anche qui, e non solo nella home di chi ha una lega: chi si è appena
          iscritto e non ha ancora creato niente è proprio la persona che incontra
          per prima le cose che non funzionano. */}
      <FeedbackCard />
    </div>
  );
}

function Tile({
  to,
  icon,
  title,
  body,
}: {
  to: string;
  icon: string;
  title: string;
  body: string;
}) {
  return (
    <Link
      to={to}
      className="flex gap-3 rounded-xl border border-line bg-surface-2 p-3 transition hover:border-ink-faint hover:bg-line/30"
    >
      <span className="text-2xl leading-none">{icon}</span>
      <span className="min-w-0">
        <span className="block font-semibold text-ink">{title} →</span>
        <span className="mt-0.5 block text-xs leading-relaxed text-ink-soft">{body}</span>
      </span>
    </Link>
  );
}
