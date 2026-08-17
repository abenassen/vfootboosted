# Reggere il carico ostile — piano

Stato: **DA FARE**. Analisi dei log del 17/08/2026, niente ancora implementato.
Numeri dell'asta misurati il 17/08/2026 (vedi «Quanto costa un'asta vera»): quelli
sì, e hanno cambiato la configurazione proposta.

| pezzo | dove | stato |
|---|---|---|
| `limit_req` in nginx, **con chiave per token** | `deploy/nginx/vfoot-limits.conf`, `vfoot.it.conf` | **scritto, da installare** |
| jail fail2ban sui 429 **di auth** e sui probe PHP | `deploy/fail2ban/jail.d/vfoot.local` | **scritto, da installare** |
| throttle DRF sugli endpoint che calcolano hash | `config/settings.py`, `vfoot/api/views.py` | **fatto** |
| prova di carico dell'asta | `manage.py auction_load_test` | **fatto** |
| avviso quando la CPU sta al muro | `deploy/systemd/vfoot-health.*` | da fare |
| Cloudflare davanti / seconda vCPU | decisione, non lavoro | da decidere |

**Niente di questo è ancora in produzione**: i file di nginx e fail2ban sono
scritti e versionati, ma vanno copiati sul server (vedi «Come si installa»). Il
throttle DRF parte da solo al prossimo deploy del codice.

## Il problema, in una riga

**La richiesta più economica che un estraneo può mandare è la più costosa che
sappiamo servire.**

- La macchina ha **1 vCPU** e 967 MB (`nproc` = 1, AMD EPYC 7713).
- Un login costa un PBKDF2 da **1.000.000 di iterazioni** (default di Django
  5.2.10) ≈ **0,5 secondi di CPU**, misurati. Lo paghiamo anche quando
  l'utente non esiste, ed è giusto così: senza, il tempo di risposta direbbe a
  un estraneo chi è iscritto (`resolve_login_identifier` in `api/views.py`).
- Nginx **non ha nessuna regola di rate limit**: zero occorrenze di `limit_req`
  e `limit_conn` in tutta `/etc/nginx/`.

Due richieste al secondo su `/api/v1/auth/login` saturano il 100% della CPU e
spengono il sito per tutti. Non serve un account, non serve indovinare niente,
non serve una botnet: basta un ciclo da un portatile. Lo stesso vale per
`/register`, che pure calcola un hash — e che in più risponde «Email already
registered», quindi è anche il modo più diretto per sapere chi è iscritto.

**Il bersaglio non è la password di qualcuno: è la disponibilità del sito.**
A 2 tentativi al secondo nessuno indovina una password che deve passare
lunghezza minima e lista delle password comuni. Ma a 2 tentativi al secondo il
sito è giù, e all'attaccante non costa niente.

## Cosa dicono i log (17/08/2026, ~8 giorni di access.log)

Misurato, non stimato.

### Attacchi: ci sono, costanti, e finora tutti a vuoto

| | |
|---|---|
| Tentativi SSH falliti in 7 giorni | **13.026** |
| Totale contato da fail2ban | **35.341**, con **874 IP bannati** |
| Richieste HTTP in ~8 giorni | **235.959** |
| ...di cui arrivate a Django in 7 giorni | **4.987** (nginx assorbe ~**98%**) |
| Risposte 401 sul login in 8 giorni | **21**, di cui ~10 sono PeppAndre e frascialpi87 |

