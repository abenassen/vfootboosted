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
    id: 'v-1-14',
    versione: '1.14',
    data: '11 settembre 2026',
    titolo: 'Chi gioca uno spezzone viene votato con un modello, non con una proiezione',
    sommario:
      'Fino a oggi chi entrava al 60’ veniva letto come se avesse fatto per novanta minuti quello che ha fatto in trenta, e poi il voto veniva riportato verso il 6 a forza. Adesso i minuti che non ha giocato li completa un modello statistico. Il voto di chi gioca tutta la partita cambia poco; quello degli spezzoni cambia di più, ed è più prudente.',
    voci: [
      {
        tipo: 'nuovo',
        testo:
          'I minuti non giocati vengono completati con un modello poissoniano–bayesiano. In parole: per ogni cosa che si conta in una partita (duelli, passaggi, tiri, recuperi) il modello parte da quanto ne fa in media un giocatore del tuo ruolo in novanta minuti, guarda quanti ne ha fatti il tuo nei minuti in cui era in campo, e da lì stima quanti ne avrebbe fatti nel resto. Chi ha fatto molto in poco viene stimato sopra la media, ma con prudenza: meno minuti ha giocato, più la stima resta vicina alla media del ruolo, e più il voto resta vicino a quello di una prestazione nella media. A novanta minuti il modello non aggiunge niente.',
        caso:
          'Le prime tre giornate di questo campionato, 789 giocatori di movimento con voto: rispetto alle pagelle il nuovo voto sbaglia meno spesso di un punto intero (da 53 a 37 casi contro la Redazione, da 39 a 34 contro lo Statistico) e resta allineato in media anche per chi entra a partita in corso, che prima stava sotto. Sugli spezzoni fra i 45 e gli 89 minuti l’ordinamento migliora.',
      },
      {
        tipo: 'bilanciamento',
        testo:
          'Il pannello del voto racconta il cambiamento: il voto di partenza è lo stesso per tutti i giocatori del tuo ruolo, ogni voce dice quanto i minuti visti hanno aggiunto, e per chi ha segnato o servito un assist in uno spezzone compare «attesa sui minuti non giocati».',
      },
      {
        tipo: 'bilanciamento',
        testo:
          'Il palo vale di più. Da quando il gol è pagato per quanto ha cambiato la partita, il tiro che batte il portiere e prende il legno era rimasto indietro: adesso conta come una parata molto difficile, non come una buona.',
        caso:
          'Nel modello un tiro sul palo vale l’esecuzione che avrebbe avuto se fosse entrato meno quel che l’occasione già valeva. Quel valore sale da 0,40 a 0,60 di gol atteso sul bersaglio. Lo stesso numero lo paga, dall’altra parte, la difesa che lo concede. Sulle prime tre giornate tocca 136 voti di pochi centesimi e ne sposta otto di mezzo punto.',
      },
      {
        tipo: 'bilanciamento',
        testo:
          'Gli episodi rari cambiano peso, perché sono stati ritarati insieme a tutto il resto: i rigori un po’ meno, gli errori che portano a un tiro e i palloni tolti dalla linea di più.',
        caso:
          'Per un difensore, a fine partita: rigore concesso da −0,84 a −0,72 di voto, rigore procurato da +0,73 a +0,54, errore che porta al gol da −0,44 a −0,51, errore che porta a un tiro da −0,08 a −0,16, pallone tolto dalla linea da +0,11 a +0,35. Un gol vale fra 0,34 e 0,79: nessun episodio vale più di un gol.',
      },
    ],
  },
  {
    id: 'v-1-13',
    versione: '1.13',
    data: '11 settembre 2026',
    titolo: 'La panchina si riordina come si sposta un oggetto',
    sommario:
      'L’ordine della panchina è la priorità con cui entrano le riserve, e si decide guardandolo tutto insieme. Il gesto per cambiarlo era rigido: la riga saltava di casella in casella sotto il dito, col mouse bisognava tenere premuto prima di poter muovere, e l’ultimo posto non si raggiungeva.',
    voci: [
      {
        tipo: 'migliorato',
        testo:
          'Quando prendi una riga della panchina si solleva dal foglio e segue il dito con un filo di ritardo, come un oggetto che ha un peso; le altre le fanno posto scivolando e, al rilascio, si posa nella casella tratteggiata che la aspettava.',
      },
      {
        tipo: 'migliorato',
        testo:
          'Da computer si trascina e basta: il cursore diventa una mano sopra le righe, e la presa parte al primo movimento senza dover tenere premuto. Sul telefono resta la pressione lunga, perché un dito che si muove subito sta scorrendo la pagina.',
      },
      {
        tipo: 'migliorato',
        testo:
          'Trascinando verso il bordo dello schermo la pagina scorre da sola, così arrivi anche alle righe che non si vedono.',
      },
      {
        tipo: 'corretto',
        testo:
          'Una riga trascinata in fondo alla panchina arriva davvero all’ultimo posto: prima si fermava al penultimo e bisognava spostarle sopra l’ultimo.',
        caso:
          'Il calcolo contava le righe «sopra quella puntata», e sotto l’ultima non c’è nessuna riga da puntare: la posizione oltre la fine non esisteva.',
      },
    ],
  },
  {
    id: 'v-1-12',
    versione: '1.12',
    data: '5 settembre 2026',
    titolo: 'Il tiro tolto dalla linea non è più un’occasione sprecata',
    sommario:
      'Quando un difensore ti spazza il pallone sulla riga, il tiro era dentro: il portiere l’avevi già battuto. Il modello invece lo leggeva come una conclusione buttata via, perché di quel pallone nessuno misura quanto valesse dopo il tocco. E il pannello che spiega il voto teneva nascosta la voce più grande di tutte.',
    voci: [
      {
        tipo: 'bilanciamento',
        testo:
          'Un tiro nello specchio che un avversario ferma sulla linea non ti toglie più voto: prima contava come occasione fallita, adesso vale quanto la palla che avevi.',
        caso:
          'Il fornitore, di quei tiri, manda uno zero — non perché il tiro fosse debole, ma perché di un pallone fermato prima della porta non registra dove sarebbe arrivato. L’abbiamo verificato incrociando un secondo archivio: a fermarli è un difensore nell’83% dei casi, e sta a un metro e mezzo dalla propria porta contro i tredici di un muro normale. Sono 72 tiri in tutta la scorsa stagione e 6 in questa; Thierry Correia (Venezia-Lecce, 1ª) passa da 5,0 a 5,5.',
      },
      {
        tipo: 'corretto',
        testo:
          'Nel pannello «come nasce il voto puro» compare la riga «nessun gol né assist», che prima non c’era: è quanto pesa, per il tuo ruolo, non aver segnato.',
        caso:
          'Quella fetta esisteva già nel voto — vale 0,26 per un attaccante, 0,10 per un centrocampista — ma finiva in fondo, dentro «altre N voci», e la riga di chiusura la spacciava per la somma di quattro voci sotto il centesimo. Ora quella riga di chiusura vale al massimo quattro centesimi su 1972 presenze controllate, com’è giusto che sia.',
      },
      {
        tipo: 'corretto',
        testo:
          'Su chi gioca uno spezzone, le voci del pannello non sono più più grandi del loro effetto reale sul voto.',
        caso:
          'Un fatto isolato — un tiro nello specchio, un errore — su venticinque minuti veniva disegnato quasi quattro volte più grande di quanto muovesse davvero il voto. Il voto era giusto, era il suo racconto a non tornare.',
      },
      {
        tipo: 'corretto',
        testo:
          'Nella mappa dei tiri, il metro «per un pari ruolo che non conclude» non è più un premio quando non lo è.',
        caso:
          'Su chi aveva un tiro senza valore misurato usciva positivo — cioè diceva che non tirare conviene — mentre per un attaccante che gioca 79 minuti vale circa −0,14.',
      },
    ],
  },
  {
    id: 'v-1-11',
    versione: '1.11',
    data: '4 settembre 2026',
    titolo: 'Gli esterni non finiscono più in difesa',
    sommario:
      'Quando Transfermarkt dice soltanto «esterno di centrocampo» non si capisce se è un terzino d’ala o un’ala: sono due mestieri diversi con lo stesso nome. Finché non abbiamo abbastanza partite per misurarlo, ora scegliamo il centrocampo.',
    voci: [
      {
        tipo: 'corretto',
        testo:
          'Un esterno di centrocampo senza partite sufficienti per misurarne il ruolo veniva messo tra i difensori. Ora va tra i centrocampisti.',
        caso:
          'Sui giocatori che abbiamo potuto misurare la voce «esterno» si spacca in due: tre terzini d’ala veri (Bellanova, Zappacosta, Bernasconi) e due ali (Luis Henrique, Zerbin). Sui sei che il ripiego decideva davvero, il listone ne legge quattro come ali e uno come terzino. E un difensore sbagliato costa più di un centrocampista sbagliato: schierato in difesa entra nel modificatore con un voto che non è quello di un difensore.',
      },
      {
        tipo: 'migliorato',
        testo:
          'L’admin decide il ruolo di più giocatori: la soglia per chiederglielo scende da 5 a 3 milioni di valore. In una lega nuova sono 65 domande invece di 51.',
        caso:
          'Una domanda costa un clic — il modulo porta già la proposta e accettarla è il gesto di default — mentre un ruolo congelato male si scopre quando qualcuno l’ha già comprato, e a quel punto non si può più spostare senza togliere un difensore a chi l’aveva pagato.',
      },
      {
        tipo: 'corretto',
        testo:
          'Rigenerare il listone non sposta più il ruolo di un giocatore già in una rosa o con un’offerta in corso, e dice quanti ne ha lasciati fermi.',
      },
      {
        tipo: 'corretto',
        testo:
          'Se il ruolo di un giocatore cambia tra il momento in cui fai un’offerta e quello in cui viene accettata, l’offerta viene rifiutata invece di completarsi con l’abbinamento sbagliato.',
        caso:
          'L’offerta è un accordo su un difensore per un difensore: se quel difensore non è più tale, l’accordo non è più quello che era stato accettato.',
      },
    ],
  },
  {
    id: 'v-1-10',
    versione: '1.10',
    data: '3 settembre 2026',
    titolo: 'Uno svincolato torna davvero disponibile',
    voci: [
      {
        tipo: 'corretto',
        testo:
          'Un giocatore acquistato dal mercato e poi svincolato poteva restare segnato come «in validazione», anche se non c’era più nulla da decidere. Ora torna subito tra gli svincolati e può ricevere nuove offerte.',
        caso:
          'La vecchia offerta conclusa restava nello storico e veniva scambiata per una validazione aperta.',
      },
    ],
  },
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
          'Una squadra con 47 disponibili offriva 1 per Jiménez svincolando Molina (recupero 25) e si ritrovava con 71 disponibili per Beto. Sulle 185 offerte della prima sessione, 6 superavano il tetto corretto.',
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
