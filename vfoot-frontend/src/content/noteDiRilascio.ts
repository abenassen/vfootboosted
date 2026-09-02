/** LE NOTE DI RILASCIO — che cosa è cambiato, versione per versione.
 *
 *  Perché esiste. Il voto puro si muove: ogni settimana correggiamo qualcosa
 *  perché un caso concreto ci ha mostrato che il modello leggeva male una
 *  partita. Chi gioca però vede solo il risultato — un difensore che questa
 *  settimana prende mezzo punto meno di quanto avrebbe preso la scorsa — e
 *  senza un posto in cui lo scriviamo quel cambiamento sembra un capriccio.
 *  Questa è la pagina in cui lo scriviamo, nella forma in cui i giochi scrivono
 *  le patch: la versione, la data, e per ogni voce il CASO che l'ha provocata.
 *
 *  Non è la striscia «Novità» (`NewsBanner`), che dice una cosa sola e poi si
 *  chiude: quella è l'annuncio, questa è l'archivio. L'annuncio rimanda qui.
 *
 *  DOVE STA IL TESTO, E PERCHÉ QUI. Nel repo, non nel database, per una ragione
 *  precisa: la nota deve viaggiare NELLO STESSO COMMIT della modifica che
 *  descrive. Una nota scritta dall'admin il giorno dopo è una nota che qualche
 *  volta non si scrive, e la voce che manca è sempre quella scomoda. Se la
 *  modifica è in produzione, la sua riga è in produzione con lei.
 *
 *  COME SI SCRIVE UNA VOCE. Dal lato di chi gioca, non dal nostro: «il tuo
 *  difensore prende meno per i duelli vinti», non «duels_won scende a 0.021».
 *  Il campo `caso` porta il fatto verificabile — la partita, il giocatore, il
 *  numero prima e dopo — perché è quello che rende la nota credibile invece che
 *  rassicurante. Dove il cambiamento non nasce da un caso singolo, `caso` si
 *  omette: inventarne uno sarebbe peggio che tacere.
 */

/** Il tipo di voce, che decide colore ed etichetta. Quattro e non di più:
 *  oltre il quarto la categoria smette di orientare e diventa arredamento. */
export type TipoVoce = 'nuovo' | 'bilanciamento' | 'migliorato' | 'corretto';

export type Voce = {
  tipo: TipoVoce;
  /** Che cosa noterai. Una frase, al presente, dal lato di chi legge. */
  testo: string;
  /** Il fatto che l'ha provocata: partita, giocatore, numeri. Facoltativo. */
  caso?: string;
};

export type Rilascio = {
  /** Usata come ancora nell'indirizzo (#v-1-7) e come chiave React. */
  id: string;
  versione: string;
  /** Giorno in cui è arrivata sul sito, per esteso e in italiano. */
  data: string;
  /** Il titolo della patch: una riga che dice che cosa è, non l'elenco. */
  titolo: string;
  /** Due righe di contesto. Facoltative: molte patch non hanno bisogno di
   *  presentazione e l'elenco parla da sé. */
  sommario?: string;
  voci: Voce[];
};

export const ETICHETTE: Record<TipoVoce, string> = {
  nuovo: 'Nuovo',
  bilanciamento: 'Bilanciamento',
  migliorato: 'Migliorato',
  corretto: 'Corretto',
};

/** DALLA PIÙ RECENTE ALLA PIÙ VECCHIA: chi apre la pagina vuole sapere che cosa
 *  è cambiato ADESSO, e l'archeologia la fa scendendo. */
