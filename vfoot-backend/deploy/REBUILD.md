# Ricostruire il server da zero (deploy di riapertura)

Non è il deploy incrementale di `DEPLOY.md`. Il database di produzione viene
**buttato e rifatto**, e la stagione 25-26 viene ricostruita sul server dalla
cache delle risposte SofaScore che il server **ha già**.

Deciso l'11/08/2026, dopo aver guardato cosa c'è davvero sul server.

> **Non serve spedire niente.** La cache del server
> (`/srv/vfoot-data/historical-data/serie-a/sofascore/cache`) contiene già tutti i
> 13.108 file della 25-26 — 11.928 heatmap, 380 shotmap, 380 lineups, 380
> incidents — **con gli stessi identici byte** di quelli locali (verificato per
> nome e dimensione su tutti, e per md5 a campione). L'unico file diverso è
> `..._seasons.json`, dove è la copia del server a essere quella buona: 6.758 byte
> contro i 45 di un troncone rimasto qui.
>
> Le 16 chiavi feature mancanti in produzione non sono un buco di cache: sono
> l'estrattore vecchio che non le leggeva. Basta il codice nuovo sopra la stessa
> cache.

---

## Perché buttarlo invece di aggiornarlo

Il codice in produzione è `72860db`, 190 commit indietro. Il database però non è
"vecchio": è **della forma sbagliata**.

| Serie A 25-26 | Linode | locale |
|---|---|---|
| partite | 385 | 385 |
| presenze | 17.773 | 17.773 |
| righe zona giocatore | 1.263.313 | 2.130.000 |
| chiavi feature distinte | **31** | **47** |
| presenze con `raw_stats` | **0** | 17.773 |
| tiri (`MatchShot`) | **0** | 9.381 |

Le partite ci sono tutte, le zone pure — mancano 16 chiavi feature su 47, tutti i
`raw_stats` e tutti i tiri, perché quell'import fu fatto con l'estrattore di
allora. È il caso peggiore, non il migliore: la guardia di `classic_rating`
rifiuta di votare quando una partita non ha **nessuna** riga di zona, ma qui le
righe ci sono e mancano solo delle chiavi, che valgono zero. Ne uscirebbe un
listone completo, ordinato, plausibile e sbagliato, senza niente a schermo che lo
dica.

Si potrebbe correggere con un re-import sopra (l'upsert cancella anche le righe
che non arrivano più, quindi pulirebbe da sé). Ma dovendo comunque applicare 28
migrazioni su un database che contiene solo prove, ricostruire costa meno e
lascia uno stato che sappiamo descrivere.

**Cosa si perde**: 20 utenti, di cui 18 seminati (`classicdemo_mgr_*`,
`preseason_mgr_*`) più `andrea`; 2 leghe demo; 500 righe di rosa. L'unico account
vero oltre al tuo è **`f.sconfienza`**, registrato il 23/07: dovrà registrarsi di
nuovo.

---

## ⚠ Non sincronizzare la cache locale sul server

Sembra un'ottimizzazione innocua ed è il modo più rapido di rovinare tutto.

In locale la stagione 2026-27 ha **220 partite in stato `finished` con calcio
d'inizio nel futuro** (dal 22/08/2026 al 31/01/2027): è la stagione **simulata**
da `simulate_sofascore_season`, quella con cui si collauda il live. Il simulatore
scrive i suoi payload finti **dentro la stessa cache** delle risposte vere:

```
13.068 file  eventi 25-26 (veri)            -> il server li ha già, identici
    39 file  schedule season_76457 (25-26)  -> il server li ha già
 7.438 file  eventi 26-27 SIMULATI          -> esistono solo qui, e qui devono restare
    39 file  schedule season_95836 riscritto dal simulatore
```

`76457` è la stagione SofaScore 25-26 (primo evento 23/08/2025), `95836` la 26-27
(primo evento 22/08/2026). Un `rsync` della cartella intera porterebbe in
produzione una stagione inventata, e un import della 26/27 la ingerirebbe senza
un solo messaggio d'errore: le partite sono `finished`, i tabellini coerenti, i
marcatori plausibili.

