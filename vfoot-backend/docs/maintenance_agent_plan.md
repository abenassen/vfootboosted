# Agente di manutenzione quotidiana — piano

Stato: **backend IMPLEMENTATO** (11/08/2026); manca la pagina sul telefono.

| pezzo | dove | stato |
|---|---|---|
| `MaintenanceRun` / `MaintenanceProposal` | `realdata/models.py`, migr. 0023 | fatto |
| insieme chiuso + doppia validazione | `realdata/services/maintenance.py` | fatto |
| ponte sudo (riavvio, fumo, uomo morto) | `deploy/agent/vfoot-maintenance` + `.sudoers` | fatto |
| seam JSON verso l'agente | `realdata/services/agent_client.py` | fatto |
| comandi `maintenance_run` / `_tick` / `_review` | `realdata/management/commands/` | fatto |
| adattatori Claude / Kimi / **finto** | `deploy/agent/` | fatto |
| unità `vfoot-agent` + `vfoot-maintenance` | `deploy/systemd/` | fatto, spente |
| 32 test, zero chiamate a modelli | `realdata/tests_maintenance.py` | fatto |
| pagina Manutenzione + push | `pages/MaintenancePage.tsx`, `realdata/api/`, rotta `/manutenzione` | fatto |

**Tutto pronto, tutto spento.** Le due unità sono installabili ma non accese, il
livello automatico è `false`, e `VFOOT_AGENT_CMD` vuota significa nessun agente.

**Quando e come si accende: `deploy/REBUILD.md`, §7 e §8 del post-deploy** — una
settimana dopo il lancio, non insieme al resto. Non è ripetuto qui: l'ordine di
accensione dei job vive in un posto solo, e la seconda copia è quella che invecchia.

La pagina è riservata a chi gestisce il **sito** (`is_staff`) — la prima area del
genere nel progetto: ogni altra amministrazione qui riguarda i membri di una lega. Il
flag `is_staff` sull'utente decide solo se il menu *offre* la voce; il cancello sono
le API, che rispondono 403.

Le stesse decisioni restano disponibili da terminale (`manage.py maintenance_review`),
ed è voluto: **la pagina la serve la stessa applicazione che l'agente sta cercando di
riparare.** Quando il guasto è l'app, restano la mail e il terminale.

Schema concordato il 10-11/08/2026, in coda al lavoro di sorveglianza già in `main`
(registro `JobRun`, `health_report`, canarino sulla forma del dato — vedi
`deploy/systemd/README.md`).

## Il problema

L'app vive di scraping. Un cambiamento a monte che invalidi lo scraping può arrivare
in un momento in cui non c'è nessuno a guardare — e il guasto peggiore non somiglia a
un guasto: il comando esce 0, il journal dice «applied», e in banca dati entra una
stagione di dati vuoti.

Il livello deterministico (già fatto) **rileva**. Questo documento riguarda il livello
sopra: **capire perché**, e fare i piccoli interventi ovvi da solo.

## Divisione dei ruoli, che è la decisione centrale

**Il modello non rileva niente.** Rilevare è aritmetica su righe: un timer che non è
scattato, un contatore che si è dimezzato, una colonna sparita. Un modello a cui si
chiede «va tutto bene?» risponde di sì, con calore, anche il giorno che non va — e lo
dice ogni volta con parole diverse, così chi legge non impara mai la forma del
normale.

Il turno del modello viene dopo: perché si è rotto, e qual è la correzione.

Da qui discende anche **quando gira**: lo sveglia il verdetto rosso di
`health_report`, non un orologio. Più una passata settimanale a prescindere, per le
derive lente che nessuna soglia prende. Un agente che ogni notte legge dati sani è un
agente che prima o poi rassicura su qualcosa che non va.

## L'agente propone, il codice esegue

L'agente **non agisce mai direttamente**. Emette una proposta il cui `kind` viene da un
insieme chiuso:

