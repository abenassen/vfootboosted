import { useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Badge, Card, SectionTitle } from '../components/ui';
import { BENCHMARK_URL, VOTO, useBenchmarkAvailable } from '../content/votoPuro';

/** COME NASCE IL VOTO PURO — la pagina di consultazione.
 *
 *  Perché esiste. Il voto puro è il pezzo del sito che nessun altro fa così: non
 *  è un giudizio umano né un voto comprato da un fornitore, è un calcolo sui dati
 *  della partita. Ma proprio per questo a volte NON assomiglia alla pagella del
 *  giornale, e un utente che vede il suo attaccante a 6 dopo un gol pensa a un
 *  errore del sito. Questa pagina è la risposta: dice come si arriva al numero,
 *  dove ci si allontana dal fantacalcio tradizionale e perché.
 *
 *  Contenuto FERMO, non chiamate al backend: sono affermazioni sul modello, non
 *  dati vivi, e un endpoint che le ricalcolasse a ogni apertura costerebbe
 *  secondi di server per ripetere gli stessi numeri. Le misure di sintesi — le
 *  quote d'accordo, lo scarto, la correlazione col rating indipendente — stanno
 *  in `content/votoPuro.ts` insieme all'istruzione per rifarle, perché le mostra
 *  anche la pagina pubblica (VotoPubblicoPage) e due copie a mano divergono al
 *  primo ritaraggio. Gli esempi e le cifre di dettaglio restano qui: appartengono
 *  a questa pagina e a nessun'altra.
 *
 *  Una scelta di sostanza sugli ESEMPI. Divergenza non vuol dire «diversi dalla
 *  Redazione»: fantacalcio.it pubblica due voti (Redazione e Statistico) e quando
 *  quei due non concordano, stare in mezzo non è divergere. Quindi ogni caso qui
 *  sotto è FUORI DA ENTRAMBE le letture di almeno un punto — lo stesso criterio di
 *  voto_benchmark/divergenze.html. Sono esclusi i casi con espulsione o autogol,
 *  dove il divario è gonfiato dalla contabilità (lo Statistico mette la penalità
 *  nel voto base, noi nel malus) e non da una lettura diversa della partita: è la
 *  trappola in cui era finita la prima stesura di questa pagina, con Cambiaso alla
 *  1ª giornata (Δ +2,0, ma 0,6 di quel divario è un rosso contato altrove).
 *
 *  Il registro è quello di chi gioca: «quanto era difficile il tiro», non «xG»;
 *  «quanto si stacca dalla media del suo ruolo», non «z-score». Le uniche cifre
 *  citate sono quelle che si possono controllare guardando una partita.
 */

const SECTIONS = [
  { id: 'cose', label: "Che cos'è" },
  { id: 'dati', label: 'Da dove vengono i dati' },
  { id: 'passi', label: 'Come si arriva al voto' },
  { id: 'peso', label: 'Che cosa pesa' },
  { id: 'errori', label: 'Espulsioni, autogol, rigori sbagliati' },
  { id: 'zona', label: 'Il pericolo nella tua zona' },
  { id: 'portiere', label: 'Il portiere' },
  { id: 'sv', label: 'Quando non c’è voto' },
  { id: 'differenze', label: 'Le differenze coi voti usuali' },
  { id: 'accordo', label: 'Quanto siamo d’accordo' },
  { id: 'limiti', label: 'Quello che non sappiamo' },
];