Il calendario 26-27 vero si prende in rete al passo 5. Le voci di schedule che il
server ha in cache sono vecchie, ma non è un problema da gestire a mano: chi
scarica dati vivi cancella la voce prima di rileggerla (`egress/fetch_worker.py`,
`purge`), perché la cache **non scade mai** ed è una trappola esattamente per le
cose che cambiano.

---

## L'ordine, e perché è obbligato

L'estrattore ricco sta nei 190 commit che mancano: **prima il codice, poi i
dati**. Importare prima significherebbe rifare l'import di adesso.

### 1. Frontend, in locale (il server non ha node)

```sh
cd vfoot-frontend
VITE_API_PROVIDER=backend \
VITE_API_BASE_URL=/api/v1 \
VITE_GOOGLE_CLIENT_ID=989229675760-6jhl2l8hootj02j3urbm2c68soia67i8.apps.googleusercontent.com \
npm run build
grep -c "api/v1" dist/sw.js      # deve dire 0
```

### 2. Push

```sh
git push origin main
```

### 3. Server: fermare, buttare, ripartire da zero

```sh
ssh root@139.162.144.123
systemctl stop vfoot
sudo -u postgres dropdb vfoot
sudo -u postgres createdb vfoot -O vfoot
sudo -u vfoot git -C /srv/vfoot-app pull --ff-only origin main
cd /srv/vfoot-app/vfoot-backend/src
sudo -u vfoot ../.venv/bin/pip install -r ../requirements.txt
sudo -u vfoot ../.venv/bin/python manage.py migrate --noinput
sudo -u vfoot ../.venv/bin/python manage.py collectstatic --noinput
sudo -u vfoot ../.venv/bin/python manage.py createsuperuser
```

`git` come `vfoot`, mai come root: un pull da root lascia oggetti di root in
`.git/objects` e il pull successivo fallisce (vedi *Gotchas* in `DEPLOY.md`).

### 4. L'import 25-26, offline dalla cache che c'è già

```sh
cd /srv/vfoot-app/vfoot-backend/src
sudo -u vfoot ../.venv/bin/python manage.py import_sofascore \
    --year 25/26 --no-skip-existing
```

Non tocca la rete: `egress_client` serve dalla cache ogni percorso che la cache
ha, e ce li ha tutti. `--no-skip-existing` non serve su un database vuoto ma non
fa danno, e serve se si rilancia.

L'importer crea da sé `Competition`, `Season` e `CompetitionSeason`: importando
la 25-26 per prima gli id restano **1 = 25/26, 2 = 26/27**, gli stessi che
`DEPLOY.md` documenta.

Controllo, che è il punto di tutta l'operazione:

```sh
sudo -u postgres psql -d vfoot -Atc \
  "select count(distinct feature_key) from realdata_playerzonefeature"   # 47, non 31
sudo -u postgres psql -d vfoot -Atc \
  "select count(*) from realdata_matchshot"                              # ~9381, non 0
```

#### 4b. Le partite importate non sono «finite», e conta

L'importatore storico legge `status.type` solo per decidere cosa saltare
(`sofascore_adapter`, `only_finished`): non scrive **mai** `Match.status`, che
resta `scheduled`, né `data_ready`, che resta falso. Su un database ricostruito
da zero escono 380 partite di una stagione conclusa in stato `scheduled`.

Non è cosmetico. `player_ratings._compute_season_player_ratings` filtra
`status=FINISHED`: con tutte a `scheduled` trova zero partite, **ritorna `{}` e il
listone ripiega sullo snapshot** senza dire niente — la stessa forma di guasto di
`export_dev_db` (voti plausibili e sbagliati, nessun allarme).

```sh
sudo -u vfoot ../.venv/bin/python manage.py sync_calendar --year 25/26 --offline
```

