import { Link } from 'react-router-dom';
import { Card } from '../components/ui';
import { BENCHMARK_URL, VOTO, useBenchmarkAvailable } from '../content/votoPuro';
import logo from '../assets/logo.png';

/** COME NASCE IL VOTO — la versione per chi non è iscritto.
 *
 *  Perché esiste. Il voto calcolato è la ragione per cui questo sito è diverso
 *  dagli altri, ed era leggibile solo DOPO l'iscrizione: chi stava valutando se
 *  entrare doveva fidarsi della riga di presentazione — «voti calcolati dai dati
 *  reali, non copiati dai giornali» — senza poter controllare che cosa ci sia
 *  dietro. È l'ordine sbagliato: la spiegazione serve a chi non ha ancora
 *  deciso, non a chi ha già deciso.
 *
 *  Perché è corta. Dentro l'app la pagina lunga (VotoPuroPage) è di
 *  CONSULTAZIONE: la si apre da una pagella con una domanda precisa — «perché il
 *  mio attaccante ha 6 dopo un gol?» — e deve rispondere per casi. Qui la
 *  domanda è un'altra e una sola: da dove viene il numero, e ci si può fidare.
 *  Undici capitoli con l'indice, a chi sta ancora sulla soglia, dicono «non
 *  adesso». Quindi: come si arriva al voto, dove ci allontaniamo dalla pagella,
 *  quanto siamo d'accordo, che cosa non sappiamo. Il resto sta di là.
 *
 *  Le cifre non sono ricopiate: vengono da content/votoPuro.ts, che le tiene per
 *  tutt'e due le pagine — due copie a mano sono due copie che divergono al primo
 *  ritaraggio.
 *
 *  I limiti ci sono anche qui, e non è modestia: una pagina di vendita che
 *  elenca i propri punti deboli è la sola forma di credibilità che possiamo
 *  offrire a chi non ha ancora visto un voto in vita sua.
 */