export const RILASCI: Rilascio[] = [
  {
    id: 'v-1-9',
    versione: '1.9',
    data: '2 settembre 2026',
    titolo: 'Il recupero di uno svincolo vale solo nella sua offerta',
    voci: [
      {
        tipo: 'corretto',
        testo:
          'Nel mercato a offerte, i crediti che recuperi svincolando un giocatore contano solo nell’offerta che lo svincola. Prima, offrire poco per uno svincolato lasciando un giocatore pagato molto faceva salire i «disponibili» anche per le altre offerte: se quella veniva superata, il giocatore restava in rosa e quei crediti non arrivavano mai.',
        caso:
          'Una squadra con 47 disponibili offriva 1 per Jiménez svincolando Molina (recupero 25) e si ritrovava con 71 disponibili per Beto. Sulle 185 offerte della prima sessione, 8 superavano il tetto corretto.',
      },
    ],
  },
  {
    id: 'v-1-8',
    versione: '1.8',
    data: '1 settembre 2026',
    titolo: 'Il modificatore difesa, e una ritaratura del voto',
    sommario:
      'Una correzione di regolamento che valeva un punto a giornata a metà delle difese, e la messa a punto del voto puro che ne ha aggiustati quindici casi visti in campo.',
    voci: [
      {
        tipo: 'corretto',
        testo:
          'Il modificatore difesa saltava una banda intera su ogni soglia esatta: una difesa da 6,00 di media non prendeva niente invece di +1, una da 6,25 prendeva 1 invece di 2. Corretto, e applicato anche alle giornate già giocate.',
        caso:
          'La media è (tre difensori + portiere) / 4 su voti a mezzo punto: cade su un multiplo di 0,25 una volta su due. Metà delle difese premiate prendeva un punto in meno del dovuto.',
      },
      {
        tipo: 'bilanciamento',
        testo:
          'La creazione non viene più pagata due volte. I passaggi chiave e le occasioni create raccontavano lo stesso gesto e si sommavano: ora conta il valore del pallone servito, una volta sola.',
        caso:
          'Dimarco in Cagliari-Inter prendeva 7,5 con due voci quasi gemelle nella spiegazione — «occasioni create» +0,69 e «passaggi chiave» +0,60. Ora è 7,0.',
      },
      {
        tipo: 'bilanciamento',
        testo:
          'Per un difensore vale più non perdere un duello che vincerne uno. Perderne uno che porta al gol conta più che vincerne altri nove, e adesso i due versi non pesano uguale.',
        caso:
          'Sposta il voto di 15 difensori sulle prime due giornate. Rrahmani in Genoa-Napoli passa da 7,5 a 7,0: la partita è la stessa, i duelli vinti valgono meno.',
      },
      {
        tipo: 'bilanciamento',
        testo:
          'Tirare conta meno di prima. Premiavamo la conclusione in sé più di quanto la conclusione valga, e i subentrati che entravano a tirare uscivano con voti da protagonisti.',
        caso:
          'Da sola cambia 98 voti su 578. Malen in Lecce-Roma passa da 9,0 a 7,5, Piotrowski in Monza-Udinese da 8,5 a 7,5.',
      },
      {
        tipo: 'bilanciamento',
        testo:
          'Il gol subito pesa per quanto ha cambiato la partita, anche per il portiere. Lo facevamo già a credito di chi segna: le due letture dello stesso gol non possono divergere.',
        caso:
          'Atalanta-Bologna 1-0: unico gol al 90°, su un pallone che il portiere doveva prendere per il 96%. La difficoltà la leggevamo, il momento no.',
      },
      {
        tipo: 'bilanciamento',
        testo:
          'Chi gioca mezz’ora non parte più dal voto di chi ne gioca novanta. Il punto di partenza tiene conto dei minuti, così quello che si legge sotto è tutto e solo quello che il giocatore ha aggiunto.',
      },
      {
        tipo: 'migliorato',
        testo:
          'La spiegazione del voto non nomina più le minuzie. Una voce compare fra i motivi solo se vale almeno un decimo di voto: sotto quella soglia resta sotto «altre voci», col suo nome e col suo numero, ma non si spaccia per una ragione.',
        caso:
          'Quasi metà delle righe mostrate valeva meno di un decimo di voto — «nessun intercetto» compariva sempre e solo al valore minimo per comparire. Ora sono una su otto.',
      },
    ],
  },
  {
    id: 'v-1-7',
    versione: '1.7',
    data: '30 agosto 2026',
    titolo: 'Il gol vale quanto cambia, e il portiere ha il suo metro',
    sommario:
      'La settimana in cui il voto ha smesso di pagare gli episodi a tariffa fissa e ha cominciato a leggerne il peso.',
    voci: [
      {
        tipo: 'bilanciamento',
        testo:
          'Il gol non vale più i minuti di chi lo fa, ma quello che cambia: il pareggio all’90° e il quarto gol di una goleada non sono la stessa rete.',
      },
      {
        tipo: 'bilanciamento',
        testo:
          'L’assist vale come il gol che ha prodotto. Prima il gol lo pesavamo per il suo peso e il passaggio che l’aveva fatto no.',
      },
      {
        tipo: 'bilanciamento',
        testo:
          'Il portiere ordinario parte dal 6,15 e non dal 6, e chi non ha avuto niente da parare non viene più punito per le parate che nessuno gli ha chiesto.',
        caso:
          'Su una stagione il portiere stava 0,13 sotto le pagelle. Si sposta il voto di 166 portieri su 766.',
      },
      {
        tipo: 'bilanciamento',
        testo:
          'Nella goleada subita il voto può scendere sotto la sufficienza; in una vittoria il risultato può portare un voto basso al 6 e non oltre.',
      },
      {
        tipo: 'nuovo',
        testo:
          'Nel voto del portiere si apre la mappa delle parate: quale pallone gli ha fatto il voto, uno per uno.',
      },
      {
        tipo: 'corretto',
        testo:
          'L’autogol contava come una conclusione tentata, quindi regalava un piccolo credito a chi lo segnava.',
        caso: '22 casi su 22 nella stagione scorsa, +0,048 di voto medio.',
      },
      {
        tipo: 'corretto',
        testo:
          'Un tiro murato non vale niente: la difficoltà dell’occasione aveva già scontato il muro, e lo contavamo due volte.',
      },
    ],
  },
  {
    id: 'v-1-6',
    versione: '1.6',
    data: '28 agosto 2026',
    titolo: 'Le probabili formazioni',
    voci: [
      {
        tipo: 'nuovo',
        testo:
          'Chi gioca domenica, prima che qualcuno lo scriva: un pronostico nostro sull’undici di ogni squadra, che indovina tre titolari su quattro.',
      },
      {
        tipo: 'nuovo',
        testo:
          'Quando l’undici previsto arriva anche da SofaScore — fino a tre giorni prima — le due letture si fondono in una.',
      },
      {
        tipo: 'nuovo',
        testo:
          'La striscia «Novità»: quando una versione porta qualcosa che ti riguarda, te lo dice una volta e poi si toglie di mezzo.',
      },
      {
        tipo: 'corretto',
        testo:
          'Nel mercato si può cercare uno svincolato scrivendo la sua squadra, non solo il suo nome.',
      },
      {
        tipo: 'corretto',
        testo: 'Il prezzo di un giocatore mostra la sua storia: senza, non dice se è caro.',
      },
    ],
  },
  {
    id: 'v-1-5',
    versione: '1.5',
    data: '25 agosto 2026',
    titolo: 'Il mercato a offerte, e la prima ritaratura del voto',
    voci: [
      {
        tipo: 'nuovo',
        testo:
          'Mercato a offerte sugli svincolati: apertura e chiusura programmabili, riserva di crediti, e ventiquattr’ore perché qualcuno rilanci.',
      },
      {
        tipo: 'nuovo',
        testo:
          'Scambi fra squadre col prezzo che viaggia col giocatore, e la dote che l’amministratore può assegnare — due mosse che prima si facevano fuori dall’app.',
      },
      {
        tipo: 'nuovo',
        testo:
          '«Se la giornata finisse adesso»: la classifica provvisoria di un turno ancora in corso.',
      },
      {
        tipo: 'bilanciamento',
        testo:
          'Il difensore ordinario non vale 6: il centro del suo ruolo si sposta a 5,91, così il modificatore difesa smette di premiare chiunque abbia quattro difensori.',
      },
      {
        tipo: 'bilanciamento',
        testo: 'Non aver perso un duello valeva più di averne vinti cinque.',
      },
      {
        tipo: 'migliorato',
        testo:
          'La riga «altre N voci» della spiegazione si apre, e ogni voce ha un nome e un numero.',
      },
      {
        tipo: 'corretto',
        testo:
          'Il voto non rimprovera più un tiro che nessuno ha tentato: chi non ha mai calciato non è «uno che ha calciato male».',
      },
    ],
  },
  {
    id: 'v-1-4',
    versione: '1.4',
    data: '22 agosto 2026',
    titolo: 'La formazione sul telefono, e quando si chiude',
    sommario:
      'La pagina che si usa di più era quella che sul telefono funzionava peggio. E la scadenza della formazione è diventata una regola di lega invece di un’ora unica per tutti.',
    voci: [
      {
        tipo: 'nuovo',
        testo:
          'La formazione si chiude alla prima partita di un tuo giocatore, non a un’ora fissa: la scadenza è la tua, non quella della giornata.',
      },
      {
        tipo: 'nuovo',
        testo: 'In classic la formazione degli altri si può guardare: vederla non dà vantaggio.',
      },
      {
        tipo: 'migliorato',
        testo:
          'Campo, panchina, ordine dei cambi e Salva rifatti per il dito: le freccette erano larghe undici pixel, ed è per questo che sembrava impossibile cambiare l’ordine.',
      },
      {
        tipo: 'corretto',
        testo: 'Nessuno scavalca in panchina chi ha già giocato.',
      },
      {
        tipo: 'corretto',
        testo:
          '«In corso» e «provvisorio» erano la stessa parola per due cose diverse: a partita in corso il motore non sostituisce più nessuno.',
      },
      {
        tipo: 'corretto',
        testo:
          'Il regolamento di una giornata si congela al suo primo calcio d’inizio: la scadenza non si può più cambiare a giornata cominciata.',
      },
    ],
  },
  {
    id: 'v-1-3',
    versione: '1.3',
    data: '19 agosto 2026',
    titolo: 'L’asta, rifinita',
    voci: [
      {
        tipo: 'migliorato',
        testo: 'In asta si vede per chi gioca il nome sul banco, e chi sta rilanciando.',
      },
      {
        tipo: 'corretto',
        testo: 'Annullare un rilancio non cancella più chi stava sotto.',
      },
      {
        tipo: 'corretto',
        testo: 'Chi non ricordava le maiuscole del proprio nome restava fuori dal sito.',
      },
      {
        tipo: 'migliorato',
        testo: 'Lo stemma della squadra si può portare da casa, non solo comporre.',
      },
      {
        tipo: 'migliorato',
        testo:
          'Nel listone il cognome viene prima del nome, così l’ordine alfabetico serve a qualcosa.',
      },
    ],
  },
  {
    id: 'v-1-2',
    versione: '1.2',
    data: '11 agosto 2026',
    titolo: 'La sala d’asta',
    voci: [
      {
        tipo: 'nuovo',
        testo:
          'L’asta online: chiamata, rilanci in tempo reale su tutti i dispositivi, e le regole di legalità (budget, ruoli, slot) controllate a ogni offerta invece che a fine giro.',
      },
      {
        tipo: 'nuovo',
        testo: 'Il profilo del fantallenatore, con avatar componibile.',
      },
    ],
  },
];