Legge la cache degli schedule che il server ha già, stampa gli stati
(`scheduled -> finished`) e stampiglia l'`external_id` 76457 sulla
`CompetitionSeason` — che l'import offline lascia vuoto. Crea anche le 5 partite
rinviate che l'import salta, arrivando a 385 come in locale.

Restano `data_ready=false`, e **vanno messe a vero a mano**. Non è pignoleria:
`candidate_matches()` prende tutto ciò che non è `data_ready`, quindi appena
l'`external_id` c'è il tick si trova 380 partite finite da stampigliare e poi da
riscaricare una per una attraverso l'egress — una stagione intera, per niente.

```sh
sudo -u vfoot ../.venv/bin/python manage.py shell -c "
from realdata.models import Match
print(Match.objects.filter(competition_season_id=1, status=Match.STATUS_FINISHED,
                           data_ready=False).update(data_ready=True))
from realdata.services.match_scheduler import candidate_matches
print('candidate del tick:', candidate_matches().count())   # 0 finche' non c'e' la 26/27
"
```

La prova che tutto questo serviva a qualcosa (dev'essere ~554 giocatori e la
media intorno a 6, non un dizionario vuoto):

```sh
sudo -u vfoot ../.venv/bin/python manage.py shell -c "
from vfoot.services.player_ratings import _compute_season_player_ratings
import statistics
d = _compute_season_player_ratings(1)
a = [v['avg'] for v in d.values() if v.get('avg')]
print(len(a), round(statistics.mean(a), 3), round(statistics.pstdev(a), 3))"
```

### 5. La stagione 26-27 (questa sì, in rete)

**Prima il calendario, poi le rose** — l'ordine inverso, che questo documento
prescriveva fino all'11/08, importa le rose della stagione SBAGLIATA:

```sh
sudo -u vfoot ../.venv/bin/python manage.py sync_calendar --egress --year 26/27
sudo -u vfoot ../.venv/bin/python manage.py poll_transfermarkt   # rose + valori
```

`poll_transfermarkt` sceglie da sé la `CompetitionSeason` con **l'id più alto**
(`_resolve_season`) e da quella deriva l'annata Transfermarkt, apposta perché
scrape e import non possano divergere. Su un database appena ricostruito l'unica
stagione esistente è la 25-26, quindi lanciarlo prima del calendario scarica le
rose del 2025 e le scrive sulla stagione vecchia. Il calendario crea la 26-27
(id 2, `external_id` 95836) e con essa il bersaglio giusto.

`import_transfermarkt_squads` **non** è il comando da usare qui: vuole un
`--cache-dir` obbligatorio perché importa da uno scrape già fatto. Quello che
scrape e importa insieme è `poll_transfermarkt`, lo stesso del job `vfoot-tm-poll`.

Transfermarkt dall'IP del Linode passa senza anti-bot. SofaScore no: `sync_calendar`
esce dall'`egress`, quindi il tunnel WireGuard deve essere su prima di lanciarlo.

### 6. Ruoli e coda dell'admin

```sh
sudo -u vfoot ../.venv/bin/python manage.py compute_classic_roles \
    --season 2 --data-season 1 --dry-run
```

`--dry-run` per leggere le categorie e l'elenco «DA DECIDERE PRIMA DELL'ASTA»
prima che conti. La riga di ogni caso misurato dice quale delle due letture lo ha
pescato: `m` il margine, `b` il confine.

Quel numero è **filtrato a 5M** come la coda vera del prodotto
(`league_decisions.players_needing_decision`): sotto quella soglia l'ambiguo
prende la proposta del sistema e non disturba nessuno. L'11/08/2026 erano **17**
con il cancello e 53 senza — la differenza sono ragazzi appena tesserati, senza un
minuto in Serie A, che ogni finestra di mercato aggiunge a decine. Se questo
comando tornasse a stampare il numero non filtrato, ci si preparerebbe a un lavoro
che non esiste.

Poi lo stesso comando senza `--dry-run`, oppure si lascia fare al polling
Transfermarkt, che chiama `refresh_current_roles` da sé due volte al giorno.

### 7. Frontend, riavvio, verifica

