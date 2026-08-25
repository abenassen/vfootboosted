# Voto puro — questioni aperte

Appunti sulle domande di taratura che restano aperte, con i numeri che le hanno
fatte emergere. Non è un piano di lavoro: è il posto dove sta scritto *cosa*
abbiamo misurato e *perché* una scelta è quella che è, così che la prossima
riapertura non riparta dagli aneddoti.

**Vincolo operativo, 24/08/2026: il campionato è iniziato. Nessun peso si
tocca** — cambiare l'indice a stagione in corso riscriverebbe voti già
assegnati e già usati per le classifiche. Quello che si può fare adesso è lo
strato delle spiegazioni (§4), che non muove un solo voto.

Tutte le misure sotto sono sulla **25-26 completa** (10.699 presenze a voto,
appaiate ai due fogli fantacalcio.it e al rating SofaScore), salvo dove detto.

---

## 1. Il caso che ha aperto tutto — Diouf, giornata 1

Andy Diouf, Inter–Monza 4-1 del 22/08/2026, 75', **2 assist**, voto puro
**6.0** (grezzo 5.930). SofaScore gli dà 7.6, il terzo rating del campo.

Scomposizione:

| | punti |
|---|---|
| xA (0.339 — 80° percentile fra le presenze con assist) | +0.170 |
| poco pericolo concesso nella sua zona | +0.066 |
| tutto il resto di ciò che ha fatto in campo | −0.089 |
| **le 24 voci a valore zero** (mai un tiro, un lancio lungo, un duello aereo) | **−0.380** |
| mitigazione del risultato (4-1 con lui in campo) | +0.163 |

I 3 passaggi chiave valgono **0.000**: `key_passes` ha peso zero (§3). Nessuna
big chance riconosciuta, quindi la creazione poggia sulla sola xA a peso 0.05.

**Non è un caso isolato.** L'archetipo (CEN, ≥60', ≥1 assist, 0 tiri) è n=58
sulla 25-26: nostro 5.99 contro Redazione 6.49 e Statistico 6.54, cioè −0.52 /
−0.58 di scostamento al netto del bias medio del modello.

---

## 1bis. Il secondo caso — Dybala, giornata 1: il guasto OPPOSTO

Paulo Dybala, Roma–Fiorentina 4-0 del 24/08/2026, 79', **3 assist** (i tre gol di
Malen), 0 gol. Voto puro **6.5** (grezzo 6.700 — arrotondato in giù di 0.2).
Pagelle 8.5, rating SofaScore **9.1**. *Voto provvisorio: `data_ready` era ancora
falso a fine serata.*

**Non è il caso di Diouf. È il suo contrario.** Qui gli strumenti hanno funzionato
tutti, a pieno regime: xA **1.093**, `big_chance_created` **3**, 4 passaggi chiave.
Credito di creazione **+0.656** — praticamente il massimo che il canale sappia
produrre (il miglior blocco creazione di TUTTA la 25-26 valeva +0.673).

Scala per un ATT a 79', sopra la media di ruolo:

| | sopra la media | in gol |
|---|---|---|
| 1 gol | +0.572 | 1.00 |
| 3 gol (la tripletta di Malen) | +1.019 | 1.78 |
| **xA 1.09 + 3 big chance (Dybala)** | **+0.656** | **1.15** |
| tetto assoluto del canale (xA 1.53 + 5 big chance) | +0.780 | 1.36 |

Creare tre gol vale **1.15 gol**. Il canale non può dare di più di 1.36, mai.

E buona parte di quel credito se lo mangiano due addebiti che colpiscono proprio
un attaccante che ha fatto segnare gli altri:

| | punti |
|---|---|
| non ha segnato lui (`shots_goal`, media ATT alta) | **−0.124** |
| ha tirato male (`sga_post`: 4 tiri, xG 0.20 ma xGOT 0.086) | **−0.129** |
| indice difensivo | −0.087 |
| dribbling concessi, duelli vinti | −0.114 |

−0.25 solo fra «non ha segnato» e «ha tirato male», che sono in parte lo stesso
fatto. Netto +0.70 → grezzo 6.700 → **6.5**.

### I due casi insieme dicono cose diverse

| | Diouf | Dybala |
|---|---|---|
| assist | 2 | 3 |
| xA | 0.339 | 1.093 |
| big chance riconosciute | **0** | **3** |
| credito di creazione | **+0.147** | **+0.656** |
| nostro voto | 6.0 | 6.5 |
| giudizio esterno | 7.6 (SofaScore) | 8.5 pagelle / 9.1 SofaScore |
| **guasto** | **falso negativo dello strumento** | **tetto del canale** |

Sono i due modi distinti in cui il blocco creazione fallisce, e **la correzione di
uno non tocca l'altro**: riaccendere `key_passes` e ribilanciare xA/bcc (§2)
avrebbe salvato Diouf e non avrebbe spostato Dybala di un centesimo — i suoi
strumenti erano già tutti accesi al massimo.

Da notare, perché è la prova che il modello non è rotto in generale: **nella stessa
partita siamo d'accordo con le pagelle su tutti gli altri** — Malen 8.0 contro 8.5,
Ndicka 6.5 contro 6.5, Hermoso 6.5 contro 6.5. Il divario di due punti è su Dybala
e su nessun altro. Lo stesso modello, la stessa partita: accordo sul finalizzatore,
due punti di scarto sul creatore.

---

## 2. LA QUESTIONE PRINCIPALE — xA contro big_chance_created

### Com'è oggi

`classic_rating.py:111` e `:165`. Il 30/07/2026 i due pesi sono stati abbassati
**insieme** (xA 0.11 → 0.05, bcc 0.07 → 0.045) perché si sovrappongono (r 0.58)
e la coppia era arrivata a valere 1.33 gol per una singola occasione creata.
La calibrazione marginale dichiarata è rispettata alla lettera: 1 bcc = 0.29
gol, xA 0.45 = 0.40, coppia = 0.69.

La motivazione registrata per tenere bcc più alto in proporzione
(`classic_rating.py:154-157`) è **l'accordo con le pagelle**: *«xA is pure cost
[...], while big_chance_created earns its keep (dropping it to 0 costs 0.01 of
r)»*.

### Cosa dice la misura

Regressione su 6.160 presenze di movimento ≥60' **senza gol**, stessi regressori
per i quattro giudici. Coefficiente = punti di voto per una big chance.

| | xA (A) | bcc (A) | xA (B) | bcc (B) | assist (B) |
|---|---|---|---|---|---|
| Noi | +1.092 | +0.147 | +1.084 | **+0.133** | +0.047 |
| Redazione | +0.460 | +0.251 | +0.364 | **+0.080** | +0.572 |
| Statistico | +0.587 | +0.271 | +0.488 | **+0.093** | +0.596 |
| SofaScore | +1.463 | +0.070 | +1.432 | **+0.015** | +0.182 |

*(A) = voto ~ xA + bcc. (B) = si aggiunge l'assist. Errori standard 0.019-0.077.*

**Due terzi di quello che le pagelle sembrano pagare per un'occasione creata è
il bonus assist che passa attraverso il flag.** Il canale è misurabile: a parità
di xA, `bigChanceCreated` scatta ~3 volte più spesso quando l'assist è arrivato
(20% → 63% nella banda xA [0.10, 0.20); 58% → 94% nella banda [0.35, 0.60)).

Il nostro voto non si muove (−10%) perché l'assist non lo paghiamo. Ma il peso
di bcc è stato tarato contro giudici che lo pagano, e **il risultato è
un'inversione**: a parità di xA *e* di assist noi paghiamo il flag +0.133,
più della Redazione (+0.080), dello Statistico (+0.093) e di SofaScore (+0.015).
Al netto dell'esito è il peso più alto del panel.

Nota: la prova registrata era già debole per conto suo — il commento stesso dice
che azzerare bcc costa 0.01 di r.

### Quanto costa a chi il flag non ce l'ha

35,3% delle presenze con assist hanno bcc = 0. Spaccando la popolazione per quel
che il modello vede:

| | n | noi | Red. | Stat. | ΔRed | credito creazione |
|---|---|---|---|---|---|---|
| big chance riconosciuta | 375 | 6.43 | 6.73 | 6.76 | −0.317 | +0.295 |
| no bcc, xA ≥ 0.15 ← *Diouf* | **36** | 6.36 | 6.64 | 6.72 | −0.302 | **+0.103** |
| no bcc, xA < 0.15 (tap-in) | 169 | 6.12 | 6.55 | 6.54 | −0.459 | −0.021 |

Il terzo blocco (29% di tutti gli assist) è quello con lo scarto più grande, e
lì lo scarto è **giusto**: quei passaggi non meritano niente e le pagelle li
pagano comunque. Il problema è il secondo blocco.

Su CEN ≥60' con xA ≥ 0.30: con flag +0.419 di credito, senza flag +0.173. Due
prestazioni che creano altrettanto, distanti 0.25 di voto su un giudizio binario
di cui **non conosciamo il criterio** (il feed dà il conteggio, non la regola, e
`MatchShot` non ha il campo del passatore per risalire all'episodio).

### Il soffitto della creazione

Scala marginale, CEN 90' (l'indice è additivo, quindi esatta):

| | da zero | sopra la media di ruolo | in gol |
|---|---|---|---|
| 1 gol | +0.717 | +0.657 | 1.00 |
| 1 big chance | +0.208 | +0.184 | 0.29 |
| 2 big chance | +0.295 | +0.271 | 0.41 |
| xA 0.10 (90° pct) | +0.116 | +0.046 | 0.16 |
| xA 0.46 (99° pct) | +0.289 | +0.219 | 0.40 |
| xA 1.53 (max stagione) | +0.476 | +0.407 | 0.66 |

La compressione fa saturare il canale quasi subito (NON è una √ — v. §2septies):
dal nulla al 90°
percentile di xA sono +0.116; dal 90° percentile al massimo assoluto — quindici
volte più xA — solo +0.360. La partita più creativa dell'intera Serie A vale
**due terzi di un gol**.

**Attenzione a una lettura sbagliata** (ci sono cascato in sessione): la media
del blocco creazione su chi ha una big chance (+0.312) confrontata con la media
della voce gol su chi segna (+0.642) *non* è il valore marginale. E la coppia
«1 bcc + xA 0.45» non è l'evento tipico: la xA mediana che accompagna una big
chance è **0.196**, e la coppia tipica vale **0.44 di un gol**, non 0.69. Lo
0.69 si raggiunge a due big chance, cioè lo 0.55% delle presenze.

### Da decidere a fine stagione

Spostare peso da bcc verso le misure continue. Argomenti:

1. **Non è un compromesso fra principio e accuratezza.** L'accordo col *voto
   pubblicato* peggiorerebbe; l'accordo con la *componente merito-del-passaggio*
   di quel voto migliorerebbe. Solo la seconda è ciò che il modello dichiara di
   misurare, e la tabella (B) dice che oggi siamo fuori taratura in eccesso.