| kind | payload validato contro | livello |
|---|---|---|
| `restart_unit` | `ALL_UNITS` di `deploy/systemd/install.sh` | auto (con tetto giornaliero) |
| `rerun_command` | lista fissa di comandi | auto (con tetto giornaliero) |
| `clear_cache_file` | percorso vincolato sotto la cache dell'egress | auto |
| `apply_patch` | un branch git + le prove | **mai** auto |
| `none` | — | — |

Un esecutore separato — Python, nessun modello coinvolto — rilegge la proposta,
**rivalida il payload contro le liste** e agisce. L'approvazione arriva ore dopo,
quando il processo dell'agente è morto da un pezzo: quindi l'esecutore è un ticker
(la forma di `market_tick`), non l'agente stesso.

Questo è ciò che rende accettabile il rischio di prompt injection. L'input contiene
messaggi d'errore che vengono da siti esterni; un agente completamente dirottato può
al massimo proporre una cosa dell'insieme chiuso, che un umano deve autorizzare. La
lista permessa non sta in un prompt che raccomanda di comportarsi bene: sta in un `if`
che nessuna frase può convincere.

## I tre canali, per quanto sei disponibile

| quando | canale | cosa ci passa |
|---|---|---|
| non ci sei | **mail** (Brevo, già configurata) | il racconto: cos'è successo, cosa ha fatto da solo, cosa aspetta te |
| sei al telefono | **push + pagina Manutenzione nella PWA** | le proposte che richiedono un sì, con due bottoni |
| sei al computer | `ssh` + `claude` nel checkout | la conversazione vera |

La push c'è già (`push_channel.send_to_user(user, title, body, url)` sa aprire una
pagina dell'app) e l'autenticazione è la sessione che hai già sul telefono. Manca solo
la pagina: è l'unica area riservata al gestore del sito che oggi non esiste
(`LeagueAdminPage` è per lega, non per il sito).

La mail resta comunque, e non per abitudine: **è l'unico canale che sopravvive alla
cosa di cui parla.** Se il guasto è l'app, la pagina con i bottoni è irraggiungibile
proprio quando serve. Brevo è fuori dal server.

## I tre cancelli di una patch

1. **Prima di toccare niente: l'esecutore rigira i test.** L'agente dice «la suite
   passa»; quella frase l'ha scritta un modello, quindi non è una prova. Se non
   passano, non applica niente e ti scrive che la proposta era falsa.
2. **Tu.** Il click. Qui si giudica se la correzione ha senso: vedi il diff, l'esito
   dei test, il canarino prima e dopo.
3. **Dopo, in produzione: il controllo di fumo**, ed è l'unico che fa tornare indietro.

Il terzo non compensa uno scrutinio insufficiente sull'agente — quello è il cancello
2. Copre una cosa che nessuno scrutinio copre, nemmeno il tuo: che la produzione non è
l'ambiente in cui hai provato. È la stessa rete che vorresti per una tua patch
corretta, applicata alle due di notte.

### Il controllo di fumo, e il verso in cui cade

```
T+0      approvi dal telefono
T+2s     l'esecutore marca il commit attuale (tag) e arma il timer per T+5min
T+5s     rigira i test  ── falliscono? si ferma qui, niente è cambiato
T+30s    applica il branch, riavvia vfoot.service
T+45s    i controlli di fumo:
           - vfoot.service è active e non in auto-restart loop
           - curl 127.0.0.1:8000/admin/login/ -> 200   (porta DIRETTA: nginx
             risponde 503 per la manutenzione e maschererebbe tutto)
           - health_report --skip-shape gira senza eccezioni (tocca l'ORM,
             quindi prova insieme Django, migrazioni e database)
           - un tick è passato senza sollevare
         tutti passati? scrive il segnale
T+5min   il timer guarda: c'è il segnale?  sì → non fa niente
                                           no → torna al tag, riavvia, ti avvisa
```

Il timer **non valuta niente**: controlla se c'è il biglietto. Va scritto in questo
verso —

> fra cinque minuti torna al tag, **a meno che** non ci sia il segnale di tutto bene

— e non in quest'altro, che sembra identico:

> fra cinque minuti, **se** i controlli sono falliti, torna indietro.