```sh
rsync -az --delete vfoot-frontend/dist/ root@139.162.144.123:/srv/vfoot-web/
ssh root@139.162.144.123 'chown -R vfoot:vfoot /srv/vfoot-web; systemctl restart vfoot'
```

Le verifiche sono quelle del passo 6 di `DEPLOY.md`: `/` a 200, il bundle nuovo,
`/api/v1/auth/me` a **401 e non 500**, `journalctl -u vfoot` senza errori.

### 8. `.env` di produzione

Da controllare **prima** di togliere il 503, perché un vuoto qui non fa rumore:

- `VFOOT_HEALTH_EMAIL` — vuoto significa nessun allarme dal canarino. È il default
  giusto ovunque tranne qui.
- `DJANGO_EMAIL_BACKEND`, `EMAIL_HOST*`, `DEFAULT_FROM_EMAIL` — `DEPLOY.md` non le
  documenta, `.env.example` sì. Su una macchina rifatta si perdono senza avviso.
- `VFOOT_FRONTEND_BASE_URL=https://vfoot.it` — è il link dentro le email.
- chiavi VAPID (`manage.py vapid_keys`) se si vogliono le push.
- `REDIS_URL=redis://127.0.0.1:6379/1` — **e Redis non c'era.** `DEPLOY.md` dice
  «the Redis that already runs on the box»: non era vero, il pacchetto non era
  nemmeno installato. Senza, il channel layer è quello in memoria, e il tick — che
  è un processo separato dal web server — spinge i suoi aggiornamenti live dentro
  la propria memoria: la pagina non si aggiorna mai e non c'è un errore da nessuna
  parte (la trappola è scritta in `vfoot/services/live_realtime.py`). Installato
  l'11/08/2026 con persistenza spenta e `maxmemory 64mb`, perché qui Redis porta
  solo messaggi che durano un istante e su 967 MB di RAM il fork di un BGSAVE è il
  rischio più grosso che introdurrebbe.

---

---

# Post-deploy: accendere i dieci job, uno alla volta

L'inventario di cosa gira e cosa si rompe se non gira sta in
`systemd/README.md`. Qui c'è **l'ordine di accensione e come si prova che un job
funziona davvero**, che è un'altra domanda: `systemctl is-active` risponde "sì"
anche a un job che scatta, riesce, e non riporta più niente.

Regola: **ogni job si prova a mano prima di accendergli il timer.** Tutti hanno
un `--dry-run` tranne `health_report`, che ha `--always`. Niente `--enable-all`
al buio.

## Da cosa si parte (fotografia dell'11/08/2026)

| | stato |
|---|---|
| unità installate | 4 su 10: `tick`, `calendar`, `tm-poll`, `egress-refill` |
| mancanti | `market`, `nudge`, `backup`, `health`, `agent`, `maintenance` — arrivano col codice nuovo |
| `tick.timer`, `calendar.timer` | **`enabled` ma mai partiti** (nessun NEXT) |
| `tm-poll.timer`, `egress-refill.timer` | `disabled` |
| bridge sudo egress | c'è dal 23/07, sudoers valido |
| **pool di IP SofaScore** | **del 23/07**, `last_ok` lo stesso giorno |
| `/var/cache/sofascore` | vuoto |

Due cose da leggere bene. **`enabled` non vuol dire acceso**: un timer abilitato
ma mai avviato parte al reboot e nel frattempo non scatta mai — è lo stato in cui
si trovano tick e calendar da luglio. `install.sh` usa `enable --now`, che
risolve, ma se un giorno li accendi a mano ricordati il `--now`.

E il **pool di IP ha diciannove giorni**. È la dipendenza più fragile di tutte:
gli exit IP Surfshark vengono bruciati e ruotati, e nessuno li ha più provati da
quando furono trovati. Si riparte da lì.

## L'ordine, e perché

### 0. `vfoot-backup`, prima di tutto il resto

Non dipende da niente ed è l'unica copia fra un deploy e l'altro. Va acceso
**prima** del lancio, non insieme.