2. **Le tre non sono ridondanti** (r 0.45-0.65) e quale pesa di più dipende dal
   ruolo: attaccanti xA, centrocampisti passaggi chiave, difensori occasioni
   nitide — v. §2ter. Con un vettore di pesi solo si sceglie il compromesso, e nel
   compromesso `key_passes` è il coefficiente più alto ed è quello spento.
   **NON** vale più, invece, l'argomento «non concentrare sull'xA per via dei
   difensori»: era fondato su una lettura sbagliata, corretta in §2ter.
3. La taratura del blocco va fatta contro i coefficienti **con l'assist
   controllato**, non contro i fogli grezzi (§2bis).

Aperto e non misurato: quanto costa in accordo complessivo. Va misurato prima di
muovere qualsiasi cosa.

---

## 2quater. Il principio, misurato — e dove sta davvero il guasto

Il principio dichiarato: **dare valore a tutti i passaggi che hanno davvero creato
un'occasione**, quelli finiti in gol e quelli no. I fogli fantacalcio legano invece
quel valore all'assist, cioè al gol.

La misura che lo mette alla prova: stessa occasione creata, esito diverso.
Presenze di movimento ≥60' che non hanno segnato loro.

| gruppo | n | noi | Redazione | Statistico | SofaScore |
|---|---|---|---|---|---|
| occasione nitida creata → **non** è gol | 427 | 6.29 | 6.01 | 6.04 | 7.02 |
| occasione nitida creata → **è** gol (assist) | 245 | 6.34 | 6.64 | 6.70 | 7.27 |
| nessuna occasione creata | 5.348 | 5.91 | 5.84 | 5.83 | 6.74 |

**Quanto costa che l'occasione sia finita in gol** (seconda riga meno prima, a
parità di occasione creata):

| noi | Redazione | Statistico | SofaScore |
|---|---|---|---|
| **+0.05** | +0.63 | +0.66 | +0.25 |

**Quanto vale aver creato un'occasione che NON è diventata gol** (prima riga meno
terza: il merito del passaggio a esito nullo):

| noi | Redazione | Statistico | SofaScore |
|---|---|---|---|
| **+0.38** | +0.17 | +0.21 | +0.27 |

Cioè: siamo **quasi indifferenti all'esito** (+0.05 contro +0.63 e +0.66) e
paghiamo il passaggio non premiato **più di ogni altro giudice** (+0.38). Il
principio non è un'aspirazione: è implementato e si misura.

E non protegge un caso di margine. Delle 672 presenze con almeno un'occasione
nitida creata, **427 — il 64% — non sono diventate assist**: la creazione che
l'esito non premia è la maggioranza della creazione.

### Dove sta il guasto, allora

Diouf **non** è un contro-esempio del principio: è un guasto dello STRUMENTO. Il
suo problema non è che leghiamo la creazione all'esito — non lo facciamo — ma che
`bigChanceCreated` non è scattato su nessuno dei suoi due passaggi, per cui la sua
creazione è stata letta dalla sola xA a peso 0.05, con `key_passes` spento.

Ne segue la conclusione di progetto, diversa da quella di §2ter e più solida:
**il problema è la ridondanza degli strumenti, non il principio né la scelta di
quale peso alzare.** Nessuna delle tre misure riconosce da sola «ha creato
un'occasione» in modo affidabile:

* il 35% delle presenze con assist ha `bigChanceCreated` a zero;
* il 46% delle presenze con `bigChanceCreated` ha xA sotto 0.20;
* il 32% dei centrocampisti con xA ≥ 0.30 non ha nessun flag.

Tre misure imperfette dello stesso fatto servono a questo: che il buco di una non
cancelli il credito. Oggi una delle tre è spenta a zero, e quando la seconda non
scatta resta solo la terza, al peso più basso che abbia mai avuto.

---

## 2ter. Le tre misure di creazione NON sono ridondanti, e cambiano per ruolo

