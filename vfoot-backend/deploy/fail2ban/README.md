# fail2ban — jail HTTP

Le jail stanno in `jail.d/vfoot.local`, versionate qui come si e' fatto per
systemd e nginx: **non si scrivono a mano sul server**.

Il perche' di ogni scelta e' in `docs/rate_limit_plan.md`. Qui c'e' solo come
metterle in piedi e come accorgersi che stanno facendo danni.

## Prima di installare

Le jail usano due filtri che fail2ban porta con se'. Vanno verificati, perche'
se mancano la jail non parte e fail2ban lo dice solo nel suo log:

```bash
ls /etc/fail2ban/filter.d/nginx-limit-req.conf /etc/fail2ban/filter.d/nginx-botsearch.conf
ls /var/log/nginx/error.log /var/log/nginx/access.log      # i percorsi attesi
```

**Il rate limit di nginx va acceso PRIMA.** La jail `vfoot-auth-limit` legge i
rifiuti che produce la zona `vfoot_auth`: senza quella conf non c'e' niente da
leggere e la jail resta muta per sempre, dando l'impressione sbagliata che vada
tutto bene.

## Installare

```bash
sudo cp jail.d/vfoot.local /etc/fail2ban/jail.d/vfoot.local
sudo fail2ban-client -t                 # come nginx -t: non saltarlo
sudo systemctl reload fail2ban
sudo fail2ban-client status             # devono comparire le due jail nuove
```

## Verificare

```bash
sudo fail2ban-client status vfoot-auth-limit
sudo fail2ban-client status vfoot-botsearch
```

La seconda dovrebbe iniziare a bannare da subito: gli scanner bussano di
continuo. La prima deve restare **a zero** finche' nessuno attacca — se conta
qualcosa senza che ci sia un attacco in corso, sta contando i nostri, e va
guardato subito chi e' (`grep vfoot_auth /var/log/nginx/error.log`).

## Se hai bannato i tuoi

Succede: e' l'unico livello che puo' farlo. Il sintomo non e' «il sito e'
lento», e' **tutta una casa che non entra piu' e l'asta che si e' piantata**,
perche' il ban e' al firewall e fa cadere anche il WebSocket.

```bash
sudo fail2ban-client set vfoot-auth-limit unbanip <IP>
sudo fail2ban-client status vfoot-auth-limit          # per vedere chi c'e' dentro
```

Poi alza `maxretry`, non abbassare il rate limit di nginx: il problema in quel
caso e' la soglia della jail, non il limite.

## Spegnere in fretta

```bash
sudo fail2ban-client stop vfoot-auth-limit
```

Non richiede riavvii e non tocca la jail `sshd`, che deve restare accesa.