```sh
./install.sh --enable backup
/usr/local/sbin/vfoot-backup && ls -lh /root/backups | tail -3
```

Resta mezzo backup — scrive sullo stesso disco (vedi `systemd/README.md`).

### 1. L'egress, che è il collo di bottiglia di tre job

```sh
cd /srv/vfoot-app/vfoot-backend
python3 egress/sofascore_egress.py status          # cosa resta del pool di luglio
python3 egress/sofascore_egress.py refill          # ne cerca di nuovi, tiene i promossi
python3 egress/sofascore_egress.py status          # quanti ne sono passati
```

Poi la prova che conta, che non è "il tunnel sale" ma "SofaScore ci risponde":

```sh
python3 egress/sofascore_egress.py fetch --kind final --match-ids <un_id_partita>
ls /var/cache/sofascore | head        # devono comparire dei file
```

L'id partita va su `--match-ids`, non posizionale. E i file di prova conviene
cancellarli dopo: `/var/cache/sofascore` è quello che legge il canarino sulla
forma del dato, e una partita non giocata ci lascia `lineups` e `shotmap` da 4
byte.

Se il refill non promuove nessun IP, **tutto il resto della catena SofaScore è
fermo** e non ha senso accendere calendar e tick: fallirebbero a ogni scatto
riempiendo il journal. È il momento di guardare `egress/README` e i cluster
Surfshark, non di andare avanti.

```sh
./install.sh --enable egress-refill
```

### 2. `vfoot-tm-poll` — Transfermarkt, che non passa dall'egress

```sh
sudo -u vfoot ../.venv/bin/python manage.py poll_transfermarkt --dry-run
```

Scrape vero, import in sola lettura. Dall'IP del Linode passa senza anti-bot. Se
il report dice numeri sensati (rose piene, valori di mercato, mappature alte),
si accende:

```sh
./install.sh --enable tm-poll
```

È anche il job che tiene aggiornati i ruoli: chiama `refresh_current_roles` da
sé, due volte al giorno.

### 3. `vfoot-calendar` — primo consumatore dell'egress

```sh
sudo -u vfoot ../.venv/bin/python manage.py sync_calendar --egress --year 26/27
```

A mano e per intero la prima volta (senza `--if-due`), per vedere se il
calendario 26-27 entra davvero. Poi il timer, che scatta ogni ora ma decide da
sé con `--if-due`:

```sh
./install.sh --enable calendar
```

### 4. `vfoot-tick` — si accende ora, si giudica il 22 agosto

```sh
sudo -u vfoot ../.venv/bin/python manage.py tick --dry-run
```

A stagione non cominciata dirà **"nothing due"**, e va benissimo: prova il
cablaggio — legge il calendario dal DB, attraversa il bridge sudo, scrive la sua
riga di `JobRun` — ma **non prova la macchina a stati**, che è la parte che
conta.

Il campionato comincia il **22/08/2026**. La catena vera
(`live-poll` → `stamp-ft` → `final-check` → `final-confirm` → `data_ready`) si
può guardare solo su una giornata vera, e la prima è quella. Mettersi lì a
guardarla è parte del piano, non un extra:

```sh
journalctl -u vfoot-tick -f
```

```sh
./install.sh --enable tick
```

### 5. `vfoot-market` e `vfoot-nudge` — solo database, nessuna rete

```sh
sudo -u vfoot ../.venv/bin/python manage.py market_tick --dry-run
sudo -u vfoot ../.venv/bin/python manage.py nudge_conclusions --dry-run
./install.sh --enable market --enable nudge
```

Il market tick non tiene corretto il mercato (quello lo fa il server a ogni
richiesta): manda gli avvisi. Se non gira, il mercato funziona ed è **muto**.

### 6. `vfoot-health` — insieme agli altri, non dopo

Prima la riga nel `.env`, altrimenti il controllo gira e non ha a chi dirlo:

```sh
VFOOT_HEALTH_EMAIL=abenassen@gmail.com
```