La domanda «perché non pesare solo la xA, visto che le tre misurano la stessa
cosa?» ha una risposta empirica. Le tre insieme, con gol **e assist** controllati
(voto Redazione, presenze di movimento ≥60'), coefficiente per 1 sd:

| ruolo | n | xA | big chance | key pass |
|---|---|---|---|---|
| DIF | 3.094 | **−0.018 ±0.014** | **+0.036** ±0.013 | +0.025 ±0.013 |
| CEN | 2.435 | +0.038 ±0.013 | +0.019 ±0.012 | **+0.052** ±0.012 |
| ATT | 1.300 | **+0.082** ±0.016 | +0.004 ±0.016 | +0.060 ±0.015 |
| tutti | 6.829 | +0.024 ±0.009 | +0.023 ±0.008 | **+0.038** ±0.008 |

Due letture:

* **Per un centrocampista la voce più forte è `key_passes`** (+0.052), non la xA
  (+0.038). È il ruolo di Diouf: concentrare sull'xA metterebbe il peso sulla più
  debole delle due proprio dove serve.
* **Per un attaccante è l'opposto**: la xA domina (+0.082) e `big_chance_created`
  va a zero (+0.004).

### ⚠ Sulla riga DIF: una lettura sbagliata, corretta il 24/08/2026

Quel −0.018 era stato letto come «per un difensore la xA non porta segnale».
**È falso, due volte.**

*Primo*, è un coefficiente CONDIZIONATO: con due regressori correlati accanto
(VIF 2.04) misura l'apporto INCREMENTALE, non l'apporto. Da sola, con gol e
assist controllati, la xA di un difensore vale **+0.014 ±0.011**. Redundanza e
assenza sono cose diverse, e la scomposizione le separa:

| DIF, coefficiente della xA | |
|---|---|
| da sola | +0.014 ±0.011 |
| + passaggi chiave | −0.004 ±0.013 |
| + occasioni nitide | −0.004 ±0.012 |
| tutte e tre | −0.018 ±0.014 |

*Secondo — e questo conta di più*: «non porta segnale» significava «non predice il
voto della Redazione». Ma la Redazione è **un** giudice. Coefficiente della xA da
sola, per 1 sd, con accanto quanto lo stesso giudice paga un gol come metro:

| ruolo | Redazione | Statistico | SofaScore | (1 gol ≈) |
|---|---|---|---|---|
| DIF | +0.014 ±0.011 | +0.025 ±0.011 | **+0.127** ±0.009 | ~1.0 |
| CEN | +0.075 ±0.010 | +0.111 ±0.011 | **+0.208** ±0.009 | ~1.0 |
| ATT | +0.115 ±0.013 | +0.140 ±0.014 | **+0.244** ±0.012 | ~1.0 |

SofaScore paga la creazione di un difensore **nove volte** quanto la paga la
Redazione (13% di un gol contro 1,4%), con un coefficiente a 14 sigma da zero. Non
è che la xA di un difensore sia rumore: **sono i due fogli fantacalcio a non
pagare la creazione di un difensore**, che è una convenzione editoriale — un
difensore si giudica su come difende — non una misura.

Cioè: dedurre dai fogli che la xA di un difensore non vale niente è **la trappola
del §2bis, un piano più su**. Lo stesso errore che ha gonfiato `big_chance_created`.

**Conseguenza sulla raccomandazione**: l'argomento «non concentrare sull'xA per via
dei difensori» **cade**. Quel che resta in piedi è solo che le tre non sono
ridondanti e che `key_passes` è la più forte per i centrocampisti. Se la filosofia
è valutare il passaggio in quanto tale, il cross pericoloso di un difensore un
credito lo merita, e i fogli non sono il giudice giusto per stabilirlo.

Sovrapposizione reale fra le tre: r fra 0.45 e 0.65 secondo la coppia e il ruolo.
Correlate, non intercambiabili — due terzi della varianza di una non è spiegata
dall'altra.

**Il vincolo strutturale che ne esce**: il vettore dei pesi outfield è UNO SOLO
(scelta esplicita, v. la nota su `shots_goal` in `classic_rating.py`). Ma i pesi
giusti del blocco creazione sono diversi per ruolo — attaccanti xA, centrocampisti
passaggi chiave, difensori occasioni nitide. Con un vettore solo si può scegliere
il compromesso, non la risposta giusta; **la riga «tutti» è quel compromesso**, e
dice che oggi `key_passes` a zero è la scelta peggiore delle tre.

### Ritrattata: il meccanismo «residuo di un cross sperante»

`classic_rating.py:130-136` spiega la xA debole dei difensori come il residuo di
cross speranti. Il fenomeno è confermato; **il meccanismo no**. Correlazione con i
cross riusciti, per ruolo:

| ruolo | xA ~ cross | key pass ~ cross |
|---|---|---|
| DIF | +0.611 | **+0.687** |
| CEN | +0.474 | +0.498 |
| ATT | +0.516 | +0.509 |

I passaggi chiave di un difensore sono **più** cross-dipendenti della sua xA, e
portano segnale mentre la xA no. Quindi non è il cross a rovinare la xA dei
difensori: è qualcos'altro — plausibilmente l'errore del modello xG proprio su
quei palloni — e resta da capire.

### Cautele su questa tabella

Multicollinearità: i tre regressori correlano fra 0.45 e 0.65, quindi i
coefficienti singoli sono meno stabili di quanto gli errori standard suggeriscano.
Segno e ordine di grandezza si leggono; le distinzioni fini no. Il bersaglio è il
voto della Redazione, giudice imperfetto (e che paga l'assist — qui controllato).
Coefficienti lineari su feature grezze, mentre il modello usa z-score compressi
(§2septies).

---

## 2quinquies. La griglia: bcc a zero, xA alzata — misurata

Domanda diretta: si può tarare in positivo in modo che **Diouf e Dybala salgano
insieme**? Sì. Taratura ricostruita da capo a ogni riga; i due casi sono applicati
alla calibrazione fissa 25-26, che è quella che gira in produzione.

*Controllo di fedeltà: alla riga ATTUALE i due valori riproducono la produzione
al millesimo (5.930 → 6.0 e 6.701 → 6.5). La griglia è affidabile.*

| xA | bcc | Diouf grezzo | voto | Dybala grezzo | voto | media | std | r Redaz | r Stat | MAE Red |
|---|---|---|---|---|---|---|---|---|---|---|
| **0.05** | **0.045** | 5.930 | **6.0** | 6.701 | **6.5** | 6.007 | 0.564 | 0.6690 | 0.6968 | 0.3357 |
| 0.11 | 0 | 5.999 | 6.0 | 6.781 | **7.0** | 6.006 | 0.564 | 0.6602 | 0.6876 | 0.3400 |
| 0.15 | 0 | 6.122 | 6.0 | 7.005 | 7.0 | 6.006 | 0.563 | 0.6574 | 0.6867 | 0.3414 |
| **0.20** | **0** | 6.264 | **6.5** | 7.251 | **7.5** | 6.006 | 0.563 | 0.6473 | 0.6762 | 0.3459 |
| 0.30 | 0 | 6.497 | 6.5 | 7.638 | 7.5 | 6.004 | 0.558 | 0.6216 | 0.6516 | 0.3562 |

* **Salgono insieme, in modo monotòno.** Azzerare bcc costa a Dybala (ne aveva 3) e
  regala a Diouf (ne aveva 0), ma da 0.11 in su l'aumento della xA copre la perdita
  anche per Dybala.
* **Per muovere entrambi i voti MOSTRATI serve xA ≈ 0.20**, cioè quattro volte
  l'attuale: lì Diouf va a 6.5 e Dybala a 7.5.
* **La distribuzione non si gonfia**: media 6.007 → 6.006, std 0.564 → 0.563. La
  ricalibrazione riassorbe tutto — non è inflazione, è redistribuzione verso i
  creatori.
* **Il prezzo è l'accordo**: r Redazione 0.669 → 0.647, MAE 0.336 → 0.346.

### Dove si perde quell'accordo — la misura che decide

| arm | gruppo | n | r Redaz | r Stat | r Sofa |
|---|---|---|---|---|---|
| attuale | creatori | 1.594 | 0.6086 | 0.6473 | 0.7426 |
| xA 0.20 | creatori | 1.594 | **0.5556** | **0.6006** | **0.7477** |
| attuale | NON creatori | 9.053 | 0.6625 | 0.6889 | 0.7648 |
| xA 0.20 | NON creatori | 9.053 | **0.6499** | **0.6768** | **0.7568** |

*(«creatore» = almeno una big chance oppure xA ≥ 0.15)*

* La perdita è **concentrata sui creatori**, come dev'essere: −0.053 contro la
  Redazione, quattro volte i −0.013 di tutti gli altri. È la divergenza voluta,
  non un peggioramento generale.
* Contro **SofaScore, sui creatori, l'accordo MIGLIORA** (0.7426 → 0.7477). Poco,
  ma è l'unico giudice che va nella direzione giusta ed è quello che la creazione
  la prezza.
* **Ma i non-creatori perdono comunque 0.013** con tutti e tre. Quello è danno
  collaterale della ricalibrazione, non divergenza voluta, e va messo nel conto.

### Tre riserve prima di prendere questa strada

1. **Due casi non tarano un peso.** Diouf e Dybala sono 2 presenze su ~250 a
   giornata. La giustificazione buona è quella di popolazione (§2quater: il 64%
   delle occasioni create non diventa assist), non questi due nomi. Tarare su due
   giocatori è esattamente il sovradattamento contro cui serve questo documento.
2. ~~**Azzerare bcc toglie l'unico strumento che funziona per i difensori.**~~
   **RITIRATA** — v. §2sexies: era letta sulla colonna Redazione, di nuovo. Contro
   SofaScore bcc vale −0.006 per i centrali e +0.049 per gli esterni, mentre la xA
   vale +0.076 e +0.151. Per i difensori lo strumento migliore è la xA, non bcc.
3. **`key_passes` resta a zero in tutta la griglia.** La combinazione a tre non è
   stata esplorata, e §2ter dice che per i centrocampisti è la più forte delle tre.
   È la direzione non misurata, e probabilmente quella giusta.

---

## 2sexies. Centrali ed esterni: la riga DIF aggregava due mestieri

Obiezione: «un Dimarco crea eccome, e crea via xA». Giusta. La riga DIF di §2ter
mescolava centrali ed esterni, che creano in misura diversa:

| | n | xA media | passaggi chiave medi |
|---|---|---|---|
| centrali | 1.431 | 0.029 | 0.29 |
| esterni (terzini/quinti) | 908 | **0.099** | **1.04** |

Coefficiente della xA da sola (gol e assist controllati), per 1 sd:

| | Redazione | SofaScore |
|---|---|---|
| centrali | +0.015 ±0.015 | +0.106 ±0.014 |
| esterni | +0.019 ±0.018 | **+0.200** ±0.016 |

E le tre insieme, contro SofaScore:

| | xA | bcc | key pass |
|---|---|---|---|
| centrali | **+0.076** | −0.006 | +0.064 |
| esterni | **+0.151** | +0.049 | +0.044 |

**Due correzioni.**

*La divisione non salva il coefficiente contro la Redazione*: anche per i soli
esterni resta +0.019 ±0.018, indistinguibile da zero. I fogli non pagano la
creazione di un difensore, terzini compresi. Il fenomeno è del GIUDICE.

*Ma contro SofaScore la divisione è decisiva*: per un esterno la xA vale +0.200,
quasi il livello di un attaccante (+0.244) e il doppio di un centrale. Per un
terzino la xA porta segnale eccome — e bcc, per i difensori, non è affatto lo
strumento migliore: per i centrali vale meno di zero.

### E il modello già la premia, quella creazione

Il punto che chiude l'obiezione. Il riferimento DIF ha una xA media bassissima
(0.029 per i centrali), quindi un esterno creativo è un outlier positivo enorme
dentro quella distribuzione. Dimarco, 28 presenze ≥60' nella 25-26:

| | |
|---|---|
| xA media a partita | **0.334** — undici volte un centrale, tre volte un esterno |
| xA totale di stagione | 9.35 |
| nostro voto medio | **6.86** |
| Redazione | 6.64 |
| SofaScore | 7.46 |

**Siamo SOPRA la Redazione di 0.22 su di lui.** Il timore che la creazione di un
difensore diventasse rumore non si materializza nel caso che lo doveva mostrare.

### «Ma la Redazione Dimarco lo paga eccome» — sì, ma attraverso l'assist

L'obiezione naturale: se la Redazione paga l'assist, e Dimarco di assist ne fa
tanti, com'è che «non paga la sua creazione»? Non è una contraddizione: è
esattamente ciò che significa **controllare per l'assist**. Lo paga, ma per la via
dell'esito. Le sue 28 presenze ≥60' spaccate in due:

| | n | xA media | noi | Redazione | SofaScore |
|---|---|---|---|---|---|
| Dimarco, con assist | 9 | 0.583 | 7.22 | **7.17** | 8.04 |
| Dimarco, **senza assist né gol** | 15 | 0.186 | 6.40 | **6.20** | 6.87 |
| altri esterni, con assist | 68 | 0.293 | 6.46 | 6.62 | 7.32 |
| altri esterni, senza | 802 | 0.082 | 6.02 | 5.87 | 6.77 |

Nelle 15 gare senza assist né gol Dimarco **creava lo stesso** — xA 0.186, più del
doppio di un esterno qualunque — e la Redazione gli dà 6.20 contro i 7.17 delle
gare con assist. **Un punto pieno di differenza**, a creazione paragonabile.

La scomposizione del suo voto medio, coi coefficienti del gruppo esterni:

| giudice | dall'assist | dalla creazione | quota della creazione |
|---|---|---|---|
| Redazione | +0.302 | +0.031 | **9%** |
| SofaScore | +0.104 | +0.330 | **76%** |

Stesso giocatore, stessa stagione: per la Redazione nove decimi di quel che il suo
gioco creativo gli frutta arrivano come bonus assist; per SofaScore è il contrario.
Ecco perché il coefficiente della xA *controllato per l'assist* è ~0 per la
Redazione e +0.200 per SofaScore, senza che nessuno dei due «ignori» Dimarco.

*(Cautela: il confronto per gruppi qui sopra non è appaiato su nulla — Dimarco
gioca nell'Inter e fa anche altro. È la regressione a isolare la creazione; questa
tabella serve a mostrare il meccanismo, non a misurarlo.)*

Da notare, perché spiega il meccanismo: il k-means puro (`role_data`) classifica
Dimarco **ATT**, categoria «ala offensiva»; è `role_mitigated` a riportarlo a DIF,
ed è quello che lo scoring usa (`current_role_map`). Cioè viene giudicato contro i
difensori mentre gioca da ala — ed è *per questo* che la sua creazione è pagata
tanto. La mitigazione, qui, gli fa un favore.

I difensori più creativi della stagione sono **tutti** «esterno basso» nel
clustering: Cambiaso (xA 4.99), Dodô (4.95), A. Martín (4.95), Valeri (4.06),
Miranda (3.97), Bartesaghi (3.95), Zappacosta (3.30), Wesley (3.28). Il fenomeno è
sistematico, e lo split centrale/esterno resta il residuo aperto già noto.

### Il pattern che devo ammettere

È la **terza volta** in questa analisi che leggo la colonna Redazione come «il
segnale» e sbaglio: prima su `big_chance_created` (§2), poi sulla xA dei difensori
(§2ter), ora sulla riserva contro l'azzeramento di bcc. È esattamente la trappola
di §2bis, e va guardata ogni volta che si scrive «questa feature non porta
segnale»: la frase è sempre relativa a un giudice, e va detto quale.

---

## 2septies. La compressione: NON è una radice, ed è xA che l'ha motivata

**Correzione a me stesso**, perché in tutta la sessione ho scritto «√-compressione»
citando il messaggio del commit `e836ddb` («selective √») senza controllare il
codice attuale. La radice **non c'è più**.

Oggi (`classic_rating.py:1211`):

```
_compress(u) = K · log1p(|u| / K) · sign(u)      con COMPRESS_K = 1.0
```

E il docstring dice perché la √ è stata tolta: *«f(0)=0, f'(0)=1 — a small value
passes through essentially untouched, which is exactly what the √ it replaces got
wrong»*. Cioè: su un valore piccolo la radice **amplifica** (√0.05 = 0.22, più di
quattro volte), gonfiando il rumore. `log1p` no.

**Non si comprime il valore grezzo, si comprime `u = valore / σ_raw`.** Per la xA
σ_raw = **0.1119**, quindi una xA da 0.34 diventa u = 3.03 e una da 1.09 diventa
u = 9.74. L'obiezione «è un numero fra 0 e 1, la radice lo amplificherebbe» è
giusta in sé e non morde qui, perché non è quel numero a entrare nella funzione.

Quanto comprime davvero, sui livelli che ci interessano:

| xA | u = xA/σ | compresso | **quota trattenuta** | z finale |
|---|---|---|---|---|
| 0.05 | 0.45 | 0.37 | 83% | 0.88 |
| 0.10 (90° pct) | 0.89 | 0.64 | 72% | 1.52 |
| **0.34 (Diouf)** | 3.03 | 1.39 | **46%** | 3.32 |
| 0.46 (99° pct) | 4.11 | 1.63 | 40% | 3.88 |
| **1.09 (Dybala)** | 9.74 | 2.37 | **24%** | 5.65 |
| 1.53 (max stagione) | 13.67 | 2.69 | **20%** | 6.39 |

**Ed è la xA ad aver motivato l'esistenza stessa della compressione**: il commento
a `COMPRESS_K` dice che raggiungeva **13σ con kurtosi in eccesso +16**, la più
grassa del modello (shots_goal +12.5, xg_shots +17.6, gk_goals_prevented +0.87).
`COMPRESS_K` è stato poi abbassato 2.0 → 1.0 il 29/07/2026 per accorciare la coda
alta degli attaccanti.

### Le due decisioni si sommano, ed è questo il soffitto

La xA è **insieme** la feature col peso più tagliato (0.11 → 0.05 il 30/07) e
quella con la coda più compressa di tutte. Il canale creazione è stretto ai due
capi, e Dybala ne trattiene il 24%.

`COMPRESS_K` è quindi la leva documentata per il tetto di §1bis — ma è **globale**:
tocca ogni feature, non solo la xA (l'unica esenzione oggi è
`gk_goals_prevented`, in `NO_COMPRESS_FEATURES`). Alzarla rifarebbe la coda alta
degli attaccanti che il 29/07 si era voluta accorciare. Una decompressione della
sola xA sarebbe un meccanismo nuovo, non una taratura.

E resta il limite già visto: **Diouf a 0.339 sta allo stesso u della media
stagionale di Dimarco (0.334)**. Nessuna leva sulla forma della curva li separa,
perché sono lo stesso numero.

---

## 2septies-bis. L'etichetta sbagliata del peso — e perché le misure reggono

Scoperto il 25/08/2026 eseguendo per la prima volta `calibrate_vote_reference`
davvero invece di simularlo.

**La causa.** `classic_rating.feature_scales()` **non ricalcola le scale**: le legge
congelate da `vote_reference.json`, e `clear_scales_cache()` le ricarica dallo
stesso file. Le simulazioni impostavano pesi e linearizzazione e chiamavano
`build_reference`, ma il `sigma_z` restava quello della versione **compressa**.

| xA | sigma_raw | sigma_z |
|---|---|---|
| compressa (file vecchio) | 0.1119 | **0.4201** |
| lineare (calibrazione vera) | 0.1119 | **1.0000** |

**Ma l'errore si riassorbe per intero in una ridefinizione del peso**, ed è la cosa
importante: con la compressione spenta `_feature_z` è **lineare in 1/sigma_z**,
quindi dividere per 0.4201 invece che per 1.0 è identico a moltiplicare il peso per
2.38. Verificato: `xA 0.1428` lineare con le scale ricostruite dà **288 voti su 288
identici** alla simulazione, reference inclusa (CEN 0.4098/0.4892 contro
0.4099/0.4892).

**Quindi nessuna misura di questo documento è nulla.** Era sbagliata l'ETICHETTA:
dove si legge «xA 0.060 lineare» si deve leggere **«xA 0.14 lineare»**. Il valore
spedito è 0.14 tondo — si scosta dall'equivalente esatto di **un solo voto** su 288
(Mandragora) e lascia Diouf e Dybala dove stanno.

**La regola da ricordare.** Simulare un cambio di **forma** (questa lista,
`COMPRESS_K`) richiede `build_feature_scales` e il passaggio esplicito delle scale;
per i soli **pesi** la scorciatoia è corretta, ed è per questo che l'errore è
passato inosservato. Nota anche il sintomo che avevo davanti e non ho riconosciuto:
l'«incrocio compresso/lineare a u = 0.011» di §2septies era assurdo, e lo era
perché confrontava due scale diverse.

> Un peso non è confrontabile fra i due regimi: vale «punti di indice per 1 sigma»,
> e togliendo la compressione quel sigma è un'altra cosa. **0.14 lineare non è
> «tre volte» 0.05 compressa** — a parità di effetto sulla fascia media, 0.14
> lineare sta a 0.06 compressa.

---

## 2octies. LA STRADA SCELTA: xA lineare, non xA più pesante

*(i pesi citati qui sotto vanno letti con l'etichetta corretta di §2septies-bis:
«0.060» = **0.14**)*

Domanda: la compressione così forte ha senso, o crea aberrazioni? Due risposte
diverse, e la seconda apre la via d'uscita.

### Nella distribuzione, nessuna aberrazione — né togliendola

Criterio del codice stesso (`NO_COMPRESS_FEATURES`: kurtosi compressa NEGATIVA =
sovra-correzione). Sulle 10.067 presenze di riferimento:

| feature | kurtosi grezza | max σ | kurtosi compressa (K=1) | max σ |
|---|---|---|---|---|
| **expected_assists** | **+17.2** | 13.5 | **+3.15** | 5.7 |
| xg_shots | +19.0 | 11.1 | +4.06 | 5.4 |
| big_chance_created | +17.3 | 13.9 | +6.79 | 6.2 |
| key_passes | +6.2 | 8.3 | **−0.22** | 4.0 |
| clearances | +4.3 | 7.2 | **−0.22** | 3.7 |
| duels_won | +1.3 | 8.0 | **−0.58** | 3.6 |

La xA **non** è sovra-compressa per quel criterio: resta chiaramente a coda grassa
(+3.15). Sono `key_passes`, `clearances` e `duels_won` a finire sotto la gaussiana
— la stessa firma che fece esentare `gk_goals_prevented`. Il commento a
`NO_COMPRESS_FEATURES` dice che era noto e accettato per il canale outfield.

### L'aberrazione c'è, ma è di ORDINAMENTO

Dybala fa 3.2 volte la xA di Diouf e ne ricava 1.7 volte il contributo. È lì che si
sente, non nella coda della distribuzione.

### E toglierla costa un quarto di quel che costa alzare il peso

`expected_assists` messa in `NO_COMPRESS_FEATURES`, peso ritarato a **0.035**
perché la fascia media resti dov'era:

| arm | Diouf | Dybala | media | std | max | ≥8 | r Redaz |
|---|---|---|---|---|---|---|---|
| **ATTUALE** (compressa, 0.05) | 5.93 | **6.70** | 6.007 | 0.564 | 9.0 | 0.9% | **0.6690** |
| compressa, xA 0.20 | 6.26 | 7.25 | 6.006 | 0.563 | 9.0 | 0.7% | 0.6473 |
| **LINEARE, xA 0.035** | 5.97 | **7.14** | 6.007 | 0.564 | 9.0 | 0.9% | **0.6637** |

Dybala guadagna quasi quanto con il peso a 0.20 (+0.44 contro +0.55) **pagando
−0.005 di correlazione invece di −0.022**. Nessuna esplosione della coda: massimo
9.0 e quota dei ≥8 allo 0.9%, identici a oggi.

### E soprattutto: non inclina la scala

Il timore che alzare il peso gonfiasse i creativi costanti (Dimarco) era fondato.
La strada lineare **non ha quel difetto**:

| quintile di creatività | attuale ΔRedaz | xA 0.20 compressa | **xA 0.035 LINEARE** |
|---|---|---|---|
| Q1 (meno creativi) | −0.014 | −0.058 | **−0.010** |
| Q2 | +0.032 | −0.005 | **+0.028** |
| Q3 | +0.060 | +0.045 | **+0.055** |
| Q4 | +0.060 | +0.089 | **+0.052** |
| Q5 (più creativi) | +0.113 | **+0.213** | **+0.116** |

Escursione del gradiente: 0.127 oggi → **0.271** con il peso → **0.126** con la
linearizzazione. Cioè invariata.

E Dimarco resta fermo: 6.857 → 6.821 (lineare) contro 7.054 (peso). Le sue gare
senza assist né gol: 6.400 → 6.333 contro 6.533.

**Perché funziona**: linearizzare agisce solo sull'alto della curva. Dybala sta a
u = 9.7, dove oggi si trattiene il 24%; Dimarco sta a u ≈ 3.0 in una gara tipica,
dove il peso più basso (0.035 contro 0.05) compensa la decompressione. Il peso
invece moltiplica tutto, e tutto include ogni partita di ogni creativo.

### Il limite, che va detto

**Diouf non ne beneficia**: 5.93 → 5.97. Conferma §1bis — lui non è un problema di
curva, è un falso negativo dello strumento, e va risolto lì (`key_passes` a zero,
`big_chance_created` che non scatta). Questa strada risolve **un** guasto dei due.

*Caveat: la kurtosi grezza della xA (+17.2, max 13.5σ) rientra nell'indice per
intero. Alla stagione 25-26 non produce nulla di anomalo (massimo 9.0, ≥8 allo
0.9%), ma è il peso 0.035 a tenerla, non la forma. Alzare quel peso su una xA
lineare non è la stessa cosa che alzarlo su una compressa.*

---

## 2novies. VINCOLO DI DEPLOY: una ritaratura NON lascia intatto il passato

Accertato il 24/08/2026, con la giornata 1 già conclusa in produzione (lega 3
«Quelli che il fanta», `FantasyMatchday` 10, chiusa alle 21:45 dopo che tutte e
dieci le partite erano finite e `data_ready` — quindi il referto è sano).

### Cosa sopravvive a una ritaratura

Scritto al **Concludi** e mai più ricalcolato
(`classic_matchday_scoring.py:830-855`):

* `FantasyFixture.home_total` / `away_total` — il punteggio fanta della sfida
* `FantasyFixtureDetail.payload` — il referto completo, voto per voto
* `FantasyMatchday.ruleset_snapshot` — il regolamento

**Le classifiche non si muovono.** Sono numeri in tabella, non una vista.

### Cosa invece cambierebbe retroattivamente

Ricalcolato a ogni lettura:

* la **pagella del campionato reale** (`classic_pagella.pagella_for_match`)
* il **registro del voto** («altre voci»)
* il **listone**

Diouf comparirebbe a 6.5 nella pagella di Inter-Monza, mentre il referto che ha
prodotto il suo fantavoto porta 6.0.

### E la cache non protegge — anzi

`data_version` e `matchday_data_version` sono impronte dei **dati** (partite
finite, presenze), **non dei pesi**. Il listone invece ha `scoring_fingerprint`
nella chiave, aggiunto proprio dopo un incidente di cache stantia
(v. memoria `listone-cache-was-stale`): la pagella quella correzione non l'ha
avuta. Per un turno concluso `matchday_data_version` non si muove più, quindi la
pagella resterebbe vecchia finché la cache regge — e un deploy riavvia il
processo e la svuota. Risultato: voti vecchi o nuovi a seconda del momento.

### L'app se ne accorge già

`ClassicMatchDetail.tsx` calcola `stale = |ledger.voto − referto.voto| >= 0.05` e
avverte: *«Il referto congelato di una giornata passata è stato scritto con la
taratura del modello di allora»*. Chi ha scritto quel codice aveva previsto
esattamente questo scenario. È un avviso, non una protezione.

### Il pezzo che manca

`FantasyMatchday` congela il **regolamento** ma non il **modello di voto**: non
c'è nessun campo che ricordi con quale taratura quel turno è stato chiuso. Il
`weights_fingerprint` di `vote_reference.json` intercetta il disallineamento e
obbliga a `calibrate_vote_reference`, ma quella riscrive il riferimento **globale**:
non esiste versionamento per stagione né per giornata.

### Le tre strade

1. **Congelare il riferimento per giornata** — salvare la taratura (o la sua
   impronta) su `FantasyMatchday` al Concludi, e far usare quella a
   `pagella_for_match` per i turni conclusi. È la correzione pulita, e il modello
   c'è già: `ruleset_snapshot` fa esattamente questo per il regolamento.
2. **Ritarare solo fra una stagione e l'altra.** Pulito, ma vuol dire aspettare.
3. **Accettarlo**: le classifiche non si muovono, cambia solo ciò che si vede, e
   l'avviso di disallineamento esiste già.

### DECISO il 25/08/2026: si accetta (opzione 3)

Motivazione: una ritaratura è un evento **sporadico**, e la divisione è quella
giusta — i risultati delle sfide di lega già concluse non si toccano (e infatti
non si toccano, sono congelati), mentre le pagelle di Serie A ha senso che
mostrino sempre il modello più recente, cioè il migliore disponibile.

Conseguenza operativa da ricordare: dopo una ritaratura, su un turno già concluso
il referto e la pagella possono divergere, e l'avviso `stale` di
`ClassicMatchDetail.tsx` è ciò che lo dichiara all'utente. Non è un bug da
inseguire.

L'opzione 1 (riferimento congelato per giornata) resta la correzione pulita se un
giorno la divergenza dovesse dare fastidio.

---

## 2decies. Perché la media resta 6, sempre

Domanda naturale guardando il confronto della giornata 1: se tanti voti salgono,
la media non dovrebbe alzarsi?

**Il bilancio completo di quel test** (la tabella mostrata in sessione era
fuorviante: 20 righe di risalite contro 12 di discese, quando in realtà scendono
più di quanti salgono):

| | n | somma |
|---|---|---|
| salgono | 26 | **+14.0** (di cui Dybala da solo +1.5) |
| scendono | **31** | **−15.5** |
| invariati | 231 | — |
| **netto** | 288 | **−1.5**, cioè −0.005 a voto |

Media 6.0260 → 6.0208: scende, di un millesimo e mezzo.

**E non è un caso, è costruzione.** Il voto è

```
voto = 6 + K · shrink · (indice − media_di_ruolo) / std_di_ruolo
```

e `media_di_ruolo` / `std_di_ruolo` vengono **ricalcolate sull'intera stagione a
ogni ritaratura**. Qualunque vettore di pesi produce media ≈ 6 per costruzione:
cambiare i pesi può solo **ridistribuire**, mai gonfiare. Si vede nei riferimenti:

| ruolo | media indice | std |
|---|---|---|
| DIF | 0.1724 → **0.2546** | 0.4200 → **0.4892** |
| CEN | 0.2821 → **0.4099** | 0.4200 → 0.4892 |
| ATT | 0.3235 → **0.4454** | 0.4200 → 0.4892 |

L'indice cresce per tutti (c'è più peso nel blocco creazione) e la media di ruolo
cresce con lui, annullandolo. La std cresce a sua volta e ricomprime la
dispersione.

*(Il 6.026 di partenza non è un bias: è una giornata sola contro una taratura di
stagione. La media di stagione è 6.007.)*

### E se si spedissero i pesi SENZA ricalibrare

Misurato sulla stessa giornata, pesi nuovi e riferimento vecchio:

| | media | std |
|---|---|---|
| ritaratura corretta | 6.021 | 0.562 |
| **pesi nuovi, riferimento vecchio** | **6.153** | **0.644** |

**+0.13 di inflazione e dispersione allargata**, con 78 voti su 288 diversi da
quelli giusti. È esattamente il caso che `weights_fingerprint` in
`vote_reference.json` esiste per intercettare, ed è il motivo per cui
`calibrate_vote_reference` non è un passo facoltativo del deploy.

---

## 3bis. QUELLO CHE E' STATO FATTO — 25/08/2026

Applicato in locale, **non ancora spedito**.

| | prima | dopo |
|---|---|---|
| `expected_assists` | 0.05 · compressa | **0.14 · lineare** |
| `big_chance_created` | 0.045 | **0.0** |
| `key_passes` | 0.0 | **0.100** |
| `weights_fingerprint` | `627a5e53b86a2ba6` | **`bbbbd853e561cf3f`** |

`calibrate_vote_reference --season 2` eseguito. Reference: DIF 0.253 / CEN 0.408 /
ATT 0.444, spread 0.488.

**Verifiche**: `check_vote_centering` tiene tutti i ruoli sul 6 (ATT 6.008,
CEN 6.007, DIF 6.003, POR 6.042); 84 test verdi. Sulla giornata 1 della 26-27:
**Diouf 6.0 → 6.5**, **Dybala 6.5 → 8.0**, 25 salgono / 31 scendono / 232 fermi,
media 6.026 → 6.019, dispersione e massimo invariati.

### La spiegazione, rivista di conseguenza

La ritaratura ha reso false due cose che la spiegazione diceva:

1. **Nota simmetrica sull'assist: TOLTA.** Diceva «non risulta un'occasione nitida,
   che nel voto base pesa a parte» — vera finché `bcc` pesava, falsa ora che pesa
   zero. E superflua: il caso che la motivava (Diouf) adesso è 6.5 da solo.
2. **Nota sull'assist da xA bassa: RISCRITTA.** Diceva «conta come bonus, non nel
   voto base», e con `key_passes` acceso è falso — un passaggio chiave vale +0.055
   per un CEN a 90', tre ne valgono +0.236. Ora dice *«il voto base legge quello,
   non il gol che ne è nato»*. Il soppressore su `big_chances > 0` resta, ma per
   una ragione nuova: se il fornitore ha riconosciuto una palla-gol, dare del
   «pallone di poco valore» allo stesso passaggio sceglie una delle due prove e
   nasconde l'altra (131 presenze su 300).

E una aggiunta: **`big_chance_created` a peso zero resta utilizzabile per
RACCONTARE**. Il peso dice quanto un dato vale nel voto, non se si può usare per
spiegarlo. La riga della xA si ancora ora al conteggio, **nei due versi**:

| | riga della creazione |
|---|---|
| Dybala (xA 1.09, 3 occasioni) | *…occasioni create per i compagni* **(3 nitide)** |
| Diouf (xA 0.34, nessuna) | *…occasioni create per i compagni* **(nessuna nitida)** |

I punti restano interamente della xA: la parentesi è una precisazione, non un
secondo addendo. Il verso negativo distingue due partite che la sola xA confonde —
tanti palloni discreti e una palla-gol vera valgono uguale in valore atteso e non
sono la stessa prestazione — e si dice **solo sopra `ASSIST_LOW_XA`**, dove
l'assenza è una notizia: 613 presenze sulla 25-26 (3,4%) contro le 609 che
ricevono il conteggio.

**Il gol che ne è nato non si nomina, in nessuno dei due versi.** La qualità
dell'occasione è una proprietà del passaggio, l'esito no, e metterlo sulla riga del
merito confonderebbe la distinzione su cui il modello è costruito.

### Perché Diouf NON riceve la nota sull'assist, e non deve

Misurato sulle 205 presenze con assist e nessuna occasione nitida: la sua xA è
**7,1 volte** la mediana di quella popolazione (0.339 contro 0.048), 3,5 volte per
assist, 3,2 volte per passaggio chiave. I suoi palloni sono stati **buoni**, e la
nota «di poco valore» direbbe il falso. Quel che lo tiene a 6.5 non è la creazione
sottopagata — vale +0.64, fra le più alte della giornata — ma il resto della
partita, ed è ciò che la sua frase dice.

*(Verificato anche che dividere la soglia per il numero di assist non cambierebbe
NIENTE: in quella popolazione le presenze con 2+ assist sono due, e scattano già
entrambe. Dividere per i passaggi chiave farebbe scattare la nota sul 96%.)*

---

## 3ter. Verifica di chiusura: ordiniamo come SofaScore, non come loro scaliamo

Il caso Diouf letto una volta di più, alla fine del lavoro. L'Inter di Inter-Monza
ordinata dal rating del fornitore:

| | giocatore | gol | assist | xA | tiri | Sofa | noi (nuovo) |
|---|---|---|---|---|---|---|---|
| 1 | Çalhanoğlu | 1 | 0 | 0.02 | 1 | 8.0 | 7.0 |
| 2 | Bisseck | 1 | 0 | 0.01 | 1 | 7.9 | 7.5 |
| 3 | Zieliński | 1 | 0 | 0.02 | 1 | 7.8 | 6.5 |
| 4 | Esposito | 1 | 1 | 0.02 | 5 | 7.6 | 7.0 |
| **5** | **Diouf** | 0 | **2** | 0.34 | **0** | **7.6** | **6.5** |

**Diouf è quinto nella sua squadra anche per SofaScore**, pari merito con Esposito e
dietro tre marcatori. *(Va corretta un'affermazione fatta all'inizio dell'indagine:
«terzo rating del campo» era sbagliato — nasceva dal leggere una lista ordinata
secondo il NOSTRO voto.)*

| | dentro l'Inter |
|---|---|
| correlazione di rango, modello vecchio | +0.818 |
| **modello nuovo** | **+0.921** |
| dispersione SofaScore / nostra | 0.54 / 0.51 |

Quel che resta è il **bias di scala** già noto: la nostra scala sta ~0.82 sotto la
loro ovunque, quindi il 6.5 di Diouf vale ~7.3 dei loro contro il 7.6 che gli danno
— tre decimi, dentro un passo di arrotondamento. Col modello vecchio l'eccesso era
0.8.

Sulla giornata intera il rango migliora poco (+0.704 → +0.715): la ritaratura
riordina **i creatori**, e in una giornata sono pochi. Dentro una squadra che ne
aveva due, il salto è grande.

---

## 3quater. Il credito per l'assenza, e le due leve del dribbling — 25/08/2026 pomeriggio

Aperto da un'inversione: **Yıldız 7.0 e Conceição 6.5**, quando a occhio è il
contrario. Yıldız 2 duelli su 2, 2 dribbling su 2, 34 tocchi; Conceição 5 su 16,
4 dribbling riusciti su 9, 53 tocchi. Il primo aveva fatto poco e non aveva
sbagliato niente, il secondo aveva provato molto.

### Il credito per l'assenza

**Che cos'è.** Lo `z` non è centrato: `z = compressione(valore/σ)/σ_z`, e per un
conteggio è ≥ 0 sempre. La media della popolazione `mu_z` è positiva, quindi una
feature a **peso negativo** che vale zero **paga**: il giocatore medio porta il
malus, chi non ha giocato il duello no. In voto, quanto incassava chi ha zero:

| voce | credito prima | credito dopo |
|---|---|---|
| duelli persi | 0.185 | 0.042 |
| passaggi sbagliati | 0.064 | 0.013 |
| duelli aerei persi | 0.047 | 0.021 |
| dribbling concessi | 0.038 | 0.025 |
| controlli sbagliati | 0.031 | 0.013 |
| palloni persi in conduzione | 0.019 | 0.012 |
| falli commessi | 0.019 | 0.008 |
| **zero su tutte e sette** | **0.404** | **0.132** |

Il premio per non aver perso un duello valeva **più** di quello per averne vinti
quattro. È il difetto che la riduzione ×0.8 del blocco volume aveva individuato
("un terzo del vantaggio veniva da cose che NON aveva fatto") ma non poteva
curare: non è una coda, è il livello, e nessuna trasformazione per-feature lo
tocca.

**La cura, e il suo limite ONESTO.** `ABSENCE_CREDIT = 0.0` schiaccia sulla media
la metà sotto la media: `z* = max(z, mu_z)`. Ma così **E[z\*] > E[z]**
(duelli persi: 1.776 → 2.176), quindi chi sta a `mu_z` è sotto la nuova media e
con peso negativo contribuisce **ancora** più della media. **Il credito non è
eliminato: è reso uniforme** — 0.404 → 0.132, un terzo. Sparisce l'ordinamento
DENTRO il gruppo dei non coinvolti, che è quel che serviva.

**E non si può portare a zero.** Tagliando a una soglia `v`, il credito è
`E[max(z,v)] − v`; azzerarlo vorrebbe `v = E[max(z,v)]`, ma
`g(v) = E[max(z,v)] − v` ha `g'(v) = P(z<v) − 1 ≤ 0`: scende verso zero e non lo
tocca a `v` finito. Misurato su `duels_lost`: a `mu_z` credito 0.042 (55%
tagliati), a 1.5·`mu_z` 0.012 (82%), a 2·`mu_z` 0.002 (95%). **Per cancellare il
credito bisogna cancellare la feature.**

**La cura strutturale sarebbe un'altra forma, e non è stata provata.** Il credito
esiste perché è un CONTEGGIO. Un **tasso** — `duelli persi / duelli ingaggiati` —
è indefinito per chi non ne ha ingaggiati, gli si assegna la media, ed è
esattamente medio: credito zero, esatto. È quel che la coppia
`dribbles_won`/`dribbles_attempted` approssima. Cambio di disegno, non di peso.

**Il livello del voto NON si sposta** (v. §2decies): la media dell'INDICE sì,
0.3411 → 0.2612, ma `build_reference` prende la media dello stesso indice
trasformato, e lo scarto medio dalla media di ruolo resta zero a precisione di
macchina. Voto grezzo medio 6.0168 → 6.0196: i tre millesimi sono l'attenuazione
sui minuti, non lo spostamento. **L'ordine è tutto**: `mu_z` congelato dentro la
trasformazione (non insegue se stesso), media di ruolo ricalcolata dopo.

**Che cosa NON è nell'insieme creditato, e perché**: `dribbles_attempted` (non è
un evento negativo, è il denominatore di un tasso; misurato, è un pareggio:
Redazione +0.0004, SofaScore −0.0022); `errors_led_to_goal`,
`penalties_conceded`, `errors_led_to_shot` (mu_z ≈ 0.1, il credito vale 0.006 di
voto a testa — coerente toglierlo, ma non misurato a parte); il canale del
portiere (nessuna voce negativa è un conteggio di volume).