export default function VotoPubblicoPage() {
  const benchmark = useBenchmarkAvailable();

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_20%_20%,#dbeafe_0%,#eff6ff_45%,#f8fafc_100%)] text-ink">
      {/* Come nella pagina di benvenuto: la riserva per la barra di stato si
          somma al respiro, e fuori da iOS vale zero. */}
      <div className="mx-auto max-w-3xl px-4 py-8 pt-[calc(2rem_+_var(--vf-safe-top))] md:py-14 md:pt-[calc(3.5rem_+_var(--vf-safe-top))]">
        {/* Il ritorno è la prima cosa: chi arriva qui da un link condiviso non ha
            mai visto la pagina di benvenuto, e deve poterci andare. */}
        <div className="mb-6 flex items-center justify-between gap-3">
          <Link to="/" className="flex items-center gap-2.5 rounded-lg hover:opacity-80">
            <img src={logo} alt="Vfoot logo" className="h-9 w-9 rounded-lg object-cover shadow-card" />
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                Vfoot Boosted
              </div>
              <div className="text-sm font-black leading-tight">Il gioco sul calcio</div>
            </div>
          </Link>
          <Link
            to="/"
            className="shrink-0 rounded-xl bg-ink px-3.5 py-2 text-sm font-bold text-paper hover:opacity-90"
          >
            Entra
          </Link>
        </div>

        <header className="mb-5 space-y-3">
          <h1 className="text-3xl font-black leading-tight md:text-4xl">Come nasce il voto</h1>
          <p className="text-ink-soft md:text-lg">
            La pagella di un giornale parte da un'impressione e la traduce in un numero. Noi partiamo
            da una quarantina di misure di quello che è successo in campo e le trasformiamo in un
            numero. Nessuno lo assegna a mano, e non lo compriamo da nessuno: è la ragione per cui
            questo sito esiste, quindi è giusto che si possa leggere prima di iscriversi.
          </p>
        </header>

        <div className="space-y-4">
          <Blocco titolo="Il voto puro è metà del punteggio">
            <p>
              Il punteggio di un giocatore è fatto di due pezzi: <b className="text-ink">voto puro</b>{' '}
              + <b className="text-ink">bonus e malus</b>. Gli episodi che hanno già un prezzo scritto
              — gol +3, assist +1, ammonizione −0,5 — li applichiamo esattamente come tutti.
            </p>
            <p>
              Il voto puro è l'altra metà: <i>quanto bene ha giocato</i>. Quello lo calcoliamo noi. E
              non contiene il gol: se un attaccante ha 6,0 di voto puro e ha segnato, il suo fantavoto
              è 9,0 come dappertutto. Metterlo anche nel voto sarebbe contarlo due volte — noi
              valutiamo semmai <b className="text-ink">quanto merito ci fosse in quel gol</b>.
            </p>
          </Blocco>

          <Blocco titolo="Da dove viene il numero">
            <p>
              Di ogni partita raccogliamo, giocatore per giocatore, che cosa ha fatto e{' '}
              <b className="text-ink">in che parte del campo</b>: il campo è diviso in venti zone, e
              ogni tocco, duello, tiro e intervento finisce nella zona in cui è avvenuto. Poi:
            </p>
            <ol className="space-y-2">
              <Passo n={1} titolo="Ogni misura si confronta con la norma del ruolo">
                Dieci duelli vinti non dicono niente da soli: dipende da quanti ne vince chi gioca lì.
              </Passo>
              <Passo n={2} titolo="Ogni misura ha il suo peso">
                Quanto conta calciare bene rispetto a vincere un duello, quanto costa un errore. È la
                parte scritta da noi, tarata su una stagione intera di pagelle vere.
              </Passo>
              <Passo n={3} titolo="La somma diventa un voto da pagella">
                La media di ogni ruolo è 6; da lì si sale o si scende in proporzione a quanto la
                partita si stacca dalla norma. Arrotondato al mezzo voto, tra 3 e 10.
              </Passo>
              <Passo n={4} titolo="Le ultime correzioni">
                Chi ha giocato pochi minuti torna verso il 6. Il risultato tempera i voti stonati —
                alto in una sconfitta, basso in una vittoria — ma non li esalta mai.
              </Passo>
            </ol>
            <p className="text-xs text-ink-faint">
              Dentro l'app ogni voto è ispezionabile: toccandolo si apre il conto di quel numero, voce
              per voce, fino al voto finale.
            </p>
          </Blocco>

          <Blocco titolo="Dove ci allontaniamo dalla pagella">
            <p>
              Le differenze non sono difetti del calcolo: sono scelte su come leggere il calcio, e
              sono sempre le stesse tre.
            </p>
            <ul className="list-disc space-y-1.5 pl-4 marker:text-ink-faint">
              <li>
                <b className="text-ink">Il gol non vale un voto fisso.</b> Nelle pagelle l'attaccante
                che segna prende quasi sempre 7. Da noi il gol lo paga il bonus, e intorno al gol
                continuiamo a leggere la partita: qualcuno prenderà 6, qualcuno 8.
              </li>
              <li>
                <b className="text-ink">Chi crea e non viene ripagato lascia traccia.</b> L'assist
                esiste solo se il compagno segna; l'occasione creata, da noi, vale anche quando finisce
                male.
              </li>
              <li>
                <b className="text-ink">Il pericolo ha un indirizzo.</b> Ogni tiro concesso viene
                addebitato a chi era in quella zona, non a tutta la difesa. Per questo, da noi, un
                difensore può prendere 6,5 in una serata da tre gol presi — e il suo compagno di
                reparto 4,0.
              </li>
            </ul>
            <div className="grid gap-2 sm:grid-cols-2">
              <Caso
                partita="Como–Napoli 0-0 · 35ª"
                chi="De Bruyne"
                noi="6,5"
                loro="5,0"
                perche="Un'occasione limpida servita a un compagno, un'ora senza perdere duelli. In uno 0-0 chi crea e non viene ripagato non lascia traccia."
              />
              <Caso
                partita="Inter–Pisa 6-2 · 22ª"
                chi="Moreo"
                noi="6,0"
                loro="7,5"
                perche="Due gol nel 6-2 dell'Inter: col bonus il fantavoto è 12,5 come per tutti, ma il gioco intorno resta quello di una serata perduta. Qui la pagella sta più in alto di noi."
              />
            </div>
          </Blocco>

          <Blocco titolo="Quanto siamo d'accordo con le pagelle">
            <p>
              Non abbiamo lavorato alla cieca: a ogni messa a punto rigiochiamo l'ultima stagione
              conclusa e confrontiamo tutti i nostri voti con i due di fantacalcio.it — la Redazione,
              scritta da una persona, e il loro Statistico. Sulla {VOTO.stagione} sono{' '}
              <b className="text-ink">{VOTO.pagelle} pagelle</b> confrontate una per una.
            </p>
            <div className="grid gap-2 sm:grid-cols-3">
              <Numero valore={VOTO.entroMezzo} testo="entro mezzo punto dalla pagella" />
              <Numero valore={VOTO.entroUno} testo="entro un punto" />
              <Numero
                valore={VOTO.scartoMedio}
                testo="lo scarto medio: vicini alle pagelle, non allineati"
              />
            </div>
            <p>
              E quando divergiamo, chi ha ragione? Un metro indipendente è il{' '}
              <b className="text-ink">rating di SofaScore</b>, che non entra mai nel nostro calcolo.
              Il nostro voto gli somiglia più di quanto gli somiglino le pagelle, in tutti e quattro i
              ruoli: da {VOTO.correlazione[3].noi} a {VOTO.correlazione[0].noi} contro{' '}
              {VOTO.correlazione[3].redazione}–{VOTO.correlazione[0].redazione} della Redazione. Non
              dice che i nostri voti sono «giusti»: dice che quando ci allontaniamo dalla pagella non
              lo facciamo a caso.
            </p>
            {benchmark ? (
              <div className="rounded-xl border border-dashed border-line bg-surface-2 p-3">
                Non fidarti di queste cifre: <b className="text-ink">guardale</b>. Il confronto è
                pubblicato per intero, giornata per giornata —{' '}
                <a
                  href={BENCHMARK_URL}
                  className="font-semibold text-accent underline decoration-dotted"
                  target="_blank"
                  rel="noreferrer"
                >
                  i nostri voti a fianco di quelli di fantacalcio.it
                </a>
                , senza scegliere gli esempi.
              </div>
            ) : null}
          </Blocco>

          <Blocco titolo="Quello che il voto non sa">
            <ul className="list-disc space-y-1.5 pl-4 marker:text-ink-faint">
              <li>
                <b className="text-ink">Il compito tattico.</b> Non sappiamo che cosa gli aveva chiesto
                l'allenatore: un mediano mandato a spezzare il gioco farà numeri da partita anonima.
              </li>
              <li>
                <b className="text-ink">Quello che non si conta.</b> Il movimento che libera il
                compagno, la copertura preventiva: sono nel calcio e non sono nei dati.
              </li>
              <li>
                <b className="text-ink">Siamo prudenti.</b> Il {VOTO.quotaSei.noi} dei nostri voti è
                esattamente 6, contro il {VOTO.quotaSei.pagelle} delle pagelle: quando i dati non
                dicono niente di netto, non inventiamo un giudizio.
              </li>
              <li>
                <b className="text-ink">Non sappiamo chi è.</b> Il nome, il prezzo e la fama non
                entrano nel calcolo. Un big in giornata da 5,5 prende 5,5.
              </li>
            </ul>
          </Blocco>
        </div>

        <Card className="mt-4 p-5 text-center">
          <div className="text-lg font-black">Questa è la parte corta.</div>
          <p className="mx-auto mt-1.5 max-w-xl text-sm text-ink-soft">
            Dentro c'è la versione completa — il portiere, i senza voto, le espulsioni, il conto di
            ogni singolo voto — insieme al campionato vero con le nostre pagelle di ogni partita.
            L'account è gratis.
          </p>
          <Link
            to="/"
            className="mt-4 inline-block rounded-xl bg-ink px-5 py-2.5 text-sm font-bold text-paper hover:opacity-90"
          >
            Entra o crea un account →
          </Link>
        </Card>

        <p className="mt-4 text-center text-xs text-ink-faint">
          Tutte le cifre di questa pagina sono misurate sulla stagione {VOTO.stagione}, l'ultima
          conclusa.
        </p>
      </div>
    </div>
  );
}