Poi a mano, forzando l'invio anche quando è tutto a posto, così si prova pure
lo SMTP:

```sh
sudo -u vfoot ../.venv/bin/python manage.py health_report --mail --always
```

Il canarino sulla forma del dato leggerà `/var/cache/sofascore`, che prima della
prima giornata è vuoto: dirà *«normale prima della prima giornata»* e non è un
allarme — gli servono almeno due partite in cache.

```sh
./install.sh --enable health
```

Accenderlo dopo gli altri significa non avere il registro proprio nelle settimane
in cui si rompe di più.

### 7. `vfoot-agent` e `vfoot-maintenance` — **non adesso**

Sono gli unici due che **non** si accendono con gli altri, e non per prudenza
generica: non si può giudicare se le diagnosi di un agente valgono guardandolo
agire. Prima serve una settimana di solo livello deterministico, così il registro
`JobRun` accumula una baseline di com'è fatto il normale — che è sia il contesto
che passiamo all'agente, sia quello che serve a te per riconoscere un'anomalia.

Se di questo paragrafo non si facesse niente, il sistema resterebbe **sorvegliato
lo stesso**: `vfoot-health` non dipende dall'agente. Quello che manca senza di lui
è la diagnosi automatica, non l'allarme.

Quando è il momento (una settimana dopo, non prima):

```sh
# il ponte sudo lo installa install.sh da solo, validando la regola sudoers
# con visudo PRIMA di copiarla (un file rotto in /etc/sudoers.d toglie sudo a tutti)
sudo -u vfoot sudo -n /usr/local/sbin/vfoot-maintenance check     # deve rispondere

# nel .env: l'adattatore e la chiave. VFOOT_MAINTENANCE_AUTO resta ASSENTE.
VFOOT_AGENT_CMD=/srv/vfoot-app/vfoot-backend/deploy/agent/vfoot-agent-claude

# la catena si prova col FINTO, che non chiama nessun modello e non costa niente
VFOOT_AGENT_CMD=…/vfoot-agent-fake sudo -u vfoot ../.venv/bin/python \
    manage.py maintenance_run --force
sudo -u vfoot ../.venv/bin/python manage.py maintenance_review
sudo -u vfoot ../.venv/bin/python manage.py maintenance_tick --dry-run

./install.sh --enable agent --enable maintenance
```

**Tetto di spesa basso dalla console del fornitore, prima che giri la prima
volta.** La stima a tavolino non regge: una passata agentica è molti turni e a
ogni turno la storia viene rimandata, quindi si arriva a qualche euro *a
esecuzione*, non al mese. Dopo una decina di risvegli veri si guarda il numero e
si sceglie il modello: `claude-opus-5` è il default, la leva economica è
`kimi-k2.6` — **non `kimi-k3`, che costa quanto Sonnet 5**.

Due o tre settimane in sola lettura (`VFOOT_MAINTENANCE_AUTO` spento: ogni
proposta aspetta un tuo sì). Quello che si sta misurando in quelle settimane è
**quante proposte rifiuti e perché**: un agente che sbaglia due proposte su tre
non merita le mani, per quanto belle siano le sue spiegazioni. Solo dopo si accende
l'automatico, e solo per i riavvii e la pulizia della cache — `apply_patch` non ci
entra a nessuna impostazione, mai, e c'è un test che lo verifica.

Resta una decisione aperta, in `docs/maintenance_agent_plan.md`: se una patch
approvata dal telefono arrivi in produzione da sola (col ripristino automatico) o
si fermi al branch. Deciso «arriva», ma è da ridiscutere se il rodaggio va male.

### 8. Chi vede la pagina di manutenzione

L'identificazione è il flag `is_staff` di Django — lo stesso che apre `/admin/`.
Non è «tu», è chiunque ce l'abbia:

```sh
sudo -u vfoot ../.venv/bin/python manage.py shell -c \
  "from django.contrib.auth.models import User; \
   print(list(User.objects.filter(is_staff=True).values_list('username', flat=True)))"
```