### `dribbles_attempted` −0.0194 → −0.012

Quel che conta è il **rapporto** con `dribbles_won`, e il nostro era fuori scala.
Fittato sulla 25-26, n=6829 presenze ≥60', gol e assist controllati, per 1σ:

| | riusciti | tentati | rapporto |
|---|---|---|---|
| Redazione | +0.069 | −0.022 | −0.32 |
| SofaScore | +0.162 | −0.083 | −0.51 |
| noi (era) | +0.0252 | −0.0194 | **−0.77** |
| noi (ora) | +0.0252 | −0.012 | **−0.48** |

**Il doppione col pallone perso è REALE ma MINORE di come veniva ricordato**: un
dribbling fallito aggiunge +0.232 `dispossessed` registrati (0 falliti → 0.51 di
essi, ≥3 falliti → 1.28), circa uno su quattro. Il 79% che sta nel commento del
codice riguarda `possessionLostCtrl`, un aggregato che NON portiamo — non è
questo. La sovrapposizione giustifica un ritocco; **il rapporto giustifica la
misura**.

### I tocchi: leva CHIUSA, misurata tre volte

L'ipotesi era che il volume di gioco fosse sottopagato (noi 0.0203 di voto per
1σ contro +0.070 della Redazione e +0.192 di SofaScore).

