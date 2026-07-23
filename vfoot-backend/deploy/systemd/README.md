# Unità systemd del server (Linode)

Coppie `service` + `timer` per i job schedulati di Vfoot. Convenzione: `oneshot`
eseguito da un timer, `User=vfoot`, `WorkingDirectory=.../vfoot-backend/src`,
interprete dal venv del backend. Le unità vive stanno in `/etc/systemd/system/`
sul server; questi file ne sono la copia versionata.

Job attuali:

| unità | cadenza | comando |
|---|---|---|
| `vfoot-tick` | ogni minuto | `manage.py tick` — stato live/finalizzazione partite |
| `vfoot-calendar` | 04:30 | `manage.py sync_calendar` — calendario campionato reale |
| `vfoot-tm-poll` | 06:00 e 18:00 | `manage.py poll_transfermarkt` — rose TM → listone + ruoli |

## Installare / aggiornare `vfoot-tm-poll`

Transfermarkt è raggiungibile dall'IP datacenter del Linode (a differenza di
SofaScore), quindi questo job gira interamente lato server. Da deployare INSIEME
al codice corrente (produzione oggi è ferma a `03b099b`, senza `poll_transfermarkt`).

```sh
# copiare le unità
scp vfoot-tm-poll.service vfoot-tm-poll.timer \
    root@139.162.144.123:/etc/systemd/system/

# provare il comando UNA volta a mano, in sola lettura, prima di schedularlo
sudo -u vfoot /srv/vfoot-app/vfoot-backend/.venv/bin/python \
    /srv/vfoot-app/vfoot-backend/src/manage.py poll_transfermarkt --dry-run

# abilitare il timer
systemctl daemon-reload
systemctl enable --now vfoot-tm-poll.timer
systemctl list-timers vfoot-tm-poll.timer     # verifica prossima esecuzione
```

`poll_transfermarkt` è idempotente e ha tre presidi per l'esecuzione non
presidiata: scrape sempre fresco (mai cache vecchia), stagione TM derivata dalla
`CompetitionSeason` (non possono divergere), e rifiuto sia delle partenze quando
lo scrape è incompleto sia delle mappature-club sotto soglia (`--min-map-score`).