export default function VotoPuroPage() {
  const { hash } = useLocation();
  const benchmark = useBenchmarkAvailable();
  // Arrivare con un'ancora (dal dettaglio di un voto, o da un link condiviso) deve
  // portare al paragrafo, non in cima: la pagina è lunga e chi ci arriva da una
  // pagella ha una domanda precisa.
  useEffect(() => {
    if (!hash) return;
    const el = document.getElementById(hash.slice(1));
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [hash]);

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 pb-16">
      <header className="space-y-2">
        <h1 className="font-cond text-2xl font-bold text-ink">Come nasce il voto puro</h1>
        <p className="text-sm text-ink-soft">
          Il voto puro è la nostra pagella: lo calcoliamo dai dati di quello che il giocatore ha
          fatto in campo, partita per partita. Nessuno lo assegna a mano e non lo compriamo da
          nessuno. Questa pagina spiega come si arriva al numero — e perché a volte non è quello che
          avresti letto sul giornale.
        </p>
      </header>

      {/* L'indice non è decorazione: è una pagina di consultazione, e quasi
          nessuno la leggerà dall'inizio. */}
      <Card className="p-4">
        <SectionTitle>In questa pagina</SectionTitle>
        <nav className="mt-2 flex flex-wrap gap-1.5">
          {SECTIONS.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className="rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-xs font-semibold text-ink-soft hover:bg-line/50"
            >
              {s.label}
            </a>
          ))}
        </nav>
      </Card>

      <Section id="cose" title="Che cos'è, e che cosa non è">
        <p>
          Nei sistemi di voto usuali il punteggio di un giocatore è fatto di due pezzi:{' '}
          <b className="text-ink">voto puro</b> + <b className="text-ink">bonus e malus</b>. I bonus
          e i malus sono gli episodi che hanno già un prezzo scritto — il gol vale +3, l'assist +1,
          l'ammonizione −0,5 — e quelli li applichiamo esattamente come li applicano tutti.
        </p>
        <p>
          Il voto puro è l'altra metà: <i>quanto bene ha giocato</i>. È il numero che una pagella dà
          a prescindere dai bonus, e a noi lo dicono i dati della partita. Da qui viene la
          differenza principale con l'abitudine di tutti: la pagella di un giornale parte da
          un'impressione e la traduce in un numero, noi partiamo da quaranta misure di quello che è
          successo in campo e le trasformiamo in un numero. Sullo stesso gol i due percorsi arrivano
          quasi sempre vicini, ma non sempre — e quando non ci arrivano, i motivi sono sempre gli
          stessi, elencati{' '}
          <a href="#differenze" className="font-semibold text-accent underline decoration-dotted">
            più sotto
          </a>
          .
        </p>
        <Callout>
          Il voto puro <b>non contiene</b> il gol, l'assist o il cartellino: quelli si sommano dopo,
          in chiaro. Se un attaccante ha 6,0 di voto puro e ha segnato, il suo fantavoto è 9,0.
          Contare il gol automaticamente nel voto puro sarebbe un doppio conteggio, e non lo
          facciamo. Noi valutiamo invece <b>quanto merito ci sia in quel gol</b>.
        </Callout>
        {/* IL RIFERIMENTO, DETTO UNA VOLTA SOLA E SUBITO. Sta qui e non più in
            fondo perché le pastiglie «Redazione» e «Statistico» compaiono già nel
            primo esempio, tre paragrafi sotto: chi leggeva le trovava senza sapere
            di chi si stesse parlando, e scopriva a metà pagina che erano due voti
            dello stesso sito. */}
        <Callout>
          Il metro di confronto di questa pagina è <b className="text-ink">fantacalcio.it</b>, il
          riferimento più usato in Italia, che pubblica <b>due</b> voti per ogni giocatore: la{' '}
          <b>Redazione</b> — la pagella scritta da una persona — e lo <b>Statistico</b>, il loro
          voto calcolato. Ogni cifra e ogni esempio qui sotto è misurato contro tutt'e due.
        </Callout>
        <p className="text-xs text-ink-faint">
          Nelle leghe in modalità <b>Aura</b> il confronto si gioca sui duelli di zona: usa gli
          stessi dati, ma non passa dal voto. Tutto ciò che segue riguarda le leghe <b>classic</b>.
        </p>
      </Section>

      <Section id="dati" title="Da dove vengono i dati">
        <p>
          Per ogni partita raccogliamo, giocatore per giocatore, che cosa ha fatto e{' '}
          <b className="text-ink">in che parte del campo</b> l'ha fatto: il campo è diviso in venti
          zone e ogni tocco, duello, tiro, contrasto e intervento finisce nella zona in cui è
          avvenuto.
        </p>
        <p>
          Nel calcolo entrano una quarantina di misure. Alcune sono ovvie — tiri, passaggi riusciti,
          duelli vinti e persi, contrasti, intercetti, respinte, palloni recuperati, dribbling.
          Altre contano <i>quanto valeva</i> un gesto e non solo che è stato fatto: quanto era
          difficile il tiro da dove è partito, dove è finito rispetto a com'era piazzato il
          portiere, quanto era limpida l'occasione creata per un compagno. E ci sono gli errori, che
          pesano in negativo: il pallone perso male, il dribbling subito, l'errore che concede un
          tiro, quello che concede un gol, il rigore regalato.
        </p>
        <p className="text-xs text-ink-faint">
          Le zone servono a una cosa che nessuna somma di totali può fare: sapere{' '}
          <i>chi era dove</i> quando l'avversario è arrivato al tiro. È tutto il capitolo{' '}
          <a href="#zona" className="font-semibold text-accent underline decoration-dotted">
            pericolo nella tua zona
          </a>
          .
        </p>
      </Section>

      <Section id="passi" title="Come si arriva al voto, in quattro passi">
        <ol className="space-y-3">
          <Step n={1} title="Ogni misura viene confrontata con la norma">
            Dieci duelli vinti non dicono niente da soli: dipende da quanti ne vince chi gioca in
            quel ruolo. Quindi ogni misura viene letta come «quanto si stacca da quello che fa un
            giocatore normale» — sopra o sotto la media. Le prestazioni fuori scala vengono
            accorciate un po', perché un dato mostruoso in una singola voce non deve da solo
            decidere il voto.
          </Step>
          <Step n={2} title="Ogni misura ha il suo peso">
            I pesi sono decisi da noi, uno per uno, e sono la parte «di autore» del modello: dicono
            quanto conta calciare bene rispetto a vincere un duello, o quanto costa un errore. Sono
            tarati confrontando i risultati con una stagione intera di pagelle vere, ma non sono una
            copia delle pagelle: dove abbiamo scelto di leggere il calcio in modo diverso, lo
            abbiamo tenuto.
          </Step>
          <Step n={3} title="La somma diventa un voto in scala di pagella">
            Tutte le voci pesate si sommano in un unico punteggio di prestazione, che poi viene
            confrontato con il suo ruolo: la media di ogni ruolo è <b className="text-ink">6</b>, e
            da lì si sale o si scende in proporzione a quanto la partita si stacca dalla norma. Il
            risultato viene arrotondato al mezzo voto, come una pagella, e sta tra 3 e 10.
          </Step>
          <Step n={4} title="Le ultime correzioni">
            Chi ha giocato pochi minuti torna verso il 6, perché venti minuti dicono poco: a un'ora
            di gioco il voto vale quasi per intero, a un quarto d'ora conta meno della metà. Poi c'è
            il risultato: un voto alto in una sconfitta scende un po', un voto basso in una vittoria
            sale un po' — <b className="text-ink">mai il contrario</b>, quindi il risultato non
            gonfia nessuno e tempera solo i casi stonati. E infine
            i tre episodi che una pagella non può ignorare — espulsione, autogol, rigore sbagliato —
            che leggiamo{' '}
            <a href="#errori" className="font-semibold text-accent underline decoration-dotted">
              entrando nel merito dell'errore
            </a>
            .
          </Step>
        </ol>
        <Callout>
          Ogni voto è ispezionabile: nelle pagelle di ogni partita, toccando il voto puro si apre il
          conto di quel numero — la media del ruolo, ogni voce che l'ha spostata e di quanto, fino
          al voto finale.
        </Callout>
      </Section>

      <Section id="peso" title="Che cosa alza il voto e che cosa lo abbassa">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl border border-line bg-surface-2 p-3">
            <div className="text-xs font-bold uppercase tracking-wide text-good">Alza</div>
            <ul className="mt-2 list-disc space-y-1.5 pl-4 text-sm text-ink-soft marker:text-ink-faint">
              <li>Come è stato calciato il tiro: dove è finito rispetto a com'era l'occasione.</li>
              <li>Occupare occasioni: tirare da posizioni pericolose, stare nell'area.</li>
              <li>Creare per gli altri, anche quando l'assist non arriva.</li>
              <li>Duelli e duelli aerei vinti, dribbling riusciti, falli subiti.</li>
              <li>Giocare nella metà campo avversaria: portare la squadra avanti.</li>
              <li>Intercetti, respinte, contrasti, salvataggi sulla linea, palloni recuperati.</li>
              <li>Il rigore conquistato — che di solito non paga nulla a chi lo guadagna.</li>
            </ul>
          </div>
          <div className="rounded-xl border border-line bg-surface-2 p-3">
            <div className="text-xs font-bold uppercase tracking-wide text-bad">Abbassa</div>
            <ul className="mt-2 list-disc space-y-1.5 pl-4 text-sm text-ink-soft marker:text-ink-faint">
              <li>Duelli persi, dribbling subiti, duelli aerei persi.</li>
              <li>Palloni perduti: passaggi sbagliati, controlli sbagliati, palla soffiata.</li>
              <li>L'errore che concede un tiro, e — molto di più — quello che concede un gol.</li>
              <li>Il rigore regalato, che di solito non costa nulla a chi lo commette.</li>
              <li>
                Tanti dribbling tentati e pochi riusciti: conta la percentuale, non il tentativo.
              </li>
              <li>Il pericolo passato dalla propria zona (qui sotto).</li>
            </ul>
          </div>
        </div>
        <p className="mt-3 text-xs text-ink-faint">
          Due voci meritano una riga per conto loro, perché il voto puro è <i>l'unico</i> posto in
          cui possono comparire: il rigore conquistato e il rigore concesso non hanno alcun bonus né
          malus nei sistemi di voto usuali. Chi si procura il penalty non prende niente (il +3 va a
          chi lo segna) e chi lo regala non paga niente.
        </p>
      </Section>

      <Section id="errori" title="Espulsioni, autogol, rigori sbagliati: il merito dell'errore">
        <p>
          Su questi tre episodi ci sono già i malus ben noti, e noi li applichiamo intatti: rosso
          −1, autogol −2, rigore sbagliato −3 sul fantavoto. Nel voto puro ne teniamo conto con una
          sottrazione che <b className="text-ink">entra nel merito</b>: quanto è stato grave
          l'evento, e quanto è costato alla squadra — per quanto tempo ha lasciato i compagni in
          inferiorità numerica? C'era un buon motivo per farlo?
        </p>
        <ul className="list-disc space-y-1.5 pl-4 text-sm text-ink-soft marker:text-ink-faint">
          <li>
            <b className="text-ink">L'espulsione</b> pesa per il motivo e per il tempo. Il fallo
            tattico dell'ultimo uomo è il meno colpevole di tutti — è una scelta, spesso a favore
            della squadra; il fallo normale sta in mezzo; condotta violenta, protesta e
            comportamento antisportivo stanno in cima e hanno un'aggravante fissa, perché non sono
            calcio. Il tutto moltiplicato per i minuti giocati in dieci: un rosso al 91' non è un
            rosso al 20'. Così si va da quasi zero a circa due punti di voto — e un cartellino preso
            fuori dal campo, in panchina o a partita finita, non tocca il voto: non ha inciso sulla
            partita.
          </li>
          <li>
            <b className="text-ink">L'autogol</b> non è tutto uguale: distinguiamo la deviazione
            dalla frittata. Se arriva nello stesso istante di un tiro avversario è una palla
            deviata, sfortuna, e il calo è minimo (due decimi); se è un errore in solitaria pesa di
            più (mezzo punto). Per dare un metro: un gol <i>fatto</i> vale circa sette decimi di
            voto, quindi nemmeno l'autogol peggiore arriva a costare quanto una rete rende. Quando
            non abbiamo il tempo al secondo non pretendiamo di distinguere: applichiamo un unico
            calo piccolo, invece di attribuire una gravità che non possiamo misurare.
          </li>
          <li>
            <b className="text-ink">Il rigore sbagliato</b> lo leggiamo prima come tiro: se è stato
            calciato bene, quel merito resta. Il calo aggiuntivo dipende dal peso dell'errore, non
            dall'errore in sé — vale il doppio se quel gol avrebbe cambiato il risultato finale
            rispetto a quando la partita era già decisa.
          </li>
        </ul>
        <p className="text-xs text-ink-faint">
          È la stessa regola che vale in tutto il modello: non si paga <i>il fatto</i>, si legge il
          merito dentro il fatto. Vale anche al contrario — il gol non entra nel voto come «gol» ma
          per come è stato calciato, e il rigore parato per quanto era difficile.
        </p>
      </Section>

      <Section id="zona" title="Il pericolo nella tua zona">
        <p>
          Il problema dei difensori, in due righe: sotto assedio un difensore respinge, intercetta e
          contrasta più del solito. Se contassimo solo il volume di quello che fa, una difesa
          travolta uscirebbe con voti alti. Se invece abbassassimo il voto a tutta la difesa quando
          la squadra prende gol, puniremmo in blocco anche chi ha tenuto la sua parte di campo — che
          è quello che una pagella tende a fare.
        </p>
        <p>
          La nostra strada è più precisa:{' '}
          <b className="text-ink">ogni tiro concesso viene addebitato a chi era in quella zona</b>,
          in proporzione a quanto ci giocava, non a tutti. Metà dell'addebito guarda com'è finita
          (gol o parata), metà quanto era pericoloso il tiro. Un tiro debole da lontano costa quasi
          niente; un'occasione limpida costa mezza rete anche se il portiere la para. Il portiere
          non entra nella spartizione: ha il suo conto.
        </p>
        <ZoneIllustration />
        <p>
          C'è un'asimmetria voluta: il pericolo che <i>è</i> passato dalla tua zona è tuo, il
          pericolo che non è mai arrivato non è necessariamente un tuo merito — può essere che
          l'avversario non fosse in grado di arrivarci. Quindi una partita tranquilla non regala un
          voto alto: lo lascia dov'è.
        </p>
        <Caso
          partita="Cremonese–Como 1-4 · 38ª giornata"
          chi="Bianchetti e Pezzella, i due centrali"
          righe={[
            { chi: 'Bianchetti', noi: 4.0, red: 4.5, stat: 4.5, sofa: 5.4 },
            { chi: 'Pezzella', noi: 5.5, red: 4.5, stat: 4.0, sofa: 6.7 },
          ]}
          perche="Le pagelle danno lo stesso voto a entrambi: la difesa ha preso quattro gol. Noi li separiamo di un voto e mezzo, perché il rigore lo concede Bianchetti ed è dalla sua parte che passa la maggior parte del pericolo. Il rating di SofaScore, che non entra nel nostro calcolo, mette i due nello stesso ordine (5,4 e 6,7)."
        />
        <p className="text-xs text-ink-faint">
          Nella stagione {VOTO.stagione} è andata così in 17 partite: due difensori della stessa difesa, lo
          stesso voto dalla Redazione, e da noi più di un voto e mezzo di differenza. Non è un caso
          limite: è il motivo per cui un difensore, da noi, può prendere 6,5 in una serata da tre
          gol presi.
        </p>
      </Section>

      <Section id="portiere" title="Il portiere ha un calcolo suo">
        <p>
          Un portiere non fa quasi nessuna delle cose che misuriamo agli altri, quindi ha un conto
          separato. Il cuore è una domanda sola:{' '}
          <b className="text-ink">
            quanto valevano i tiri che ha affrontato, e quanti gol ha preso?
          </b>{' '}
          Se i tiri nella sua porta valevano due gol e ne ha preso uno, ha guadagnato un gol alla
          sua squadra. Se valevano mezzo gol e ne ha preso uno, l'ha perso. Ogni tiro pesa per
          quanto era difficile pararlo: un tiro angolato da dentro l'area non vale un tiro da trenta
          metri.
        </p>
        <p>Attorno a questo:</p>
        <ul className="list-disc space-y-1.5 pl-4 text-sm text-ink-soft marker:text-ink-faint">
          <li>
            <b className="text-ink">Le parate</b> contano, e quelle su tiri da dentro l'area contano
            quasi il doppio delle altre.
          </li>
          <li>
            <b className="text-ink">Le uscite alte</b> — il comando dell'area su cross e mischie —
            valgono.
          </li>
          <li>
            <b className="text-ink">La papera</b> — l'errore che porta a un gol — è il malus più
            pesante del ruolo.
          </li>
          <li>
            <b className="text-ink">I gol presi non entrano nel voto</b>: ogni gol preso è già −1
            sul fantavoto. Metterlo anche nel voto puro sarebbe contarlo due volte, e il portiere di
            una squadra che perde 4-0 sarebbe condannato in partenza.
          </li>
          <li>
            <b className="text-ink">L'autogol di un compagno pesa per quanto era parabile.</b> Un
            pallone messo dentro da un proprio difensore non è un tiro che il portiere ha
            affrontato, quindi non gli costa un gol intero: gli costa quello che valeva. Se era
            imparabile non paga quasi nulla; se era un pallone da prendere, paga. E se la colpa è
            sua — il retropassaggio che si lascia sfuggire — la paga dov'è giusto, nel malus
            dell'errore che porta a un gol.
          </li>
          <li>
            <b className="text-ink">Il rigore parato non ha un premio fisso</b>: entra nel conto per
            quanto era difficile pararlo — un rigore angolato e forte vale la metà in più di uno
            debole. Il +3 di bonus lo prende comunque, come dappertutto.
          </li>
          <li>
            <b className="text-ink">Se non ha avuto niente da fare, il voto resta vicino al 6.</b>{' '}
            Un portiere che affronta un tiro solo e lo prende non ha giocato una brutta partita: non
            ha giocato una partita giudicabile. Sotto i quattro tiri in porta affrontati (la mediana
            della Serie A) il giudizio viene smorzato in proporzione.
          </li>
        </ul>
        <div className="space-y-2">
          <Caso
            partita="Cremonese–Genoa 0-0 · 25ª giornata"
            chi="Bijlow"
            righe={[{ chi: '', noi: 8.0, red: 6.5, stat: 6.5, sofa: 10 }]}
            compatto
            perche="Porta inviolata con otto parate, sette dentro l'area, in una partita in cui il pareggio è merito suo. Le due colonne di fantacalcio.it lo mettono a 6,5: uno 0-0 non fa notizia."
          />
          <Caso
            partita="Torino–Cagliari 1-2 · 17ª giornata"
            chi="Caprile"
            righe={[{ chi: '', noi: 8.0, red: 6.5, stat: 7.0, sofa: 9.1 }]}
            compatto
            perche="Nove parate, sei su tiri da dentro l'area, un gol preso: i tiri che ha affrontato valevano due gol e mezzo più di quello che gli è entrato."
          />
          <Caso
            partita="Inter–Verona 1-1 · 37ª giornata"
            chi="Montipò"
            righe={[{ chi: '', noi: 6.5, red: 7.5, stat: 7.5, sofa: 7.4 }]}
            compatto
            invertito
            perche="Cinque parate su sei tiri, e l'unico gol è l'autogol di un compagno — che gli addebitiamo solo per quanto era parabile, cioè quasi niente. Restiamo mezzo punto sotto perché i cinque palloni che ha parato valevano 0,64 gol in tutto: le pagelle contano gli interventi, noi quanto valevano. È la differenza di lettura, e qui il nostro conto è quello di minoranza."
          />
          <Caso
            partita="Sassuolo–Fiorentina 3-1 · 14ª giornata"
            chi="De Gea"
            righe={[{ chi: '', noi: 3.5, red: 4.5, stat: 4.0, sofa: 4.1 }]}
            compatto
            perche="Due errori che portano a un gol nella stessa partita, e due gol in più di quanto valessero i tiri affrontati: il nostro voto più basso della stagione tra i portieri. Qui pagelle, rating e noi diciamo la stessa cosa."
          />
        </div>
        <p className="text-xs text-ink-faint">
          Il portiere resta il ruolo in cui ci discostiamo di più, e lo diciamo volentieri: su una
          stagione il nostro voto medio è 0,13 sotto quello delle pagelle. Il motivo è quello che si
          vede negli esempi — noi paghiamo il saldo tra i tiri affrontati e i gol presi, loro
          leggono anche lo spettacolo delle parate.
        </p>
      </Section>

      <Section id="sv" title="Quando non c'è voto (s.v.)">
        <p>
          Chi entra per pochi minuti e tocca pochi palloni non prende un voto: prende{' '}
          <b className="text-ink">s.v.</b>, e in formazione lo sostituisce un altro. Da noi non è un
          giudizio ma <b className="text-ink">una regola scritta prima</b>, uguale per tutti e
          verificabile sul tabellino: due numeri — i minuti giocati e i palloni toccati — e un
          elenco chiuso di episodi che impongono comunque il voto. Non c'è nessun caso in cui
          decidiamo lì per lì.
        </p>
        <ul className="list-disc space-y-1.5 pl-4 text-sm text-ink-soft marker:text-ink-faint">
          <li>
            dai <b className="text-ink">16 minuti</b> in su il voto c'è sempre, anche se ha visto
            poco il pallone: chi sta in campo un quarto d'ora viene giudicato — magari male, ma
            giudicato;
          </li>
          <li>
            tra i 14 e i 16 minuti serve anche un minimo di coinvolgimento: almeno sei palloni
            giocati;
          </li>
          <li>sotto i 14 minuti, di norma, è senza voto;</li>
          <li>
            ma chi fa gol, assist, autogol, sbaglia un rigore o si fa espellere ha{' '}
            <b className="text-ink">sempre</b> un voto, anche dopo due minuti: ha deciso qualcosa.
            L'ammonizione no — su quella le pagelle non tacciono e noi neppure, ma non basta a
            imporre un voto a chi ha giocato cinque minuti.
          </li>
        </ul>
        <p className="text-xs text-ink-faint">
          Sui senza voto arriviamo alla stessa conclusione nel <b className="text-ink">98,2%</b>{' '}
          delle presenze della stagione scorsa. Il disaccordo è tutto nei subentrati tra i 12 e i 16
          minuti, cioè esattamente dove una pagella decide caso per caso e noi invece applichiamo la
          regola: sopra i 16 minuti nessuno tace più, sotto i 12 tacciono quasi tutti.
        </p>
      </Section>

      <Section id="differenze" title="Le differenze tipiche coi voti usuali">
        <p>
          Queste sono le discrepanze che tornano più spesso. Sono tutte volute: nascono da una
          scelta su come leggere il calcio, non da un difetto del calcolo — e l'ultima raccoglie i
          casi su cui si discute di più.
        </p>
        <Callout>
          Come sono scelti gli esempi. Quando le due colonne di fantacalcio.it non concordano tra
          loro, stare in mezzo non è divergere: qui sotto ci sono quindi solo partite vere del
          {VOTO.stagione} in cui il nostro voto sta <b>fuori da entrambe</b> di almeno un punto. C'è anche
          il rating di SofaScore, come terzo giudice indipendente: non entra nel nostro calcolo, e
          serve a vedere chi ha ragione quando divergiamo.
        </Callout>

        <Differenza titolo="1. Il gol non vale un voto fisso">
          <p>
            Nei voti usuali il gol è quasi un bonus extra sul voto puro: tra gli attaccanti che
            hanno segnato una volta, la Redazione di fantacalcio.it ha scritto{' '}
            <b className="text-ink">esattamente 7,0 in 261 casi su 357</b> (media 7,03, con
            oscillazioni minime). Noi teniamo una media vicina — 6,86 — ma con il doppio della
            dispersione (qualcuno prenderà 6, qualcuno prenderà 8), perché al di là del gol
            continuiamo a valutare l'intera partita.
          </p>
          <Caso
            partita="Juventus–Parma 2-0 · 1ª giornata"
            chi="Vlahović"
            righe={[{ chi: '', noi: 6.0, red: 7.0, stat: 7.0, sofa: 7.2 }]}
            compatto
            perche="Entra e segna, in dieci minuti. Il gol vale +3 e il suo fantavoto è 9,0 come per tutti: ma di quei dieci minuti non sappiamo niente altro, e un voto puro di 7 sarebbe una prestazione che non abbiamo visto. Il voto puro resta 6."
          />
          <Caso
            partita="Pisa–Napoli 0-3 · 37ª giornata"
            chi="Rrahmani, difensore"
            righe={[{ chi: '', noi: 8.5, red: 7.0, stat: 7.0, sofa: 9.3 }]}
            compatto
            perche="Qui siamo noi ad andare oltre la pagella: un gol, due palloni buoni serviti ai compagni, porta inviolata e una partita giocata alta. Il 7 della pagella è la tariffa del gol; l'8,5 è il resto della serata."
          />
        </Differenza>

        <Differenza titolo="2. Chi crea e non viene ripagato">
          <p>
            L'assist, di solito, esiste solo se il compagno segna. Nel voto puro l'occasione
            creata vale anche quando finisce male, perché il passaggio è stato fatto: è la voce che
            più spesso ci porta sopra le due pagelle.
          </p>
          <Caso
            partita="Como–Napoli 0-0 · 35ª giornata"
            chi="De Bruyne"
            righe={[{ chi: '', noi: 6.5, red: 5.0, stat: 5.0, sofa: 7.1 }]}
            compatto
            perche="Un'occasione limpida servita a un compagno, altri palloni buoni e un'ora di partita senza perdere duelli. Entrambe le colonne di fantacalcio.it lo mettono a 5,0: in uno 0-0 chi crea e non viene ripagato non lascia traccia."
          />
          <Caso
            partita="Atalanta–Pisa 1-1 · 1ª giornata"
            chi="Bellanova"
            righe={[{ chi: '', noi: 7.0, red: 5.5, stat: 5.5, sofa: 6.8 }]}
            compatto
            perche="Un terzino che tira in porta, crea per i compagni e non concede pericoli dalla sua fascia: per noi 7, per le pagelle un anonimo 5,5."
          />
        </Differenza>

        <Differenza titolo="3. Il voto non segue il risultato">
          <p>
            Una pagella legge anche il risultato: chi perde 0-3 raramente prende più di 6, chi vince
            prende di più. Noi guardiamo il risultato solo per <i>temperare</i> i voti stonati (alto
            in una sconfitta, basso in una vittoria) e mai per esaltarli: per quanto pesante sia
            stata la sconfitta, una buona partita resta una buona partita. Il rovescio è che un
            difensore o un centrocampista di una squadra in difficoltà, se ha tenuto la sua zona,
            resta alto.
          </p>
          <Caso
            partita="Verona–Inter 1-2 · 10ª giornata"
            chi="Bastoni"
            righe={[{ chi: '', noi: 7.0, red: 5.5, stat: 5.5, sofa: 8.1 }]}
            compatto
            perche="Centododici palloni giocati, settantadue passaggi riusciti su ottantatré, sei duelli aerei vinti, e il gol subito lontano dalla sua zona. Le pagelle lo tengono a 5,5 in una partita vinta ma sofferta."
          />
        </Differenza>

        <Differenza titolo="4. Gli errori hanno un prezzo, anche senza cartellino">
          <p>
            Il pallone perso male da cui nasce il gol avversario, il dribbling subito, il rigore
            regalato: di norma non c'è nessun malus per queste cose, e nella pagella si
            vedono solo se il giornalista ha deciso di vederle. Da noi entrano nel conto sempre, con
            un peso proporzionato al danno — l'errore che porta a un gol è la voce negativa più
            pesante di tutte, dopo l'espulsione.
          </p>
        </Differenza>

        <Differenza titolo="5. I casi più discussi">
          <p>
            Ci sono partite in cui la nostra lettura è quella di minoranza: la diamo diversa dalle
            pagelle <i>e</i> dal rating indipendente. Il caso tipico è l'attaccante che segna in una
            squadra travolta — il gol è suo e glielo paghiamo per intero col bonus, ma la mezz'ora
            di gioco intorno al gol resta quella di una serata perduta. Sono i casi che abbiamo
            aperto uno per uno mentre sceglievamo i pesi: li abbiamo soppesati con cura, e la
            lettura che ne è uscita è quella che leggi qui.
          </p>
          <Caso
            partita="Inter–Pisa 6-2 · 22ª giornata"
            chi="Moreo"
            righe={[{ chi: '', noi: 6.5, red: 7.5, stat: 7.5, sofa: 8.7 }]}
            compatto
            invertito
            perche="Due gol nel 6-2 dell'Inter, e un nostro 6,5 di voto puro — con i due gol il fantavoto è 12,5, come per tutti. Nel voto pesano il pericolo passato dalla sua zona e i quattro gol di scarto che la sua squadra aveva mentre lui era in campo: per le pagelle e per il rating due gol valgono la serata, per noi la raccontano solo in parte."
          />
        </Differenza>
      </Section>

      <Section id="accordo" title="Quanto siamo d'accordo con le pagelle, in numeri">
        <p>
          Non abbiamo lavorato alla cieca: a ogni messa a punto abbiamo rigiocato l'ultima stagione
          conclusa e confrontato tutti i nostri voti con i due di fantacalcio.it. Sulla{' '}
          {VOTO.stagione} sono <b className="text-ink">{VOTO.pagelle} pagelle</b> confrontate una per
          una.
        </p>
        <div className="grid gap-2 sm:grid-cols-3">
          <Numero valore={VOTO.entroMezzo} testo="dei nostri voti è entro mezzo punto dalla pagella" />
          <Numero valore={VOTO.entroUno} testo="è entro un punto" />
          <Numero
            valore={VOTO.divergenze.casi}
            testo={`i casi (${VOTO.divergenze.quota}) fuori da entrambe le letture di almeno un punto: ${VOTO.divergenze.alto} verso l'alto, ${VOTO.divergenze.basso} verso il basso`}
          />
        </div>
        <p>
          Lo scarto medio è {VOTO.scartoMedio} punti: siamo <i>vicini</i> alle pagelle, non
          allineati. Per ruolo:
          0,33 portieri e centrocampisti, 0,34 i difensori, 0,35 gli attaccanti. E la parte in cui
          non siamo allineati è quella che ci interessa, perché è dove i dati dicono qualcosa che
          l'impressione non aveva registrato.
        </p>
        <p>
          Chi ha ragione, quando divergiamo? Un metro indipendente è il{' '}
          <b className="text-ink">rating di SofaScore</b>: il punteggio che una piattaforma esterna
          e consolidata calcola sugli eventi della partita, e che non entra mai nel nostro modello.
          Qui sotto l'accordo con quel rating (1 = identico) del nostro voto e delle due colonne di
          fantacalcio.it:
        </p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-ink-faint">
                <th className="py-1.5 pr-3 font-semibold">Ruolo</th>
                <th className="py-1.5 pr-3 text-right font-semibold">Noi</th>
                <th className="py-1.5 pr-3 text-right font-semibold">Redazione</th>
                <th className="py-1.5 text-right font-semibold">Statistico</th>
              </tr>
            </thead>
            <tbody className="text-ink-soft">
              {VOTO.correlazione.map((r) => (
                <tr key={r.ruolo} className="border-t border-line">
                  <td className="py-1.5 pr-3">{r.ruolo}</td>
                  <td className="py-1.5 pr-3 text-right font-mono font-semibold text-good">
                    {r.noi}
                  </td>
                  <td className="py-1.5 pr-3 text-right font-mono">{r.redazione}</td>
                  <td className="py-1.5 text-right font-mono">{r.statistico}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-ink-faint">
          Misurato sui giocatori che non hanno segnato: il gol mette tutti d'accordo e coprirebbe il
          resto. Da leggere per quello che è: non dice che i nostri voti sono «giusti», dice che
          quando ci allontaniamo dalla pagella non lo facciamo a caso. Le due colonne di
          fantacalcio.it sono d'altra parte vicinissime tra loro — d'accordo entro mezzo voto nel
          99,3% dei casi — quindi il loro Statistico resta fortemente influenzato dalla redazione
          tradizionale.
        </p>
        {/* Le carte in tavola: non un riassunto del confronto, il confronto. */}
        {benchmark ? (
          <Callout>
            Non ti fidare di queste cifre: <b className="text-ink">guardale</b>. Il confronto è
            pubblicato per intero, giornata per giornata —{' '}
            <a
              href={BENCHMARK_URL}
              className="font-semibold text-accent underline decoration-dotted"
              target="_blank"
              rel="noreferrer"
            >
              i nostri voti a fianco di quelli di fantacalcio.it
            </a>
            , con l'elenco di dove ci allontaniamo da entrambe le loro letture. È l'intera stagione
            {VOTO.stagione}, senza scegliere gli esempi.
          </Callout>
        ) : null}
      </Section>

      <Section id="limiti" title="Quello che il voto puro non sa">
        <p>
          Un modello onesto dice anche dove è debole. Queste cose il nostro voto non le vede, e non
          finge di vederle:
        </p>
        <ul className="list-disc space-y-1.5 pl-4 text-sm text-ink-soft marker:text-ink-faint">
          <li>
            <b className="text-ink">Il compito tattico.</b> Non sappiamo che cosa gli aveva chiesto
            l'allenatore. Un mediano mandato a spezzare il gioco in una partita da difendere farà
            numeri da partita anonima.
          </li>
          <li>
            <b className="text-ink">Quello che non si conta.</b> Il movimento che libera il
            compagno, la copertura preventiva, il tempo perso con intelligenza: sono nel calcio e
            non sono nei dati. Per i difensori ci aiutiamo con un indicatore di valore difensivo, ma
            resta una stima.
          </li>
          <li>
            <b className="text-ink">Siamo prudenti.</b> Il {VOTO.quotaSei.noi} dei nostri voti è
            esattamente 6, contro il {VOTO.quotaSei.pagelle} delle pagelle: quando i dati non
            dicono niente di netto, noi non
            inventiamo un giudizio. È una scelta, ma vuol dire anche qualche 6 dove un occhio umano
            avrebbe visto una sfumatura.
          </li>
          <li>
            <b className="text-ink">In alto siamo più larghi delle pagelle.</b> Quando un attaccante
            segna e domina arriviamo all'8 più spesso di loro: leggiamo il gol insieme al resto
            della partita, invece di fermarci alla tariffa. È il punto della scala che teniamo più
            d'occhio.
          </li>
          <li>
            <b className="text-ink">I portieri sono il ruolo più difficile</b> e il nostro punto più
            debole: pochi tiri affrontati vogliono dire poca evidenza, e con poca evidenza il voto
            dice poco.
          </li>
          <li>
            <b className="text-ink">Non sappiamo chi è.</b> Il nome, il prezzo e la fama non entrano
            nel calcolo. Un big in giornata da 5,5 prende 5,5.
          </li>
        </ul>
        <Callout>
          Se un voto ti sembra sbagliato, apri il suo dettaglio nella pagella della partita: vedrai
          da quali voci è composto. È il modo migliore per segnalarci un problema — le segnalazioni
          le leggiamo, e pesano sulla prossima messa a punto del modello.
        </Callout>
        <p className="text-xs text-ink-faint">
          Tutte le cifre e i confronti di questa pagina sono stati misurati sulla stagione{' '}
          {VOTO.stagione}, l'ultima conclusa, sulle {VOTO.pagelle} presenze che abbiamo potuto
          appaiare con entrambe le colonne di fantacalcio.it.
        </p>
      </Section>

      <div className="pt-2 text-center text-sm">
        <Link to="/serie-a" className="font-semibold text-accent underline decoration-dotted">
          Vai alle pagelle delle partite →
        </Link>
      </div>
    </div>
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    // scroll-mt: la barra in alto è fissa, e senza questo un'ancora finisce
    // sotto di essa — il titolo del paragrafo resta nascosto proprio a chi ci è
    // appena arrivato.
    <Card id={id} className="scroll-mt-20 p-4">
      <h2 className="font-cond text-lg font-bold text-ink">{title}</h2>
      <div className="mt-2 space-y-3 text-sm leading-relaxed text-ink-soft">{children}</div>
    </Card>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand/15 text-xs font-bold text-brand-strong">
        {n}
      </span>
      <div>
        <div className="font-semibold text-ink">{title}</div>
        <div className="mt-0.5">{children}</div>
      </div>
    </li>
  );
}

function Callout({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-surface-2 p-3 text-sm text-ink-soft">
      {children}
    </div>
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

/** Un caso reale: la partita, chi, i voti a confronto e la ragione della
 *  differenza. I voti stanno su una riga sola di pastiglie perché la domanda che
 *  la gente si fa è «di quanto siamo lontani», e la si legge in un colpo d'occhio.
 *  `invertito` marca i casi in cui siamo NOI i più severi o i più probabilmente in
 *  errore: tenerli dentro è ciò che rende la pagina un resoconto e non una vetrina. */
function Caso({
  partita,
  chi,
  righe,
  perche,
  compatto = false,
  invertito = false,
}: {
  partita: string;
  chi: string;
  righe: Array<{
    chi: string;
    noi: number;
    red: number;
    stat?: number;
    sofa?: number;
  }>;
  perche: string;
  compatto?: boolean;
  invertito?: boolean;
}) {
  const fmt = (n: number) => n.toFixed(1).replace('.', ',');
  return (
    <div className="rounded-xl border border-line bg-surface-2 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-xs font-bold uppercase tracking-wide text-ink-faint">{partita}</span>
        {invertito ? <Badge tone="amber">qui la pagella è più alta della nostra</Badge> : null}
      </div>
      {!compatto ? <div className="mt-1 text-sm font-semibold text-ink">{chi}</div> : null}
      <div className="mt-2 space-y-1.5">
        {righe.map((r, i) => (
          <div key={r.chi || i} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
            <span
              className={
                compatto
                  ? 'shrink-0 font-semibold text-ink'
                  : 'w-24 shrink-0 font-semibold text-ink'
              }
            >
              {compatto ? chi : r.chi}
            </span>
            <span className="rounded-lg bg-brand/15 px-2 py-1 font-mono font-bold text-brand-strong">
              noi {fmt(r.noi)}
            </span>
            <span className="rounded-lg border border-line px-2 py-1 font-mono text-ink-soft">
              Redazione {fmt(r.red)}
            </span>
            {r.stat != null ? (
              <span className="rounded-lg border border-line px-2 py-1 font-mono text-ink-soft">
                Statistico {fmt(r.stat)}
              </span>
            ) : null}
            {r.sofa != null ? (
              <span className="rounded-lg border border-line px-2 py-1 font-mono text-ink-faint">
                SofaScore {fmt(r.sofa)}
              </span>
            ) : null}
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs leading-relaxed text-ink-soft">{perche}</p>
    </div>
  );
}

function Differenza({ titolo, children }: { titolo: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2 border-t border-line pt-3 first:border-0 first:pt-0">
      <div className="font-semibold text-ink">{titolo}</div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

/** Le venti zone, con un tiro concesso e l'addebito che si spartisce fra chi era
 *  lì. Disegnata e non descritta perché «in proporzione alla presenza nella zona»
 *  è una frase che si capisce in un secondo se la si vede, e in tre righe se la si
 *  legge. */
function ZoneIllustration() {
  const cols = 5;
  const rows = 4;
  // Il tiro concesso sta nel PROPRIO terzo (colonna 1): è un tiro subito, e
  // disegnarlo a metà campo faceva leggere la figura al contrario.
  const hit = { c: 1, r: 1 };
  const near = [
    { c: 0, r: 1 },
    { c: 2, r: 1 },
    { c: 1, r: 0 },
    { c: 1, r: 2 },
  ];
  return (
    <figure className="rounded-xl border border-line bg-surface-2 p-3">
      {/* Largo quanto una figura e non quanto la pagina: a piena larghezza le
          venti caselle diventavano un muro alto mezzo schermo. */}
      <div className="mx-auto max-w-sm">
        <div className="flex items-center justify-between text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
          <span>la sua porta</span>
          <span>porta avversaria</span>
        </div>
        <div
          className="mt-1 grid gap-1"
          style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
          aria-hidden
        >
          {Array.from({ length: cols * rows }, (_, i) => {
            const c = i % cols;
            const r = Math.floor(i / cols);
            const isHit = c === hit.c && r === hit.r;
            const isNear = near.some((n) => n.c === c && n.r === r);
            return (
              <div
                key={i}
                className={
                  'flex aspect-[4/3] items-center justify-center rounded text-[11px] ' +
                  (isHit ? 'bg-bad/70' : isNear ? 'bg-bad/25' : 'bg-surface')
                }
              >
                {isHit ? '⚽' : null}
              </div>
            );
          })}
        </div>
      </div>
      <figcaption className="mt-2 text-xs text-ink-faint">
        Il tiro concesso parte dalla zona scura. L'addebito va a chi giocava lì, in proporzione a
        quanto ci stava, e in parte alle zone confinanti — così un tiro partito a un metro dal
        confine non finisce sulle spalle del difensore sbagliato. Chi era all'altro lato del campo
        non paga niente.
      </figcaption>
    </figure>
  );
}