1. **A bilancio aperto** (alzando solo `touches`): Redazione peggiora in modo
   monotono, 0.6436 → 0.6418 (.020) → 0.6401 (.028) → 0.6380 (.036); SofaScore
   fermo.
2. **A bilancio chiuso** (travasando da `passes_completed`, che misura quasi la
   stessa cosa): 0.6437 → 0.6437 (metà) → 0.6432 (totale). Niente.
3. **Tocchi in metà campo avversaria** (colonne 3-4 della griglia zone, che si
   ricavano senza riscaricare nulla), al netto dei tocchi totali: Redazione DIF
   +0.001, CEN −0.011, ATT −0.039; SofaScore DIF −0.004, CEN −0.005, ATT −0.071.

Il motivo del terzo è strutturale: **la quota di tocchi alti È il ruolo** (DIF
22%, CEN 38%, ATT 59%), e separare i ruoli è quel che la z-standardizzazione per
ruolo fa già. La partecipazione è già nel modello, la portano i passaggi, i
passaggi in metà campo avversaria, i duelli e i recuperi.

### Il risultato, e quello che NON risolve

Contro il modello in produzione: **20 voti su 288** si muovono (6 su, 14 giù),
spostamento medio −0.010. Yıldız 7.0 → 6.5, gli altri casi fermi. Accordo sulla
25-26, stesso metodo per entrambi: Redazione −0.0020, Statistico −0.0039,
SofaScore −0.0080, difensori sulla Redazione −0.0079.