**`manutenzione-test` non deve comparire in quell'elenco.** È un utente staff
creato in sviluppo l'11/08/2026 per provare la pagina, con una password scritta in
chiaro in una conversazione; va cancellato anche in sviluppo quando non serve più.

Provare una push vera di manutenzione una volta: le chiavi VAPID sono le stesse
delle altre notifiche, ma il destinatario qui è «tutti gli staff attivi», che è un
insieme diverso da quello di ogni altra push del prodotto.

## La prova generale del tick su una partita vera, prima del 22

Collaudare il live per la prima volta sulla giornata d'apertura è un rischio che
non serve correre: **il tick non ha niente di specifico sulla Serie A**, quindi si
può far girare adesso su una partita di un altro campionato che si sta giocando
davvero.

Tre punti del codice lo rendono possibile senza toccare una riga:

* `match_scheduler.candidate_matches()` non filtra per competizione — prende
  qualunque `Match` con stato `scheduled/live/finished`, `data_ready=False` e un
  `competition_season.external_id` non vuoto;
* `live_ingest` scarica e importa **per id di evento**
  (`warm_matches([external_id])`, poi `ingest_sofascore_matches(match_ids=[...])`),
  e `_event_by_id` risolve la partita dal suo indirizzo `/event/{id}`: il torneo
  non entra mai nel percorso normale;
* `ingest_sofascore_matches` accetta un `season_code` esplicito, e quello decide
  in quale `CompetitionSeason` la partita atterra.

L'unico punto cablato è `_get_or_create_competition_season`, che appende sempre a
`Competition(external_id="23")`. Non è un problema: dandogli un codice stagione
inventato nasce una `CompetitionSeason` a parte, "Serie A PROVA-LIVE", isolata da
tutto e cancellabile in un colpo. Il codice fa andata e ritorno
(`year_for` ↔ `season_code_from_year` lasciano passare intatto ciò che non ha la
forma `YYYY-YYYY`), quindi anche i tick successivi la ritrovano dov'era.

### Come si fa

Si sceglie su sofascore.com una partita che comincia fra poco — meglio di un
campionato di prima fascia, che ha la stessa ricchezza di dati della Serie A
(heatmap per giocatore, shotmap, incidents) — e si prende l'id dall'URL.

```sh
cd /srv/vfoot-app/vfoot-backend/src
EV=<id evento>

# 1. la scalda attraverso l'egress: prova bridge sudo + WireGuard + pool
sudo -u vfoot ../.venv/bin/python manage.py shell -c "
from realdata.services import egress_client
print('warm:', egress_client.warm_matches([$EV], 'live'))"

# 2. la importa in una stagione sandbox
sudo -u vfoot ../.venv/bin/python manage.py shell -c "
from django.conf import settings
from realdata.services.sofascore_client import SofaScoreClient
from realdata.services.sofascore_adapter import ingest_sofascore_matches
print(ingest_sofascore_matches(
    scraper=SofaScoreClient(cache_dir=settings.VFOOT_SOFASCORE_CACHE, max_retries=1),
    year='PROVA-LIVE', season_code='PROVA-LIVE', match_ids=[$EV],
    only_finished=False, skip_existing=False, with_heatmaps=False))"

# 3. da qui in poi la partita è una candidata come le altre: guarda il tick
sudo -u vfoot ../.venv/bin/python manage.py tick --dry-run
journalctl -u vfoot-tick -f
```

### Cosa prova, e cosa no

Prova le tre cose che il 22 agosto non si vogliono scoprire: che **l'egress
attraversa davvero** (è il pezzo più fragile e il pool ha diciannove giorni), che
**l'estrattore nuovo legge bytes freschi** (le 47 chiavi su dati di oggi, non su
una cache di un anno fa), e che **la macchina a stati gira** — finestra live,
cadenza per partita, `stamp-ft`, `final-check` a +15 minuti, `final-confirm` a
+1 ora, `data_ready`.

