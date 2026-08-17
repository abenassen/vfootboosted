# Reggere il carico ostile — piano

Stato: **DA FARE**. Analisi dei log del 17/08/2026, niente ancora implementato.

| pezzo | dove | stato |
|---|---|---|
| `limit_req` / `limit_conn` in nginx | `deploy/nginx/vfoot.it.conf` | da fare |
| jail fail2ban sui 429 e sui probe PHP | `deploy/fail2ban/` (da creare) | da fare |
| throttle DRF sugli endpoint che calcolano hash | `config/settings.py`, `api/views.py` | da fare |
| avviso quando la CPU sta al muro | `deploy/systemd/vfoot-health.*` | da fare |
| Cloudflare davanti / seconda vCPU | decisione, non lavoro | da decidere |

Il codice dell'applicazione **non si tocca** per i primi due punti: sono
configurazione di sistema. È il motivo per cui vengono prima.

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

## I livelli, dal più economico al più strutturale

### 1. `limit_req` in nginx — è questo che conta

Il filtro deve stare **prima di Python**, dove rifiutare costa microsecondi
invece di mezzo secondo. Ogni livello più in alto arriva troppo tardi.

La conf versionata (`deploy/nginx/vfoot.it.conf`) è **allineata al server**,
verificato: si modifica quella e si copia, non si edita in produzione.

Nel blocco `http` (quindi `/etc/nginx/nginx.conf` o un file in `conf.d/`, non
dentro il `server`):

```nginx
# Le zone stanno nel contesto http; 10m tengono ~160.000 IP.
limit_req_zone  $binary_remote_addr zone=vfoot_api:10m   rate=20r/s;
limit_req_zone  $binary_remote_addr zone=vfoot_auth:10m  rate=10r/m;
limit_conn_zone $binary_remote_addr zone=vfoot_conn:10m;
limit_req_status 429;   # default 503: si confonderebbe con la manutenzione
limit_conn_status 429;
```

Nel `server` di vfoot.it, **prima** della `location ~ ^/(api|admin)/`
esistente — serve un match più specifico, e `^~` batte le regex:

```nginx
# Gli endpoint che calcolano un hash: mezzo secondo di CPU l'uno, su una vCPU
# sola. Sono l'unico punto del sito dove una richiesta anonima compra lavoro
# costoso, quindi qui il limite è stretto e il burst piccolo.
location ~ ^/api/v1/auth/(login|register|password-reset|google|resend-verification) {
    limit_req  zone=vfoot_auth burst=5 nodelay;
    limit_conn vfoot_conn 10;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
}
```

E il limite generale, largo, dentro la `location ~ ^/(api|admin)/` già
esistente:

```nginx
    limit_req  zone=vfoot_api burst=40 nodelay;
    limit_conn vfoot_conn 20;
```

**Attenzione a due cose, o si rompe quello che funziona:**

- **`/ws/` non va limitato.** Le connessioni dell'asta restano aperte a lungo
  (`proxy_read_timeout 3600s`) e il `limit_conn` le conterebbe tutte. La
  `location /ws/` è separata: lasciarla com'è.
- **Il polling live** gira ogni 60-90 secondi con aggiornamento automatico a
  pagina aperta. 20r/s con burst 40 è larghissimo per una persona, ma va
  ricontrollato durante una giornata di campionato vera, con più schede aperte
  in casa dietro **un solo IP pubblico** — è il caso che morde per primo, non
  l'attaccante.

Da solo, questo livello trasforma «2 al secondo mi uccidono il sito» in
«l'attaccante ottiene 10 hash al minuto».

### 2. fail2ban esteso all'HTTP

La macchina c'è già e funziona (jail `sshd` attiva, tabella `f2b-table` in
nftables): mancano due jail che leggano il log di nginx.

- **Sui 429** prodotti dal livello 1: chi continua a bussare dopo il rate limit
  viene bannato al firewall e smette di costare anche a nginx. È il pezzo che
  chiude il cerchio — senza, un attaccante paga solo un 429 e riprova per
  sempre.
- **Sulle raffiche di 404 dei probe PHP**: oggi 230.000 richieste di scanner si
  prendono banda e cicli di nginx gratis. Bannarli non è urgente per la CPU, ma
  toglie rumore dai log e rende leggibile quello che resta.

Le jail vanno versionate in `deploy/fail2ban/`, come si è fatto per systemd e
nginx, non scritte a mano sul server.

### 3. Throttle DRF sugli stessi endpoint

Cintura oltre alle bretelle, nello stile che il progetto ha già: uno scope per
vista, opt-in, come `password_reset` (`config/settings.py`, con il commento che
spiega perché non c'è un `DEFAULT_THROTTLE_CLASSES` globale — metterebbe il
contatore anche al polling e all'asta, dove molte richieste al minuto sono la
forma normale).

Va detto con onestà: **questo livello non salva la CPU**, perché la richiesta è
già arrivata fino a Python. Serve per due cose diverse — se la conf di nginx si
perde in un rebuild, e per limiti per-account che nginx non sa esprimere.
Priorità dopo i primi due.

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

## Come si verifica che funzioni

1. `nginx -t` prima di ricaricare, sempre.
2. Da fuori, una raffica su `/api/v1/auth/login` deve dare **429** dopo il
   burst, non 401 all'infinito.
3. Durante la raffica, `uptime` sul server: il load **non** deve salire — è il
   punto di tutto l'esercizio.
4. Il polling live e l'asta devono continuare a funzionare con più schede aperte
   dallo stesso IP. Questo è il test che può fallire davvero.
5. `fail2ban-client status <jail>` deve mostrare l'IP della raffica fra i
   bannati.
6. Dopo il ricarico, i 429 devono comparire nel log di nginx e **non** devono
   comparire 503: quelli restano riservati alla manutenzione, o si confondono le
   due cose in fase di diagnosi.

## Ordine

**1 e 2 insieme, in una sessione.** Sono configurazione di sistema, non toccano
il codice, e da soli tolgono l'intera classe di problemi. Il 3 è rifinitura da
fare col resto del codice. Il 4 è una decisione, non un lavoro. Il 5 quando i
primi due sono in piedi e c'è qualcosa da misurare.

## Contesto

Emerso il 17/08/2026 indagando perché un iscritto non riusciva a entrare
(`git log`, «Chi non ricordava le maiuscole del proprio nome restava fuori»).
Aggiungendo l'accesso via email si è allargato chi può essere preso di mira —
l'indirizzo è un valore che un estraneo spesso possiede già, mentre un username
inventato dentro l'app lo si impara solo stando in lega — e la domanda «e se
qualcuno ci martella il login?» ha portato a misurare quanto costa davvero un
tentativo. La risposta è: mezzo secondo su una CPU sola.