**Il bersaglio non è raggiunto e non era raggiungibile con queste leve.**
Yıldız 6.734 e Conceição 6.662: l'inversione è corretta ma cadono nello stesso
6.5, e a 6.734 Yıldız è a **16 millesimi** dal tornare 7.0. Tutte le leve li
alzano INSIEME, perché 2/2 e 44 tocchi per 90' non sono sotto media. L'unica che
li separa è il credito (−0.145 contro +0.028): il vantaggio di Yıldız *era* quel
credito.

### Gila e il duello con Njie: quel che il fornitore ci dà e quel che no

L'evento **c'è**: `challengeLost` → `dribbled_past` = 1, −0.086 di voto **in
più** del duello perso ordinario. Quel che non c'è, e non è recuperabile da
questa fonte: **il minuto** (le statistiche per giocatore sono totali di partita;
solo gli *incidents* portano un minuto), **il posto** (`challengeLost` è di
distinta, non è posato sul campo — solo i *tocchi* lo sono, via la mappa di
calore), **la gravità**. La conseguenza invece la sappiamo, ed è nulla:
`errorLeadToAShot` e `errorLeadToAGoal` sono entrambi 0, e `clearances`/`blocks`
pure. Pesare quell'evento per gravità richiede dati a livello di evento, che
questo fornitore non espone.

Il 7.0 di Gila non viene da lì: viene da **`defensive_value`**, +0.369 di voto da
solo, quattro volte il costo del duello con Njie, con z=2.27 contro una media di
0.065. Ridurlo 0.10 → 0.085 è stato misurato e **costa** (Redazione −0.005,
SofaScore −0.004): si sta pagando il suo peso, non è stato toccato. La tensione
da nominare: quel numero il fornitore lo calcola SAPENDO di quel duello, e lo
valuta comunque 0.55.

### `dribbled_past` per ruolo, e i due limiti che ha fatto vedere

**Prima eccezione al vettore unico di pesi** (`ROLE_WEIGHTS`): DIF −0.045, CEN 0,
ATT 0. La previsione calcistica — essere saltati e' un evento di mestiere per un
difensore, un non-evento per un attaccante in ripartenza — **regge nei dati
grezzi**, e controllata per il duello perso ORDINARIO di cui e' sottoinsieme:

| per 1σ | DIF | CEN | ATT |
|---|---|---|---|
| Redazione | **−0.040** ±0.011 | +0.004 | **+0.026** ±0.012 |
| Statistico | **−0.035** ±0.012 | −0.007 | +0.003 |
| SofaScore | −0.006 | +0.010 | +0.008 |

Le due pagelle umane lo addebitano **solo al difensore**, con 3-4σ di margine;
per l'attaccante la Redazione ha perfino il segno positivo. SofaScore non lo
distingue per nessuno. Frequenza: 0.50/partita per un DIF (14.9% dei suoi duelli
persi), 0.33 per un ATT (6.0%).

**Ma nel modello non paga**, ed e' la seconda meta' della lezione. Lo spettro fra
peso globale, peso per ruolo e azzeramento totale e' **0.003 di correlazione**, e
l'arm nominalmente migliore sulla Redazione era azzerare la feature (0.6475
contro 0.6445). Nessun arm muove un voto dei casi. La ragione: `duels_lost` pesa
da noi −0.102 di voto per σ contro il −0.034 della Redazione, **tre volte** — il
posto che il giudice riempie col dribbling subito, noi lo abbiamo gia' occupato
col duello perso. Isolato, il peso per ruolo muove 7 voti su 288 (quasi tutti
centrocampisti) e vale Redazione +0.0012, Statistico −0.0018, SofaScore −0.0005.
Tenuto per il senso calcistico, non per la misura.

### LA LEZIONE DELLA GIORNATA: un peso ORDINA, non alza

Chiesto: quanto deve pesare `dribbled_past` sui DIF perche' Gila scenda da 7.0 a
6.5? Risposta: **−0.30**, cioe' 4.8× il duello perso di cui e' un sottoinsieme.
E la curva e' piattissima — da −0.045 a −0.20 (4.4×) Gila perde 0.14 di voto.

Il motivo e' strutturale e vale per OGNI leva provata oggi: **alzando un peso si
sposta anche la media di ruolo**. Tutti i difensori saltati scendono insieme, la
media DIF scende con loro, e chi sta in mezzo alla distribuzione resta dov'era.
Gila e' saltato UNA volta, che e' la media del ruolo (0.50): nessun peso su
quella voce lo puo' isolare dai suoi pari. **Per muovere un giocatore singolo
bisogna che su quella feature sia un caso estremo.**