Non prova il nostro `sync_calendar` sulla Serie A, né il punteggio di una lega
sopra quei voti, né le soglie del canarino sulla forma, che sono misurate su 600
partite di Serie A e su un altro campionato possono leggere diverso.

### Due accortezze

**L'ora si può accelerare.** `tick --now <istante>` sposta solo l'orologio del
piano, quindi invece di aspettare l'ora piena fra `stamp-ft` e `final-confirm` si
può passare avanti a mano e vedere subito i due passi di finalizzazione.

**Poi si cancella, e prima che riparta il tick vero.** Le stampigliature scritte
con un `--now` nel futuro restano nel database, e `clock_drift()` guarda il
massimo globale: finché la stagione di prova è lì, il tick vero segnalerebbe un
orologio andato indietro. Cancellare la `CompetitionSeason` "Serie A PROVA-LIVE"
si porta via tutto.

## Cosa NON è provabile prima del 22 agosto

Vale la pena scriverlo perché la tentazione è dichiarare fatto ciò che è solo
acceso:

| provabile subito | solo su una giornata di Serie A |
|---|---|
| backup, tm-poll, market, nudge, health | la finestra densa del calendario (`--if-due`) |
| l'egress (refill + un fetch) | il punteggio di una lega sopra i voti live |
| `sync_calendar` per intero | le soglie del canarino sulla forma |
| che ogni job scriva la sua riga di `JobRun` | |
| **la macchina a stati del `tick`**, sulla prova generale qui sopra | |

Il registro `JobRun` è la cosa da guardare il giorno dopo il lancio: dice per ogni
job **quando sarebbe dovuto scattare e quando è scattato davvero**, che è l'unico
modo di accorgersi di un timer che non parte più.

```sh
sudo -u vfoot ../.venv/bin/python manage.py health_report --json | head -40
./install.sh --status        # cosa è acceso e quando scatta la prossima volta
```

## La scadenza vera non è tecnica

**La Serie A 2026-27 comincia il 22/08/2026**, e un'asta si fa prima della prima
giornata, non dopo. Contando all'indietro da lì: serve il sito aperto, i membri
avvisati, la lega creata e la sua coda dei ruoli smaltita **con qualche giorno di
margine per l'asta**. È questo a dettare quando togliere il 503, non la lunghezza
di questo documento.

Attenzione a **di chi** è quel lavoro: la coda dei ruoli non è del gestore del
sito ed è **per lega**. `players_needing_decision` parte dalla rosa della lega e
sottrae ciò che è già risolto *in quella lega* (`LeagueDecision` e
`LeaguePlayerRole` sono entrambi filtrati per `league`), quindi non esiste una
coda globale da smaltire prima di riaprire: ogni admin di lega risponde alla
propria, quando crea la lega, e la risposta di uno non vale per gli altri. Il
numero misurato l'11/08/2026 — **17 giocatori** — è la previsione di quanti ne
troverà *una* lega creata oggi sulle rose 26-27, non un totale da dividere.

Il che sposta anche la scadenza: quelle decisioni non bloccano il 503, bloccano
l'asta di ciascuna lega.

Ed è anche il primo deploy che porta l'asta online in produzione: girerà per la
prima volta davanti a delle persone.

## Dopo

- Il polling automatico è pronto e **spento**: si accende al lancio, non prima
  (`DEPLOY.md`, sezione *Automated polling*).
- La PWA si collauda solo da `https://vfoot.it`, e prima va disinstallata l'app di
  prova installata da `http://10.x.x.x:5173`: è un'altra origine, quindi un'altra
  app con un'altra iscrizione push.
- La fascia «È disponibile una nuova versione» si vede al **secondo** deploy, non
  al primo: compare solo quando un worker nuovo ne trova uno vecchio.
- **L'agente di manutenzione si accende una settimana dopo, non al lancio** (§7 e
  §8 qui sopra). È l'unica parte del sistema deliberatamente in ritardo sul resto:
  gli serve una settimana di registro per sapere com'è fatto il normale, e a te per
  giudicare le sue diagnosi prima di dargli le mani.