La differenza si vede solo nel caso brutto: se a schiantarsi è il controllore stesso,
il primo ripristina e il secondo lascia il codice rotto in produzione tutta la notte.
È la forma dell'interruttore dell'uomo morto.

### Cosa il ripristino NON copre

**La patch sbagliata ma innocua resta su**, ed è il caso più probabile. Se `duelWon`
è diventato `duelsWon` e la correzione ha sbagliato nome, il server sta benissimo:
riparte, risponde, i controlli passano tutti. Quel caso lo prende il controllo del
mattino dopo, che rialza **lo stesso allarme**. Il ripristino risponde a «è vivo?»,
non a «la correzione era giusta?»: la seconda domanda non ha risposta in cinque
minuti, ce l'ha al prossimo dato vero che arriva.

### Solo codice, mai schema

Tornare al tag ripristina il **codice**, non il resto. Se la patch conteneva una
migrazione, quella ha già toccato lo schema, e rimettere il codice di prima lascia una
banca dati che il codice vecchio non si aspetta — un guasto peggiore di quello da cui
stavi scappando.

Quindi: **una proposta il cui diff tocca `migrations/` o i dati non entra nel livello
«approvi dal telefono»**. Ti aspetta al computer. L'esecutore lo verifica sui file
toccati dal diff, non con una raccomandazione nel prompt. Restringe poco: il guasto
per cui l'agente esiste è quasi sempre una riga di codice e zero schema.

## Come si chiama l'agente

La flessibilità non sta nello scegliere bene il modello: sta nel decidere **cosa
attraversa il confine**. Stessa figura di `egress_client.run_egress()` — un seam solo,
verso qualcosa di lento, esterno e inaffidabile, con un interruttore che lo finge.

**Ingresso** (stdin): il contesto già digerito. L'agente non va a caccia sul server,
riceve.

```json
{
  "verdict": "alarm",
  "checks":  [ "… da health_report --json …" ],
  "journal": [ {"date": "…", "proposed": "…", "decided": "rejected", "outcome": "…"} ],
  "allowed_kinds": ["restart_unit","rerun_command","clear_cache_file","apply_patch","none"],
  "allowed_units": ["vfoot-egress-refill", "vfoot-tick"],
  "max_actions": 2
}
```

**Uscita** (stdout): la proposta, e nient'altro.

```json
{
  "summary": "SofaScore ha rinominato duelWon in duelsWon",
  "diagnosis": "…",
  "proposals": [
    {"kind": "apply_patch", "branch": "fix/duelswon",
     "rationale": "…", "evidence": {"tests": "…", "canary": "…"}}
  ]
}
```

**L'adattatore** è uno script a percorso fisso scelto da `VFOOT_AGENT_CMD` nel `.env`,
non una stringa di flag: i flag di ogni CLI sono diversi, e infilarli in una variabile
d'ambiente è come costruire un cambio d'olio che funziona solo con una marca.

```sh
#!/bin/sh
# deploy/agent/vfoot-agent-claude
# stdin: il contesto JSON.  stdout: SOLO la proposta JSON.  Uscita != 0 = passata fallita.
cd /srv/vfoot-app || exit 1
exec claude -p "$(cat)" \
     --append-system-prompt "$(cat deploy/agent/prompt.md)" \
     --allowedTools 'Read,Grep,Glob,Bash(git *),Bash(*manage.py test*)' \
     --output-format json
```

### Quale modello (deciso 11/08/2026)

**Claude Opus 5** (`claude-opus-5`), effort `xhigh`. Il lavoro dell'agente — leggere,
cercare, far girare i test, scrivere una patch — è il profilo agentico/coding, dove
Opus 5 è il default e `xhigh` la raccomandazione.

**Il costo va misurato, non stimato** (una prima stima da «qualche euro al mese» era
sbagliata di un ordine di grandezza). L'agente si sveglia solo sul verdetto rosso più
una passata settimanale — ~10 esecuzioni al mese — ma una passata agentica vera è
molti turni, e a ogni turno la storia viene rimandata: si arriva facilmente a un
milione di token di input cumulativo, cioè **qualche euro a esecuzione** su Opus 5.