Lo stesso, in forma piu' forte, su `defensive_value` — dove Gila SI' e' un caso
estremo (z=2.27 contro media 0.065), ed e' da li' che nasce il suo 7.0 (+0.369 di
voto da solo, quattro volte il costo del duello con Njie):

| peso `defensive_value` | Gila | **media voto DIF** |
|---|---|---|
| 0.100 | 6.912 | **6.002** |
| 0.085 | 6.880 | **6.003** |
| 0.070 | 6.846 | **6.002** |
| 0.025 | 6.72 → 6.5 | — |

**La media dei difensori NON si muove di un millesimo.** La
z-standardizzazione per ruolo inchioda ogni ruolo al 6 per costruzione e la
ricalibrazione riassorbe tutto (v. §2decies). Confermato invece che i difensori
sono il ruolo piu' generoso: media nostra 6.002 contro 5.922 della Redazione
(**+0.080**), contro +0.018 dei CEN e +0.014 degli ATT. Ma quello e' un problema
di CENTRO, non di pesi, e l'offset di ruolo e' deciso e chiuso dal 02/08/2026.

### `defensive_value` 0.100 → 0.085 — per esposizione, non per taratura

Deciso il 25/08/2026 sapendo che **costa su tutti e tre i giudici**, e sui soli
difensori due-tre volte tanto:

| | tutti | solo DIF |
|---|---|---|
| Redazione | −0.0033 | −0.0076 |
| Statistico | −0.0040 | −0.0100 |
| SofaScore | −0.0051 | −0.0126 |

(a 0.070 il conto raddoppia ancora.) La ragione tenuta e' **l'esposizione**: dare
il peso piu' alto del modello a un numero che il fornitore calcola con un metodo
ignoto e che puo' sparire senza preavviso — il RISCHIO OPERATIVO gia' scritto
accanto a `DEFENSIVE_VALUE_SOURCE` — e' una dipendenza che vale la pena ridurre
anche pagandola. La ragione SCARTATA, perche' misurata falsa, e' che abbassi il
livello dei difensori: non lo fa.

### Il conto totale della giornata

Contro il modello in produzione, e scomposto per intervento:

| | Redazione | Statistico | SofaScore | Red DIF |
|---|---|---|---|---|
| credito assenza + tentati | −0.0020 | −0.0039 | −0.0080 | −0.0079 |
| `dribbled_past` per ruolo | +0.0012 | −0.0018 | −0.0005 | −0.0006 |
| `defensive_value` 0.085 | −0.0033 | −0.0040 | −0.0051 | −0.0076 |
| **totale** | **−0.0041** | **−0.0097** | **−0.0137** | **−0.0160** |

