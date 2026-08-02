# I job schedulati del server (Linode)

**Questo file è l'inventario**: tutto ciò che gira da solo in produzione sta qui.
Un job che non è in questa tabella non esiste — e un job che esiste solo nella
testa di qualcuno è un job che, il giorno che smette di girare, nessuno cerca.

Sono unità systemd, non righe di crontab. La differenza che conta: `Persistent=true`
recupera un'esecuzione saltata mentre il server era spento (cron la perde e basta),
`RandomizedDelaySec` evita di bussare a un sito esterno allo stesso secondo ogni
giorno, e il log finisce nel journal insieme al resto (`journalctl -u vfoot-tick`)
invece che in una mail a root che nessuno legge.

Convenzione: `Type=oneshot` mosso da un timer, `User=vfoot` (tranne dove serve
root, indicato sotto), `WorkingDirectory=/srv/vfoot-app/vfoot-backend/src`,
interprete dal venv del backend. Le unità vive stanno in `/etc/systemd/system/`;
questi file ne sono la copia versionata. L'ambiente (DB, SMTP, VAPID) arriva da
`/srv/vfoot-app/.env`, che `config/settings.py` carica da sé: nessun
`EnvironmentFile` nelle unità.

## Inventario

| unità | cadenza | comando | cosa si rompe se non gira |
|---|---|---|---|
| `vfoot-tick` | ogni minuto | `tick` | i risultati reali non entrano mai: niente live, niente `data_ready`, quindi nessuna giornata concludibile |
| `vfoot-calendar` | 00/06/12/18 | `sync_calendar --egress` | orari e rinvii restano quelli vecchi: le formazioni si bloccano all'ora sbagliata |
| `vfoot-tm-poll` | 06 e 18 | `poll_transfermarkt` | il listone invecchia: i trasferimenti non compaiono |
| `vfoot-egress-refill` | 03/09/15/21 | `sofascore_egress.py refill` | il pool di IP si esaurisce e SofaScore torna a bloccarci (**root**) |
| `vfoot-market` | ogni 90 s | `market_tick` | il mercato resta corretto ma **muto**: nessuno viene avvisato di una chiusura o di un sorpasso |
| `vfoot-nudge` | 10:00 | `nudge_conclusions` | l'admin distratto non viene mai richiamato: classifica ferma finché non se ne accorge da solo |
| `vfoot-backup` | 03:15 | `/usr/local/sbin/vfoot-backup` | **nessuna copia dei dati** fra un deploy e l'altro (**root**) |

Fuori da questa tabella, ma schedulato lo stesso: il rinnovo dei certificati TLS,
che è il timer di sistema `certbot.timer` (vedi `DEPLOY.md`) — di nostro non ha
niente, ma se un giorno il sito diventa irraggiungibile in HTTPS, si guarda lì.

### Il backup è ancora mezzo backup

`vfoot-backup` scrive in `/root/backups`, cioè **sullo stesso disco della cosa che
sta salvando**. Protegge da quello che succede più spesso — una migrazione andata
male, una cancellazione, un deploy da rifare — e non protegge per niente dal caso
in cui si perde il Linode. Perché sia un backup vero manca una copia fuori dal
server (S3/Backblaze, o anche solo un `rsync` notturno verso casa). È una
decisione aperta, non una dimenticanza.

### Le due dipendenze da conoscere

`vfoot-tick` e `vfoot-calendar` escono verso SofaScore attraverso il ponte sudo
`/usr/local/sbin/vfoot-egress`: **accesi senza quello fallirebbero a ogni scatto**.
L'installer se ne accorge e li salta invece di riempire il journal di errori.
Gli altri cinque non dipendono da niente e si possono accendere quando si vuole.

`vfoot-market` e `vfoot-nudge` mandano email e push: senza le credenziali Brevo e
le chiavi VAPID nel `.env` non falliscono — semplicemente non notificano nulla, il
che è peggio, perché sembra che funzionino. Verificarlo al primo giro.

## Installare e accendere

```sh
# sul server, come root, dal checkout
cd /srv/vfoot-app/vfoot-backend/deploy/systemd

./install.sh --dry-run          # cosa farebbe
./install.sh                    # copia unità + script di backup, daemon-reload, NON accende
./install.sh --status           # cosa è acceso e quando scatta il prossimo
```

Installare **non** accende: è la postura con cui il server sta oggi, tutto pronto
e spento. Accendere è un gesto separato:

```sh
./install.sh --enable tm-poll --enable backup    # uno alla volta
./install.sh --enable-all                        # go-live
```

### Prima di accendere un job nuovo

Ognuno di questi si può provare a mano, e conviene farlo: un comando che gira ogni
minuto e sbaglia, sbaglia 1440 volte al giorno.

```sh
sudo -u vfoot /srv/vfoot-app/vfoot-backend/.venv/bin/python \
  /srv/vfoot-app/vfoot-backend/src/manage.py poll_transfermarkt --dry-run
sudo -u vfoot ... manage.py tick --dry-run
sudo -u vfoot ... manage.py market_tick --dry-run
sudo -u vfoot ... manage.py nudge_conclusions --dry-run
/usr/local/sbin/vfoot-backup --dry-run
```

`sync_calendar` non ha un `--dry-run`, ma ha `--offline`, che gli fa leggere solo
la cache già scaricata.

`poll_transfermarkt` è idempotente e ha tre presidi per l'esecuzione non
presidiata: scrape sempre fresco (mai cache vecchia), stagione TM derivata dalla
`CompetitionSeason` (non possono divergere), e rifiuto sia delle partenze quando
lo scrape è incompleto sia delle mappature-club sotto soglia (`--min-map-score`).

## Aggiungere un job

Tre cose, nessuna delle quali opzionale:

1. i due file `vfoot-<nome>.{service,timer}` qui dentro;
2. il nome in `ALL_UNITS` dentro `install.sh`;
3. **una riga nella tabella qui sopra**, con la colonna "cosa si rompe" compilata
   davvero — se non si riesce a scriverla, vale la pena chiedersi se il job serve.

## Quando qualcosa non torna

```sh
systemctl list-timers 'vfoot-*'        # quando ha girato, quando rigira
journalctl -u vfoot-tick --since today # cosa ha detto
systemctl status vfoot-backup.service  # l'ultimo esito
```

Un `oneshot` che fallisce **non** ferma il timer: riproverà allo scatto successivo.
Comodo per un errore passeggero (rete giù), infido per uno permanente — che resta
a fallire in silenzio finché qualcuno non guarda. Il primo posto dove guardare, se
un dato sembra fermo, è `list-timers`.