Quindi: tetto di spesa basso in console, e si sceglie il modello dopo il rodaggio, coi
numeri veri di dieci passate. Listini per milione di token (agosto 2026):

| modello | input | in cache | output |
|---|---|---|---|
| `claude-opus-5` | $5,00 | — | $25,00 |
| `claude-sonnet-5` | $3,00 | — | $15,00 |
| `kimi-k3` | $3,00 | $0,30 | $15,00 |
| `kimi-k2.6` / `kimi-k2.7-code` | $0,95 | $0,16 | $4,00 |
| `claude-haiku-4-5` | $1,00 | — | $5,00 |

Nota che **`kimi-k3` costa quanto Sonnet 5**: passare a Kimi non è di per sé un
risparmio. La leva economica è `k2.6`, ed è plausibile che basti — il compito è
*diagnosticare un guasto che il codice ha già identificato e nominato*, non trovarlo.
Il rodaggio è il posto dove verificarlo.

**Il gratis non esiste su questa strada:** l'API Kimi non ha piano gratuito né crediti
di prova (il gratuito è l'app consumer, un altro prodotto), e il locale è fuori
discussione — pesi aperti sì, ma un MoE fuori dalla portata del Linode, e un modello
abbastanza piccolo da girarci scriverebbe patch sbagliate sul motore del voto.

**Il gratis che invece esiste è già in produzione:** `health_report` + canarino + mail
non chiamano nessun modello e sono il 90% del valore — trasformano il guasto silenzioso
in un guasto rumoroso e ne scrivono la diagnosi («`duelWon` sparita, `duelsWon`
comparsa»). L'agente compra il 10% restante: che la correzione venga scritta, provata e
applicata alle tre di notte senza di te. È comodità, non sicurezza — e resta legittimo
decidere di non costruirlo e correggere a mano la mattina dopo.

### Il secondo fornitore: Kimi, e non serve un secondo adattatore

Moonshot espone un endpoint **compatibile Anthropic** (`/anthropic/v1/messages`), e la
CLI accetta una base URL personalizzata: stessa CLI, stesso contratto JSON, stesso
`prompt.md`, stessa lista di strumenti permessi. Cambia solo l'ambiente.

```sh
# deploy/agent/vfoot-agent-kimi — identico all'altro, con questo blocco davanti
ANTHROPIC_BASE_URL="https://api.moonshot.ai/anthropic"
ANTHROPIC_AUTH_TOKEN="$KIMI_API_KEY"
ANTHROPIC_MODEL="kimi-k3"
CLAUDE_CODE_AUTO_COMPACT_WINDOW="1048576"   # k3 ha 1M di contesto
```

Modelli: **`kimi-k3`** (consigliato, ragionamento attivo da sé), `kimi-k2.7-code` e la
variante `-highspeed` (più veloci ma **pretendono** il thinking esplicito, altrimenti
400), `kimi-k2.6` per la latenza. Tre avvertenze verificate:

* **WebFetch non è supportato** su quell'endpoint — e nel nostro disegno l'agente non
  ce l'ha comunque, gliel'abbiamo tolto perché non deve leggere payload che vengono da
  fuori. Il limite del fornitore coincide con il nostro confine di sicurezza;
* usare `k3` evita del tutto la trappola del thinking obbligatorio delle varianti
  `k2.7-code`;
* il menu `/model` non mostra Kimi: si verifica con `/status`.

Quindi il seam JSON-in/JSON-out **non** serve per Kimi (il contratto è già rispettato a
monte): serve per una CLI futura che non parli Anthropic, e soprattutto per
`vfoot-agent-fake`. Resta.

**Da sapere prima e non dopo:** puntare la base URL su Moonshot significa che il prompt
e i pezzi di codice che l'agente legge vanno sui loro server. È una decisione su dove
finiscono i dati, non un dettaglio tecnico.

Fonti: [Use Kimi in Claude Code](https://platform.kimi.ai/docs/guide/claude-code-kimi),
[MoonshotAI/Kimi-K2 #129](https://github.com/MoonshotAI/Kimi-K2/issues/129).

**Il guadagno vero**: un `vfoot-agent-fake` che stampa una proposta finta fa girare nei
test tutta la catena rischiosa — validazione, click, applicazione, fumo, **ripristino**
— in modo deterministico e in mezzo secondo. La macchina del rollback è la cosa che non
puoi permetterti di scoprire rotta la notte in cui serve, e senza questo seam non la
proveresti mai davvero.

Il lock-in residuo è il **prompt**, cioè un Markdown versionato in `deploy/agent/`. È
anche l'unica parte tarata su un modello preciso, ed è giusto che stia in git e non
dentro un client. Per Opus 5 va scritto sapendo tre cose:

* **niente istruzioni di verifica** — le fa da sé, e dirglielo lo porta a esagerare.
  È una cancellazione, non una riscrittura;
* **disciplina di scopo** — tende ad allargare il compito; va detto di consegnare
  quello che è stato chiesto e di segnalare, non di fare;
* **niente sottoagenti** — delega volentieri, e qui non serve a niente se non a
  moltiplicare costo e latenza.

Le tre sono al peggio inerti su un altro modello, quindi il prompt resta condivisibile.

## Poteri

L'agente gira come `vfoot`, nel checkout, **senza sudo**: legge, cerca, fa girare i
test, crea un branch. Non può riavviare niente. Il potere sta tutto nell'esecutore, che
ha la sua regola sudoers stretta — di nuovo la forma di `/usr/local/sbin/vfoot-egress`.

L'unica cosa nuova sulla macchina è una chiave API nel `.env`, leggibile solo da
`vfoot`, con un tetto di spesa impostato dalla console del fornitore.

Se l'agente non risponde, va in timeout o dice sciocchezze: passata fallita, riga nel
diario, e la sorveglianza deterministica continua. **Non è mai portante** — è un
consulente, non un pilastro. Registrando le sue passate come `JobRun`, `health_report`
si accorge gratis anche di quando l'agente stesso smette di girare.

## La continuità

L'agente è senza memoria fra una passata e l'altra. Se non scrive, mercoledì
rediagnostica da zero il problema di martedì e magari lo «ripara» una seconda volta.

Serve un diario append-only — `MaintenanceRun`, gemello di `JobRun`, con la stessa
disciplina — e una regola sopra: **prima di proporre, rileggi le ultime passate; se
questa proposta l'hai già fatta e te l'hanno rifiutata, non riproporla.** Senza quella
riga diventa un collega che ripete la stessa idea ogni mattina finché non lo spegni.

## Cosa costruire, in ordine

1. `MaintenanceProposal` + `MaintenanceRun` (modelli), e l'esecutore con la
   validazione contro le liste. **Zero modelli LLM coinvolti**: si prova tutto con
   `vfoot-agent-fake`.
2. Il tag + il controllo di fumo + il timer dell'uomo morto, provati con il finto.
   È il pezzo pericoloso: va prima, e va provato prima.
3. Pagina Manutenzione (area gestore sito, oggi inesistente) + push + i due bottoni.
4. L'adattatore vero e `deploy/agent/prompt.md`.
5. **Rodaggio in sola lettura, 2-3 settimane**: nessun livello auto, nessun
   `apply_patch`. Serve a vedere se le sue diagnosi sono giuste prima di dargli le
   mani, e a te per sapere com'è fatta una settimana normale.

## Domande ancora aperte

- ~~Il livello `auto` parte acceso o spento?~~ **DECISO 11/08/2026: parte spento.**
  Si accende dopo il deploy, quando il rodaggio ha mostrato che le diagnosi reggono.
- ~~Quale modello.~~ **DECISO 11/08/2026: `claude-opus-5` a effort `xhigh`, con Kimi
  (`kimi-k3`) come secondo fornitore a quattro variabili d'ambiente di distanza.**
  Vedi la sezione sopra.
- `apply_patch` arriva in produzione da solo dopo il tuo click (con il ripristino), o
  si ferma al branch e aspetta il computer? Deciso: arriva, perché fermarsi al branch
  lascia il guasto aperto proprio nel caso per cui l'agente esiste — ma è la scelta da
  ridiscutere se il rodaggio va male.