Da 0.6465 / 0.6766 / 0.7700 a 0.6425 / 0.6669 / 0.7563. **Nessuno dei quattro
interventi e' stato preso perche' migliorava l'accordo**: tre su quattro lo
peggiorano e sono stati presi per ragioni di principio (il credito che premiava
il non-fare, il rapporto del dribbling fuori dalla forbice dei giudici,
l'esposizione a un numero opaco). E' una scelta legittima ma va vista in blocco,
non una alla volta.

### Il CENTRO del ruolo — la leva che i pesi non erano (25/08/2026, spedito)

`ROLE_VOTE_CENTER = {DIF: 5.91}`, media DIF realizzata **5.917**. E' la sola cosa
che muove il LIVELLO di un ruolo, ed e' la conferma per contrasto di tutto il
resto della giornata: nessun peso lo muoveva, questo si', perche' non passa per
l'indice.

**Il centro non e' la media, e la differenza e' tutta l'ARROTONDAMENTO.** Misurato
sulle 3908 presenze DIF:

| centro | media PRIMA di arrotondare | scarto | media DOPO | bias |
|---|---|---|---|---|
| 6.000 | 6.0010 | +0.0010 | 6.0026 | +0.0016 |
| 5.930 | 5.9310 | +0.0010 | 5.9365 | +0.0056 |
| 5.920 | 5.9210 | +0.0010 | 5.9278 | +0.0069 |
| 5.910 | 5.9110 | +0.0010 | 5.9173 | +0.0064 |
| 5.750 | 5.7510 | +0.0010 | 5.7449 | **-0.0061** |

Lo scarto prima di arrotondare e' **+0.0010 a qualunque centro**: il modello e'
centrato esattamente dove gli si dice. Dopo, la griglia del mezzo punto e' FISSA
sui multipli di 0.5 mentre la distribuzione la spostiamo — a centro 6.00 il picco
sta su un nodo e i due lati si compensano, a 5.91 sta 0.09 sotto e piu' massa
sale a 6.0 di quanta ne scenda a 5.5, a 5.75 il segno si rovescia. **La media
dopo l'arrotondamento non e' una funzione liscia del centro.**

**Il centro deve stare sui CENTESIMI.** La spiegazione del voto riconcilia a due
decimali (`base` + voci mostrate + `other_points` = `subtotal`) e tutte le sue
voci sono arrotondate al centesimo: con 5.912 quattro test della riconciliazione
fallivano di 0.008 esatti. Per una taratura piu' fine va prima resa robusta la
riconciliazione, non alzata la tolleranza dei test.

**La mitigazione del risultato ora misura la divergenza dal centro DEL RUOLO.**
Altrimenti un difensore esattamente nella media passava per «voto basso in una
vittoria» e veniva spinto su in ogni vittoria: un offset che si mangia da solo
(+0.015 sulla media realizzata).

**Il MODIFICATORE DIFESA non si compensa, e scatta meno spesso.** La sua soglia e'
6.00 assoluto, un numero FISSO del regolamento che non insegue il centro del
ruolo: bonus medio **+1.071 -> +0.915**, squadre a zero bonus dal **38.9% al
44.5%**. E' l'effetto voluto — se un difensore ordinario non vale piu' 6, la
difesa che prende il bonus deve essere piu' brava. Una compensazione
(`voto_puro_base6` + `vote_on_common_scale`) era stata scritta e poi TOLTA: non
riproporla. Stesso discorso per la scala 66/+6, dove pero' compensare romperebbe
la somma VISIBILE del tabellino.

**E l'accordo ci guadagna dove serviva.** Una traslazione non muove una
correlazione, ma riallinea l'arrotondamento, e noi eravamo sistematicamente sopra
la Redazione: **0.6425 -> 0.6455**. Statistico -0.0006, SofaScore -0.0007.

### Spedito in produzione il 25/08/2026 (`d3a661d`)

Verificato sul server: media DIF della giornata 1 26-27 = **5.923** (POR 5.975,
CEN 6.000, ATT 6.037), Yıldız 7.0 -> 6.5. Impronte del modello identiche fra
locale e produzione (`d0296353612d9f75` / `a794ace234b1061b`); cache su file
svuotata a mano, che il riavvio non basta.

**Una divergenza PREESISTENTE trovata dal confronto, da non confondere con
questo lavoro**: l'impronta dei VOTI differisce fra locale e produzione su 27
presenze delle 11903 della 25-26 (0.23%, sempre mezzo punto). Causa: 396 presenze
hanno ruolo **CEN in locale e ATT in produzione** — tutte trequartisti ed esterni
al confine (Berardi, Nico Paz, De Ketelaere, Pellegrini, Baldanzi, Samardzic). E'
`current_role_map` che diverge fra le due installazioni, non il modello. Il passo
del runbook che la chiuderebbe e' `compute_classic_roles`, che pero' cambierebbe
il ruolo di quei giocatori sulla stagione VIVA: non e' stato lanciato.

---

## 2bis. La trappola di taratura, che generalizza

**Qualunque feature correlata con un evento bonus assorbe quel bonus, se la si
tara contro un giudice che lo paga.** bcc è il caso che abbiamo trovato; non è
il solo.

Screening su 6.829 presenze di movimento ≥60' (gol inclusi, sono un controllo):
coefficiente sul voto Redazione da solo, e con gol+assist come controlli.
Coefficienti per 1 deviazione standard della feature.

| feature | da sola | con gol+assist | collasso |
|---|---|---|---|
| onTargetScoringAttempt | +0.234 | +0.034 | 86% |
| totalShots | +0.155 | +0.018 | 89% |
| **bigChanceCreated** | +0.142 | +0.052 | **63%** |
| keyPass | +0.134 | +0.060 | 55% |
| expectedAssists | +0.122 | +0.057 | 54% |
| wonContest | +0.086 | +0.050 | 42% |
| duelWon | +0.076 | +0.066 | 13% |
| defensiveValueNormalized | +0.236 | +0.229 | **3%** |
| totalTackle | +0.026 | +0.051 | −98% |
| totalClearance | +0.004 | +0.057 | (base ≈ 0) |
| interceptionWon | +0.000 | +0.029 | (base ≈ 0) |

Tre letture:

* **Tutto il blocco offensivo è contaminato**, non solo bcc. Fra le tre misure
  di creazione bcc è la più contaminata (63%) ma xA e keyPass non sono lontane.
  Il confronto che decide resta quello **congiunto** della tabella (B), dove xA
  e bcc competono: lì xA conserva +0.364 e bcc +0.080.
* **Il blocco difensivo è il contrario**: i coefficienti *crescono* controllando
  per gol e assist. Chi respinge e contrasta molto sta in una squadra sotto
  assedio, che segna poco; il coefficiente grezzo è mascherato. Fittare le
  feature difensive ingenuamente contro le pagelle le **sottovaluta**.
* **`defensiveValueNormalized` è pulito** (3% di collasso, +0.236: il
  coefficiente non-contaminato più grande della tabella). Il suo peso 0.10 è
  giustificato — con la riserva già documentata sul carico di risultato.

Cautela: coefficienti univariati, le feature sono correlate fra loro. È uno
*screening di contaminazione*, non un fit da cui prendere pesi. La colonna
«collasso» è priva di senso quando la base è ≈ 0 (le ultime due righe): lì si
leggono i valori assoluti.

**Regola da applicare alla prossima ricalibrazione**: rifittare con gol e assist
come controlli e guardare quali pesi si muovono.

---

## 3. `key_passes` a peso zero

`classic_rating.py:166`. Azzerato nel commit `e836ddb` (pesi a mano v2), prima
era 0.181, **senza motivazione scritta**. È la terza misura dello stesso gesto,
e la più pulita: nessun modello xG, nessun giudizio del fornitore, solo «ha
giocato il passaggio da cui è nato un tiro».

Controfattuale misurato, **con la taratura ricostruita da capo** (alzare un peso
alza anche media e dispersione di ruolo: la versione ingenua dà +0.5 e mente):

| | n | voto | cambiati |
|---|---|---|---|
| CEN ≥60' (tutti) | 2450 | 6.074 → 6.088 (+0.014) | 760 |
| CEN ≥60', ≥1 assist, 0 tiri | 58 | 5.991 → **6.164** (+0.172) | 20, **tutti in su** |
| tutte le presenze a voto | 10699 | 6.007 → 6.006 (−0.001) | 2673 |

Mirato sull'archetipo, distribuzione globale ferma. Ma cambia il 25% dei voti:
l'accordo coi due fogli va rimisurato prima di muoverlo. **Non fatto.**

---

## 4. Lo strato delle spiegazioni — CORRETTO il 24/08/2026

Scansione su tutte le 10.699 spiegazioni della 25-26.

**Il 59,18% contiene almeno una riga che descrive qualcosa che il giocatore non
ha fatto.**

| difetto | n | % |
|---|---|---|
| famiglia «conclusioni» frasata su ZERO tentativi | 4615 | 43,13% |
| «pochi X» con X = 0, in «Male» (rimprovero per un'assenza) | 2661 | 24,87% |
| «pochi X» con X = 0, in «Bene» (lode per un'assenza) | 1577 | 14,74% |
| TUTTI i rimproveri sono cose mai fatte | 1502 | 14,04% |
| TUTTE le lodi sono cose mai fatte | 449 | 4,20% |
| l'INTERA frase parla solo di assenze | 130 | 1,22% |
| «prestazione in linea con la media del suo ruolo» (frase vuota) | 113 | 1,06% |
| assist di merito senza flag, nessuna nota | 36 | 0,34% |

I tassi di zero sono **veri**, non un difetto dei dati: sulle presenze ≥60' il
48,7% non tira mai, il 55,9% non fa un passaggio chiave, il 31,7% non respinge.
Il difetto è nel modo di dirlo.

### 4.1 La famiglia unita frasata dal solo segno del netto

`vote_explanation.py:154`. I `MERGES` scelgono la frase dal segno del netto,
senza guardare se il giocatore abbia tentato qualcosa. Con tutti i tiri a zero
il netto è negativo (la media di ruolo è positiva) e la pagina dice **«Male: una
o più occasioni fallite»** a chi non ha tirato mai. `_never_happened` copre
questo caso per le feature singole; i `MERGES` lo saltano.

Esempi: `gg36 A. Obert (DIF, 88')` → *«Male: una o più occasioni fallite, poche
respinte»*, con zero tiri e zero respinte.

### 4.2 «pochi X» quando X è esattamente zero

`_phrase`, ramo COUNT. Il quantificatore è scelto confrontando con la media di
ruolo, e zero diventa «pochi». Due sottocasi, il secondo peggiore del primo:

* rimprovero: *«Male: pochi duelli vinti»* a chi non ne ha giocato nessuno;
* **lode**: *«Bene: pochi duelli persi»* a chi non è mai entrato in un duello.
  449 spiegazioni hanno **solo** questo come lato positivo.

`gg36 M. Nzola (ATT, 14', voto 6.0)`: *«Bene: pochi duelli persi | Male: una o
più occasioni fallite»* — l'intera frase su un giocatore che, per i dati, non ha
fatto niente di ciò di cui si parla.

### 4.3 Manca la nota simmetrica sull'assist

`vote_explanation.py:303-315`. Esiste la nota per l'assist a **basso** merito
(*«nasce da un passaggio di basso valore atteso: conta come bonus, non nel voto
base»*), che scatta solo se `xa < ASSIST_LOW_XA and big_chances == 0`.

Non esiste la simmetrica: **xA alta, nessuna big chance riconosciuta**. È la
casella di Diouf, 36 presenze sulla 25-26 — fra cui Modrić (gg2, xA 0.36), Soulé
(gg4, 0.40), McTominay, Berardi, Dybala. Lì la pagina non spiega niente del
perché il credito di creazione sia un terzo di quello di un pari-merito flaggato.

### 4.4 La frase vuota

113 casi di *«Prestazione in linea con la media del suo ruolo»*. Onesta (niente
supera la soglia di 0.05), ma il pannello non dice nulla — e fra questi ci sono
portieri che hanno giocato 90' (Audero, Bijlow, Falcone).

### 4.5 Cosa è stato fatto, e il risultato

Quattro correzioni in `vote_explanation.py`, **nessuna tocca un voto**:

1. `COUNT_NONE` — lo zero si chiama «nessun duello vinto», non «pochi». E se lo
   zero pesa **a favore** la riga si tace: elogiare per un duello non perso chi
   non è mai entrato in un duello è rumore. I punti restano e finiscono in «altre
   voci», quindi il conto torna.
2. Quinto campo nei `MERGES`, la frase di chi non ci ha nemmeno provato:
   «nessuna conclusione tentata». La penalizzazione resta visibile — il modello
   addebita davvero il non-tiro, e tacerlo lo nasconderebbe.
3. `assist_note` simmetrica per il passaggio di merito senza occasione
   riconosciuta. Al **plurale** quando gli assist sono più di uno, e **senza gergo
   interno**: chi legge non sa — e non deve sapere — che la creazione è pesata da
   due voci distinte. «pesa a parte» spiegava il modello invece della partita.

   > *I suoi passaggi valgono 0.34 di xA: gli assist nascono da buoni palloni, ma
   > non da occasioni nitide, e i gol non erano scontati.*

   **Due scelte consapevoli su questa frase.**

   *Il numero è attribuito a «i suoi passaggi», non all'assist*, perché è il totale
   della partita. Nel gruppo che riceve la nota (36 presenze) il **75%** ha
   passaggi chiave oltre agli assist — mediana 3 contro 1 — quindi buona parte di
   quel numero viene da palloni che assist non sono diventati. Metterlo accanto
   all'assist («l'assist nasce da un buon passaggio, xA 0.34») lo avrebbe
   attribuito a quel singolo pallone, che è falso in tre casi su quattro. Isolare
   la xA del passaggio da assist non si può: `MatchShot` non porta il passatore.

   *«i gol non erano scontati» invece di «merito a chi ha segnato».* Il docstring di
   `assist_note` registra una decisione contraria ad attribuire merito al
   finalizzatore, con una misura dietro (McKennie g14: la qualità del suo tiro era
   +0.67σ, cioè «ha fatto lui la cosa eccezionale» sarebbe stato inventare un
   merito). Un'occasione non nitida è per definizione una in cui il gol non è
   ragionevolmente atteso: dirlo della situazione è difendibile, dirlo del
   giocatore no.
4. Fallback per la partita piatta: si mostrano le due voci più grandi anche sotto
   soglia, con `flat=True` e un'avvertenza in `note` (che il dettaglio partita già
   stampa, quindi niente da toccare nel frontend). **Guardia**: non scatta se
   esiste una voce ≥ 0.05 che non sappiamo nominare — promuovere due voci da 0,01
   al posto di `defensive_value` direbbe che la partita è stata insignificante
   mentre il voto lo muoveva quella.

Tutte le etichette sono ora impersonali: nessuna nomina chi fornisce i dati.

Misura sulle stesse 10.699 spiegazioni, dopo:

| | prima | dopo |
|---|---|---|
| righe che descrivono male un'assenza | **59,18%** | **0%** |
| solo rimproveri per cose mai fatte | 14,04% | 0% |
| solo lodi per cose mai fatte | 4,20% | 0% |
| frase muta | 1,06% (113) | **0,46% (49)** |
| «nessuna conclusione tentata» (era una falsa accusa) | — | 4411 |
| note sull'assist emesse | 171 | **207** |

Le 49 mute residue sono portieri che hanno affrontato pochissimo (la nota sul
poco su cui giudicarli c'è già) e spezzoni da una quindicina di minuti.

### 4.6 `defensive_value` adesso parla — e la genericità è la parte onesta

Era la voce più grande del voto di molti difensori (il 20% in Rrahmani di
Genoa-Napoli) e non aveva una riga in `LABELS`, per una ragione buona: «tanto
valore difensivo» non spiega niente. Ora è un SIGNAL con due facce:

* **buona prestazione difensiva d'insieme**
* **prestazione difensiva d'insieme sottotono**

Generica per forza, e la genericità è ciò che la rende difendibile. L'indice è una
sintesi di un feed che non abbiamo (ogni duello con posizione, avversario e fase):
non si scompone in un gesto che il lettore ritrovi nel tabellino, quindi
promettergliene uno sarebbe una bugia. Ed è **in parte collettivo** — correla
−0.53 con i gol subiti mentre era in campo, più del rating di chi lo calcola
(−0.32) — per cui «d'insieme» dice il vero due volte.

La tabella tecnica tiene il suo nome tecnico (`TABLE_ONLY_LABELS` ha ora la
precedenza in `readable_label`): in una colonna accanto a valore, peso e sigma
serve un nome, non un giudizio.

Effetto: le mute scendono da 77 a **49**, e `defensive_value` compare nel
riassunto delle presenze in cui muove davvero il voto — inclusa quella di Diouf,
dove pesa −0.08 ed era invisibile.

### 4.7 Rimane un solo silenzio deliberato

L'unica feature pesata ancora senza frase parlata è `shots_off`, che compare solo
dentro la riga unita delle conclusioni e non ha mai bisogno di parlare da sola.
Il resto dei silenzi sono gli **EVENT che non sono accaduti** («nessun gol» a chi
non ha segnato): tacciono per scelta di sempre nella frase, e nel registro esteso
hanno la loro riga con i punti.

---

## 5. Riserve già registrate altrove, che restano aperte

* **xA dei difensori** — `classic_rating.py:130-136`. Confermata sulla giornata
  1: cinque dei primi dodici crediti di creazione sono difensori. Il rimedio è
  un trattamento per ruolo, non un peso globale più basso.
* **Livello dei portieri** (−0.15, strutturale) — vedi memoria
  `listone-cache-was-stale`.
* **Niente offset di ruolo** — deciso il 02/08/2026, non riproporlo.

---

## Come rifare le misure

Gli script della sessione del 24/08/2026 stanno nello scratchpad, non
versionati. Le due basi da ricostruire sono:

```sh
# il dataset appaiato (nostro voto + Redazione + Statistico + rating SofaScore)
python manage.py voto_puro_discrepancies --json /tmp/discrep.json

# il benchmark HTML, da leggere PRIMA di ogni analisi sul voto
python manage.py build_voto_benchmark
```

Da lì: le regressioni di §2 e §2bis sono OLS su `discrep.json` unito ai
`raw_stats` di `MatchAppearance`; il credito di creazione per presenza si ottiene
da `vote_explanation._terms` meno `classic_pagella.get_role_averages`,
moltiplicato per `VOTE_SPREAD_K · min/(min+25) / ref[ruolo]["std"]`.

**Trappola**: `raw_stats` **omette i campi a zero**. Filtrare per presenza della
chiave invece che trattare l'assenza come zero taglia fuori proprio gli eventi
rari — è come `bigChanceCreated` era sparito dal primo screening.