function Blocco({ titolo, children }: { titolo: string; children: React.ReactNode }) {
  return (
    <Card className="p-5">
      <h2 className="font-cond text-xl font-bold text-ink">{titolo}</h2>
      <div className="mt-2 space-y-3 text-sm leading-relaxed text-ink-soft">{children}</div>
    </Card>
  );
}

function Passo({ n, titolo, children }: { n: number; titolo: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand/15 text-xs font-bold text-brand-strong">
        {n}
      </span>
      <div>
        <div className="font-semibold text-ink">{titolo}</div>
        <div className="mt-0.5">{children}</div>
      </div>
    </li>
  );
}

function Numero({ valore, testo }: { valore: string; testo: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface-2 p-3">
      <div className="font-cond text-2xl font-bold text-ink">{valore}</div>
      <div className="mt-0.5 text-xs text-ink-faint">{testo}</div>
    </div>
  );
}

/** Un caso vero, ridotto all'osso: due voti a confronto e la ragione. Il secondo
 *  è di proposito uno in cui la pagella sta PIÙ IN ALTO della nostra — una
 *  vetrina di soli casi favorevoli non è un argomento, è una réclame. */
function Caso({
  partita,
  chi,
  noi,
  loro,
  perche,
}: {
  partita: string;
  chi: string;
  noi: string;
  loro: string;
  perche: string;
}) {
  return (
    <div className="rounded-xl border border-line bg-surface-2 p-3">
      <div className="text-[11px] font-bold uppercase tracking-wide text-ink-faint">{partita}</div>
      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
        <span className="font-semibold text-ink">{chi}</span>
        <span className="rounded-lg bg-brand/15 px-2 py-1 font-mono font-bold text-brand-strong">
          noi {noi}
        </span>
        <span className="rounded-lg border border-line px-2 py-1 font-mono text-ink-soft">
          pagella {loro}
        </span>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-ink-soft">{perche}</p>
    </div>
  );
}