**SSH è già a posto** e non va toccato: la configurazione *effettiva* (`sshd -T`,
che è l'autorità — il vecchio `sshd_config` dice ancora `PasswordAuthentication
yes` ma `sshd_config.d/99-hardening.conf` vince) è `passwordauthentication no`,
`permitrootlogin without-password`, `kbdinteractiveauthentication no`. Stanno
bussando a una porta che non ha serratura. Il firewall è `nftables` con
`policy drop` sull'input e solo 22/80/443 aperte.

**Il traffico HTTP è quasi tutto scansione di massa a caccia di WordPress**, su
un sito che WordPress non ce l'ha: `/wp-content/plugins/hellopress/wp_filemanager.php`
(824), `/this_is_a_new_hello_world.php` (800), `/.env` (711), poi decine di
`/1.php`, `/222.php`, `/admin.php`. Nessuno di questi raggiunge Django: l'unico
`proxy_pass` è su `^/(api|admin)/` e `/ws/`, il resto lo chiude nginx con un 404
statico.

**Nessuna forzatura contro il nostro login.** Mai, nel periodo coperto.

### Due allarmi che allarmi non sono

- I **4.161 errori 503** stanno tutti fra il 3 e l'11 agosto e si fermano di
  colpo l'11: è la **pagina di manutenzione**, non saturazione. Zero 502 e zero
  504 in tutto il periodo.
- Il **picco del 12/08 alle 22:36** (3.036 richieste in un minuto da
  185.177.72.56) erano **3.024 richieste malformate**, stato 400 e percorso
  vuoto: respinte a livello di protocollo, mai entrate nell'applicazione.

Carico medio al momento dell'analisi: **0.34**. Nessun OOM in 14 giorni.

**Morale: il sito regge perché nginx fa da scudo, e l'unica porta che porta a
lavoro costoso è spalancata. Che non l'abbiano ancora trovata è fortuna
statistica — gli scanner cercano PHP, e `/api/v1/auth/login` non è nel loro
elenco.**

## Quanto costa un'asta vera

Prima di scrivere qualsiasi limite bisogna sapere quanto traffico fa **la stanza
dei nostri**, perché è lei che rischia di inciampare per prima. E l'asta non
somma: **moltiplica**.

Il socket è un campanello, non una consegna: `consumers.py` manda un nudo
`{"type":"update"}` e ogni client rilegge lo stato via REST
(`useNudgeSocket.ts`, e la scelta è deliberata — così il percorso col socket e
quello con un F5 non possono divergere). Quindi **un rilancio non è una
richiesta: è una richiesta per ogni dispositivo collegato**, tutte nello stesso
istante e, se la lega fa l'asta nella stessa stanza, tutte dallo stesso IP
pubblico.

Misurato con `manage.py auction_load_test` contro un server vero, il core
singolo (`taskset -c 0`), DEBUG spento, listone da 660 giocatori:

| dispositivi | ritmo | ampl. | picco 1s | picco 100ms | stanza allineata | CPU (1 core) |
|---|---|---|---|---|---|---|
| 4  | rilancio ogni 1,5s | 4,0×  |  4 r/s |  40 r/s | 142 ms | 8%  |
| 10 | rilancio ogni 1,5s | 10,0× | 10 r/s | 100 r/s | 216 ms | 12% |
| **20** | rilancio ogni 1,5s | **20,0×** | 20 r/s | **200 r/s** | 326 ms | **19%** |
| 20 | rilancio ogni 0,4s | 20,0× | 60 r/s | 200 r/s | 328 ms | **55%** |
| 30 | rilancio ogni 0,4s | 30,0× | 83 r/s | 190 r/s | 415 ms | 68% |

In più, non nella tabella: **l'apertura della pagina è una raffica a sé**, una
lettura per dispositivo tutte insieme, prima che l'asta cominci.

Tre cose che questi numeri dicono, e che a occhio non si indovinavano:

1. **L'amplificazione è esattamente il numero di dispositivi.** Non «più o meno»:
   20,0 e 30,0 tondi. Ogni limite va dimensionato su `dispositivi × eventi`, mai
   su «una persona».
2. **Il picco che conta è quello a 100 ms, non quello al secondo.** Le richieste
   non sono distribuite: arrivano tutte insieme. 20 dispositivi fanno 20 r/s di
   media e **200 r/s istantanei**, cioè dieci volte tanto. È il `burst` di nginx
   che decide, non il `rate`.
3. **Funziona, e con margine sul tempo.** Zero errori in ogni scenario, e la
   stanza si allinea in ~330 ms anche a 20 dispositivi, di cui solo ~230 ms sono
   la lettura e il resto la consegna del campanello. L'architettura regge: il
   costo è la CPU, non la latenza.

### Il vero soffitto non è nginx, è la vCPU

Una lettura di stato costa **~17 ms di CPU** su questa macchina. Il PBKDF2, che
sul Linode è stato misurato a ~0,5 s, qui costa 0,195 s: il core del Linode è
quindi circa **2,6 volte più lento**. Trasportando:

| scenario | qui | sul Linode (×2,6) |
|---|---|---|
| 20 dispositivi, rilancio ogni 1,5s | 19% | **~49%** di una vCPU |
| 20 dispositivi, rilancio ogni 0,4s | 55% | **oltre il 100%** |
| 30 dispositivi, rilancio ogni 0,4s | 68% | **oltre il 100%** |

Il fattore 2,6 è una stima da un solo carico (il PBKDF2) e va preso come ordine
di grandezza, non come misura. Per averlo davvero basta puntare la prova di
carico a `https://vfoot.it` fuori orario e leggere la CPU lì.

**Un'asta tranquilla si mangia metà della macchina. Una guerra di rilanci la
satura**, e non c'entra niente il rate limit: è il costo dell'applicazione. Non è
un problema urgente — quando la CPU è al muro l'asta rallenta, non si rompe, e i
429 non arrivano perché il limite non è ancora stato messo — ma è il motivo per
cui il limite va scritto con la chiave giusta invece che con numeri più grandi.

La leva, se un giorno servirà, è **ridurre l'amplificazione, non alzare i
limiti**: far collassare lato client i rimbalzi ravvicinati (un nudge che arriva
mentre una rilettura è in volo non ne merita un'altra). A 0,4 s fra un rilancio e
l'altro, con la stanza che si allinea in 350 ms, i client rileggono in pratica di
continuo — e nessuno noterebbe la differenza.

## I livelli, dal più economico al più strutturale

### 1. `limit_req` in nginx — è questo che conta

Il filtro deve stare **prima di Python**, dove rifiutare costa microsecondi
invece di mezzo secondo. Ogni livello più in alto arriva troppo tardi.

La conf versionata (`deploy/nginx/vfoot.it.conf`) è **allineata al server**,
verificato: si modifica quella e si copia, non si edita in produzione.

**SCRITTO.** La configurazione vera sta in due file versionati, e i commenti che
spiegano ogni numero stanno lì dentro, non qui — così non possono divergere:

| file | va installato in | cosa contiene |
|---|---|---|
| `deploy/nginx/vfoot-limits.conf` | `/etc/nginx/conf.d/` | la `map` e le due zone (contesto `http`) |
| `deploy/nginx/vfoot.it.conf` | `/etc/nginx/sites-available/` | le due `location` che le usano |

Le zone stanno in un file a parte perché `limit_req_zone` e `map` vivono nel
contesto `http`: dentro un `server` nginx non parte.

**La chiave non è l'IP, ed è la decisione che conta.** Contare per IP è giusto
per chi non si è ancora autenticato e sbagliato per tutti gli altri: venti
dispositivi in salotto sono un IP solo, e a ritmo di rilanci fanno **60 richieste
al secondo sostenute** — il triplo di qualunque limite ragionevole. Col token
come chiave ognuno ha il suo secchiello e fa 5 r/s contro un limite di 20:
margine quattro volte.

I numeri, e perché:

- **`vfoot_api`: `rate=20r/s burst=100`, chiave per token.** Il burst è tarato
  sul picco **istantaneo** misurato (200 r/s su 100 ms con 20 dispositivi), non
  sulla media, che è dieci volte più bassa e porterebbe a un numero dieci volte
  troppo piccolo.
- **`vfoot_auth`: `rate=20r/m burst=20`, chiave per IP.** Il burst è più grande
  della lega di proposito: 10 manager più l'admin sono **11 persone** che la sera
  dell'asta entrano dallo stesso IP, qualcuna da due dispositivi. Un burst
  inferiore al numero dei partecipanti fa prendere un 429 sul login a chi arriva
  per ultimo. Le 20r/m sostenute sono ~17% della vCPU per chi insiste, contro il
  100% di oggi.

**Attenzione a tre cose, o si rompe quello che funziona:**

- **`/ws/` non va limitato.** Le connessioni dell'asta restano aperte a lungo
  (`proxy_read_timeout 3600s`). La `location /ws/` è separata e non combacia con
  nessuna delle due regex: lasciarla com'è.
- **Niente `limit_conn`.** Era nella prima stesura di questo piano ed è stato
  tolto: contro la minaccia misurata non serve — il costo è il *ritmo* delle
  richieste, non il numero di connessioni aperte — e con `http2 on` venti
  dispositivi sono venti connessioni, cioè esattamente il valore che si sarebbe
  scelto a naso. È il pezzo con più probabilità di fare danno e meno di servire.
- **L'ordine delle `location` è la regola, non lo stile.** Sono entrambe regex, e
  fra regex vince la prima che combacia: quella di auth deve stare **sopra**
  `^/(api|admin)/`, o non verrà mai usata.

Da solo, questo livello trasforma «2 al secondo mi uccidono il sito» in
«l'attaccante ottiene 20 hash al minuto».

**Il buco che questa chiave apre**, e va detto: nginx non sa distinguere un token
vero da uno inventato, quindi chi si scrive un `Authorization` a caso ottiene un
secchiello nuovo ogni volta e scavalca `vfoot_api`. Non tocca `vfoot_auth`, che
resta per IP, quindi il lavoro costoso è comunque protetto. Il tappo vero è il
livello 3, che il token lo valida davvero — vedi lì.

### 2. fail2ban esteso all'HTTP

La macchina c'è già e funziona (jail `sshd` attiva, tabella `f2b-table` in
nftables): mancano due jail che leggano il log di nginx.

- **Sui 429 degli endpoint di auth**, e SOLO su quelli: chi continua a bussare
  dopo il rate limit viene bannato al firewall e smette di costare anche a
  nginx. È il pezzo che chiude il cerchio — senza, un attaccante paga solo un
  429 e riprova per sempre.
- **Sulle raffiche di 404 dei probe PHP**: oggi 230.000 richieste di scanner si
  prendono banda e cicli di nginx gratis. Bannarli non è urgente per la CPU, ma
  toglie rumore dai log e rende leggibile quello che resta.

**La jail non deve MAI guardare i 429 generici dell'API.** Il modo di sbagliare è
asimmetrico: col solo limite di nginx una stanza che eccede prende un 429,
ritenta e si ripara da sola; con fail2ban viene bannata al firewall — e il ban
non colpisce solo l'API, **fa cadere anche il WebSocket**, che ci si era
preoccupati di non limitare. A quel punto `useNudgeSocket` ritenta con backoff
fermo a 15 secondi contro un pacchetto che il firewall scarta, e tutta la stanza
resta fuori dall'asta finché il ban non scade.

Per lo stesso motivo, l'ordine prudente è **prima il livello 1 da solo**, poi
guardare il tasso di 429 durante un'asta e una giornata di campionato vere, e
solo dopo accendere il 2 con una soglia tarata su dati veri. Accenderli insieme
significa scegliere quella soglia a occhio.

**SCRITTO**, versionato in `deploy/fail2ban/jail.d/vfoot.local` come si è fatto
per systemd e nginx, non scritto a mano sul server. Istruzioni e verifica in
`deploy/fail2ban/README.md`.

Il modo in cui la jail viene tenuta lontana dai nostri è concreto, non una
raccomandazione: usa il filtro `nginx-limit-req` di fail2ban legato al **nome
della zona** (`ngx_limit_req_zones="vfoot_auth"`). Legge l'error log di nginx,
dove ogni rifiuto porta scritta la zona che l'ha prodotto, quindi la jail non
*può* vedere i 429 della zona generale — nemmeno per un errore di configurazione
successivo.

`maxretry = 60` in 10 minuti, apposta alto: con `rate=20r/m` un IP può fare ~220
richieste di auth in dieci minuti **prima** di vedere un solo 429, quindi una
lega intera che entra non ci si avvicina; un attaccante ne colleziona 60 in
pochi secondi. La soglia separa i due casi di due ordini di grandezza.

### 3. Throttle DRF sugli stessi endpoint

Cintura oltre alle bretelle, nello stile che il progetto ha già: uno scope per
vista, opt-in, come `password_reset` (`config/settings.py`, con il commento che
spiega perché non c'è un `DEFAULT_THROTTLE_CLASSES` globale — metterebbe il
contatore anche al polling e all'asta, dove molte richieste al minuto sono la
forma normale).

Una correzione a quello che questo documento diceva prima («non salva la CPU»):
è troppo assoluto. Il throttle DRF gira in `initial()`, **prima** che la vista
esegua l'hash, quindi il PBKDF2 non parte: si paga l'overhead di Django, qualche
millisecondo, invece di mezzo secondo. Assorbe cioè il grosso del costo, non
niente. La cache è `FileBasedCache` (`settings.py`), condivisa fra i processi:
i contatori sono corretti anche senza Redis, che in produzione non c'è.

Nginx resta comunque meglio — microsecondi, nessun processo Python, regge volumi
molto più alti — ma questo livello ha tre motivi propri per esistere:

1. **Tappa il buco della chiave per token.** Nginx non può validare un
   `Authorization`; DRF sì. Un throttle per utente autenticato non si scavalca
   inventandosi header.
2. **Sopravvive a un rebuild del server**, perché si deploya con un `git pull`
   invece che con un file in `/etc`.
3. **Esprime limiti per-account**, che per-IP non si possono scrivere.

**SCRITTO.** Tre scope in `config/settings.py`, applicati per vista in
`vfoot/api/views.py`; test in `vfoot/tests_throttling.py`.

| scope | dove | limite | contato per |
|---|---|---|---|
| `auth_hash` | login, register, google | 40/min | IP |
| `password_reset` | password-reset, resend-verification | 5/hour | IP |
| `password_change` | cambio password | 10/hour | **utente** |

`auth_hash` è **deliberatamente più largo** del limite di nginx davanti (20r/m +
burst 20): così in condizioni normali è nginx a rifiutare e questo non tocca mai
nessuno di vero. Serve il giorno in cui la conf di nginx si perde in una
ricostruzione — allora 40/min limita il danno a un terzo della macchina invece
che a tutta.

`password_change` è l'unico che chiude un buco che nginx non vede: calcola due
hash ed è autenticato, quindi **non passa dalla location stretta** — cade in
quella generale, il cui limite è per token e tarato sul traffico d'asta, cioè
generosissimo per una cosa che costa mezzo secondo. Ed è contato per utente,
che nginx non sa proprio esprimere.

`resend-verification` ha preso lo scope di `password_reset`, che prima non
aveva: è la stessa identica forma di abuso (far partire una mail verso un
indirizzo che non è tuo) e mette a rischio la stessa cosa, la reputazione del
dominio presso Brevo.

**Un difetto trovato e corretto strada facendo:** senza `NUM_PROXIES` DRF usa
come chiave **l'intera stringa `X-Forwarded-For`**, e nginx a quella stringa
*appende* invece di sostituirla. Bastava mandarsi un `X-Forwarded-For` diverso a
ogni richiesta per avere un contatore nuovo ogni volta: il throttle di
`password_reset` era aggirabile da chiunque, da sempre. Con `NUM_PROXIES: 1` DRF
prende l'ultimo indirizzo, quello che nginx ha davvero osservato, e non è
falsificabile. C'è un test apposta.

**Non è stato fatto un throttle per-username sul login**, e non per dimenticanza:
bloccherebbe *l'account bersaglio*, non l'attaccante, e diventerebbe un modo per
chiudere fuori una persona a comando. Il piano dice che il bersaglio realistico è
la disponibilità del sito, non la password di qualcuno — e le password devono già
passare lunghezza minima e lista delle più comuni.

Resta dopo i primi due per ordine di urgenza, non per irrilevanza.

### 4. Il moltiplicatore: quella singola vCPU

- **Cloudflare davanti** (piano gratuito). Il ~98% di spazzatura non arriverebbe
  proprio al Linode, la shell della SPA verrebbe servita dalla loro cache, e ci
  sarebbe assorbimento DDoS vero — che è l'unica risposta seria a un attacco
  distribuito, contro cui `limit_req` per-IP non può niente. Costo: spostare il
  DNS, che oggi sta su Linode (vedi la nota su Brevo/DNS in memoria).
- **Seconda vCPU**: non risolve, raddoppia la soglia. Semmai *dopo* i punti
  1-3, non al posto loro.

### 5. Accorgersene

Oggi non c'è niente che avvisi se la CPU sta al muro: il canarino esistente
guarda la forma dei dati e i `JobRun`, non il carico. Un controllo su load
average e sul tasso di 429, agganciato a `vfoot-health`, che scriva dove già
guardi.

## Quello che NON si fa

**Abbassare le iterazioni del PBKDF2.** È letteralmente la leva che rende ogni
tentativo costoso, e viene la tentazione. Ma indebolirebbe **tutte** le password
memorizzate per rendere più sopportabile un attacco che si ferma meglio a monte.
Il default di Django è tarato per macchine con più margine: il margine si compra
con i livelli 1 e 4, non svalutando gli hash.

**Un `DEFAULT_THROTTLE_CLASSES` globale in DRF.** Metterebbe il contatore al
polling live e all'asta. La scelta di non averlo è già documentata in
`settings.py` ed è giusta.

## Come si installa

I file sono scritti e versionati; questi passi vanno fatti sul Linode. **Uno alla
volta, verificando fra uno e l'altro** — l'ordine è quello che permette di
tornare indietro senza aver rotto niente.

```bash
# 1. nginx — le zone e le location. Il -t non è una formalità: una virgola
#    sbagliata qui e il sito non risponde più.
scp deploy/nginx/vfoot-limits.conf root@139.162.144.123:/etc/nginx/conf.d/
scp deploy/nginx/vfoot.it.conf     root@139.162.144.123:/etc/nginx/sites-available/vfoot.it.conf
ssh root@139.162.144.123 'nginx -t && systemctl reload nginx'

# 2. la prova di carico dell'asta, DA SUBITO e attraverso nginx (vedi sotto).
#    Se dà 429, si torna indietro con un reload prima che se ne accorga qualcuno.

# 3. fail2ban, solo DOPO aver guardato i 429 di un'asta e di una giornata vere.
scp deploy/fail2ban/jail.d/vfoot.local root@139.162.144.123:/etc/fail2ban/jail.d/
ssh root@139.162.144.123 'fail2ban-client -t && systemctl reload fail2ban'
```

Il livello 3 non ha passi propri: è codice, parte col deploy normale.

**`nginx -t` non è stato eseguito** su questi file — in locale nginx non c'è.
È la prima cosa da fare sul server, prima del reload.

## Come si verifica che funzioni

1. `nginx -t` prima di ricaricare, sempre.
2. Da fuori, una raffica su `/api/v1/auth/login` deve dare **429** dopo il
   burst, non 401 all'infinito.
3. Durante la raffica, `uptime` sul server: il load **non** deve salire — è il
   punto di tutto l'esercizio.
4. **L'asta con una stanza intera dietro un IP solo.** È il test che può fallire
   davvero, ed è automatizzato:

   ```bash
   python manage.py seed_auction_demo --managers 10
   # in un'altra shell, il server pinnato a un core solo come il Linode:
   DJANGO_DEBUG=0 DJANGO_SSL_REDIRECT=0 taskset -c 0 \
       python manage.py runserver 127.0.0.1:8011 --noreload
   python manage.py auction_load_test --base http://127.0.0.1:8011 \
       --clients 20 --rounds 4 --bids-per-round 6 --server-pid <pid di python>
   ```

   Contro il server nudo dà i numeri della tabella sopra. Puntato a
   `https://vfoot.it`, cioè **attraverso** nginx, deve dare gli stessi: zero
   errori e nessun 429. Se compaiono 429, il `burst` è troppo stretto — ed è
   meglio scoprirlo così che di sabato sera.

   `--server-pid` vuole il pid di **python**, non della shell che l'ha lanciato:
   il comando somma comunque l'albero dei figli, ma se stampa una CPU quasi nulla
   è quello il motivo.
5. `fail2ban-client status <jail>` deve mostrare l'IP della raffica fra i
   bannati — e **non** quello della stanza durante il punto 4.
6. Dopo il ricarico, i 429 devono comparire nel log di nginx e **non** devono
   comparire 503: quelli restano riservati alla manutenzione, o si confondono le
   due cose in fase di diagnosi.

## Ordine

**Prima l'1 da solo**, con la prova di carico dell'asta subito dopo il ricarico
(punto 4 delle verifiche). Da solo toglie l'intera classe di problemi, e non può
chiudere fuori nessuno: il caso peggiore è un 429 che il client ritenta.

**Poi il 2**, tarato sui 429 che si sono visti davvero durante un'asta e una
giornata di campionato — non su una soglia scelta a occhio. È l'unico livello che
può bannare i nostri, e non si torna indietro da un ban col sito in uso.

Il 3 è rifinitura da fare col resto del codice, ma è anche il tappo del buco che
la chiave per token apre nel livello 1: se quella chiave si adotta, il 3 sale di
priorità. Il 4 è una decisione, non un lavoro. Il 5 quando i primi due sono in
piedi e c'è qualcosa da misurare.

## Contesto

**Aggiornato il 17/08/2026** dopo aver misurato l'asta invece di stimarla. La
prima stesura dimensionava i limiti su «una persona con qualche scheda aperta» e
sarebbe stata **troppo stretta per un'asta vera**: il `burst=40` proposto lo
consuma per intero l'apertura della pagina di venti dispositivi, e il
`limit_conn 20` cadeva esattamente sul numero di connessioni di una stanza. Da lì
la chiave per token, la sparizione di `limit_conn`, l'auth a 30r/m e la
separazione fra il livello 1 e il 2.

Emerso il 17/08/2026 indagando perché un iscritto non riusciva a entrare
(`git log`, «Chi non ricordava le maiuscole del proprio nome restava fuori»).
Aggiungendo l'accesso via email si è allargato chi può essere preso di mira —
l'indirizzo è un valore che un estraneo spesso possiede già, mentre un username
inventato dentro l'app lo si impara solo stando in lega — e la domanda «e se
qualcuno ci martella il login?» ha portato a misurare quanto costa davvero un
tentativo. La risposta è: mezzo secondo su una CPU sola.
