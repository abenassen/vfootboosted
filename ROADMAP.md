# Prospettive e cose da fare

Elaborazione degli spunti raccolti in `idee_commenti.txt`. Ogni voce dice **cosa
si è deciso**, **cosa resta aperto** e **quanto costa**, così che riprendere un
filo non richieda di ricostruirne il contesto da capo.

Stato al 22/07/2026.

---

## 1. Listone vivo tutto l'anno (in corso)

**Il problema.** Una lega nasce tipicamente pochi giorni prima dell'asta, a
mercato di agosto ancora aperto. Il listone quindi *non* è una fotografia
scattata una volta: continua a muoversi per arrivi e cessioni, in agosto e poi di
nuovo a gennaio.

**Il modello deciso.**

1. **Polling periodico da Transfermarkt** che aggiorna le rose.
2. Ogni aggiornamento **semina automaticamente** i ruoli dei nuovi arrivati,
   usando lo stesso criterio della lega — variante ibrida (posizione TM dove è
   inequivocabile) o pura dai dati, secondo `FantasyLeague.role_mode` — con
   disambiguazione dalle categorie storiche quando il giocatore ha dati.
3. Quando il criterio **non basta** (posizione TM ambigua e nessuno storico) si
   apre una decisione per l'admin.
4. **Finché la decisione è aperta, quel giocatore è in limbo**: non compare fra i
   selezionabili all'asta, e un inserimento manuale a roster che lo contiene dà
   errore. La lega per il resto continua a funzionare.

Il punto 4 è la correzione importante rispetto alla prima versione, che bloccava
l'intero mercato: accettabile al listone iniziale, sbagliato a gennaio, dove un
singolo acquisto avrebbe congelato tutta la lega. Il blocco **per-giocatore**
rende lo stesso meccanismo valido tutto l'anno.

**Aperto.** Con quale cadenza gira il polling TM, e da dove. Lo scraping
Transfermarkt non è quello di SofaScore e potrebbe funzionare dal Linode: va
verificato prima di progettarci sopra.

---

## 2. Polling dati partite: capire cosa blocca davvero

**Quel che sappiamo.** SofaScore risponde 403 dal Linode. La VPN Surfshark non
risolve: l'uscita è Datacamp Limited, cioè un altro hosting. Il Raspberry ha
fallito **da un IP dove il laptop riusciva**, e questo è il dato che cambia la
diagnosi: se lo stesso indirizzo funziona da una macchina e non dall'altra, il
discriminante non è (solo) l'IP.

**Ipotesi da verificare per prima.** Un challenge "non sono un robot" che scatta
sul browser automatizzato. Se è così, un IP dedicato a pagamento **non
risolverebbe nulla** — ed è il motivo per cui va verificato prima di comprarlo.

**Come verificarlo.** Catturare la risposta effettiva (status, corpo, cookie di
challenge) da: laptop a mano, laptop con Playwright, Raspberry con Playwright,
stesso IP. La differenza fra la seconda e la terza isola la causa. Serve una
sessione con l'utente; lo script si può preparare prima.

**Non fare** finché l'ipotesi non è verificata: comprare l'IP dedicato.

---

## 3. Profilo utente

**Il difetto.** Esiste solo `auth/me` in lettura. I dati dell'utente compaiono
come etichetta inerte dentro "Le mie leghe", che è anche il posto sbagliato:
l'utente esiste al di là della lega.

**Da decidere prima di scrivere codice**, perché sono scelte sull'identità e non
tecnicalità:

- lo username è modificabile, o è l'identificatore stabile?
- cambiare email fa ripartire la verifica? Nel frattempo l'account resta attivo?
- si può impostare una password su un account nato da Google (oggi ha una
  password inutilizzabile)? Il flusso naturale è il reset via email.
- scollegare l'account Google: permesso solo se esiste una password, altrimenti
  l'utente si chiude fuori.

**Costo.** Mezza giornata una volta prese le decisioni.

---

## 4. Spiegazione del voto (fatto, estendibile)

Implementata: dalla pagella si apre "perché questo voto?" e si vede lo scarto
dalla media del ruolo in **punti di voto**.

**Estensioni naturali**, in ordine di utilità:
- la stessa spiegazione nel listone, come sintesi stagionale del giocatore;
- confronto fra due giocatori sullo stesso metro (utile in asta);
- spiegazione del *fantavoto*, che oggi si ferma al voto puro e non racconta i
  bonus.

---

## 5. Webapp installabile (PWA)

Manifest, icone, service worker: il sito appare come app su Android e iOS.
Nessuna decisione di prodotto, nessun rischio, poche ore. È il candidato
migliore per una sessione corta.

Attenzione a una cosa sola: il service worker non deve mettere in cache le
risposte API, o un utente si ritrova voti vecchi senza capire perché.

---

## 6. Mobile: selezione e navigazione

Le liste a discesa sono il punto debole segnalato. Da guardare insieme per
capire *quali*: il selettore di lega e competizione sono già compatti, mentre
listone e mercato hanno liste lunghe dove uno swipe o una ricerca incrementale
cambierebbero l'esperienza.

Da valutare anche la formazione, che su schermo piccolo è la pagina più densa.

---

## 7. Coinvolgimento: commenti, chat, meme

Richiede scelte di prodotto prima che tecniche. Una nota architetturale utile: il
meccanismo `LeagueDecision` costruito per i ruoli è **generico** (tipo, oggetto,
opzioni, esito, voto consultivo) e regge già discussioni e votazioni di lega su
qualunque argomento. Un thread di commenti è vicino, non lontano.

Da decidere: moderazione, notifiche, e se i contenuti restano dentro la lega o
sono pubblici.

---

## 8. Bot WhatsApp

Richiede un servizio esterno (API Business o simili), con costi e verifica del
numero. Da valutare rispetto all'alternativa più semplice: notifiche push della
PWA, che non dipendono da terzi e arrivano sullo stesso telefono.

---

## Debiti tecnici aperti

- **Portieri: voto compresso.** Sette valori distinti contro i dodici dei
  difensori, perché la deviazione standard del loro indice è quasi doppia. Si
  correggerebbe con uno `spread_k` dedicato al canale, da calibrare. Nota che
  sui portieri **noi battiamo fantacalcio.it** (0,785 contro 0,606 verso il
  rating indipendente): il problema è la granularità, non la qualità.
- **Aura non riverificata dopo la correzione delle coordinate.** I tiri erano
  collocati nella metà campo sbagliata; i vettori di zona su cui poggia la
  modalità Aura giravano su quei dati. Ora sono corretti ma non ho verificato
  cosa cambia per quella modalità.
- **Blocco formazione al fischio d'inizio**, mai implementato.
- **Produzione ferma** al commit `03b099b`. Il deploy richiede migrazioni,
  reimportazione e ricalcolo dei ruoli.
