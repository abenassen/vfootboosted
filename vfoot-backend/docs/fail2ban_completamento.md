# fail2ban: il pezzo che manca, e quando accenderlo

**Lavoro in sospeso, con una scadenza vera.** Il rate limit di nginx è in
produzione dal 17/08/2026 e funziona; la jail di fail2ban che lo completa è
scritta e versionata ma **volutamente spenta**. Questo documento dice quando
accenderla, su quali dati, e perché aspettare non è pigrizia.

Il ragionamento completo sta in `rate_limit_plan.md`. Qui c'è solo la cosa da
fare.

## Perché non è già accesa

fail2ban è l'unico livello che può **bannare i nostri**, e sbaglia in modo
asimmetrico:

- Col solo limite di nginx, chi eccede prende un 429, il client ritenta e la cosa
  si ripara da sola.
- Con la jail, quello stesso IP viene bannato **al firewall**. Il ban non
  colpisce solo l'API: **fa cadere anche il WebSocket**, che ci si era
  preoccupati di non limitare. `useNudgeSocket` ritenta con backoff fermo a 15
  secondi contro un pacchetto che il firewall scarta, e tutta la stanza resta
  fuori dall'asta finché il ban non scade.

La soglia (`maxretry`) va quindi scelta sapendo **quanti 429 di auth produce la
vita normale**, non a occhio. Oggi quel numero non lo sappiamo: il rate limit è
attivo da poche ore e non c'è ancora stata né un'asta né una giornata di
campionato con il limite in mezzo.

## ⚠️ La finestra è di 14 giorni, non «qualche settimana»

`/etc/logrotate.d/nginx` ruota **ogni giorno** e conserva **14 rotazioni**. Il
log che serve a decidere **sparisce da solo il quindicesimo giorno**, in
silenzio.

Quindi:

- **Guardare entro il 31/08/2026**, oppure
- far accumulare il conteggio da qualche parte che non ruota (vedi
  «Conservare le prove più a lungo»).

Se l'asta della lega cade dopo il 31/08 e non si è fatto niente, il dato per
decidere non c'è più e si torna al punto di partenza — con l'aggravante di
credere di avere delle prove.

## Il fondo scala di oggi: 6, e sono miei

Al 17/08/2026, subito dopo il deploy, l'error log contiene:

| zona | righe | chi |
|---|---|---|
| `vfoot_api` | 169 | **collaudo mio** (400 richieste con un token finto) |
| `vfoot_auth` | 6 | **collaudo mio** (raffica su `/auth/register`) |

**Nessuna di queste è traffico vero.** Chi legge il log a settembre e trova 6
rifiuti di auth non deve concludere che qualcuno stava attaccando il login: erano
la prova che il limite funziona. Il conteggio utile parte da zero **dopo** il
17/08/2026, ore 13:00 UTC.

## Cosa misurare

La jail guarda **solo** la zona `vfoot_auth` (è legata al nome della zona, non ai
429 in generale), quindi è solo quel numero che conta.

```bash
ssh root@139.162.144.123 '
  echo "--- vfoot_auth negli ultimi 14 giorni (log ruotati inclusi):"
  zgrep -h "zone \"vfoot_auth\"" /var/log/nginx/error.log* 2>/dev/null | wc -l
  echo "--- da quali indirizzi, e quanti a testa:"
  zgrep -h "zone \"vfoot_auth\"" /var/log/nginx/error.log* 2>/dev/null \
    | grep -oP "client: \K[0-9a-f.:]+" | sort | uniq -c | sort -rn | head
  echo "--- e in che giorni:"
  zgrep -h "zone \"vfoot_auth\"" /var/log/nginx/error.log* 2>/dev/null \
    | cut -d" " -f1 | sort | uniq -c
'
```

`zgrep` e la `*` sono necessari: senza, si legge solo la giornata in corso e si
conclude «zero» qualunque cosa sia successa la settimana prima.

## La regola di decisione

Il numero che conta è **quanti rifiuti di auth ha prodotto il picco di una
giornata normale** — cioè la sera dell'asta, o la domenica.

| cosa si trova | cosa vuol dire | cosa fare |
|---|---|---|
| **0-5 in tutto il periodo** | nessuno ci si avvicina nemmeno | accendere con `maxretry = 60` così com'è |
| **decine, ma tutte da IP di scanner** | il limite lavora contro estranei | accendere così com'è; è esattamente il caso per cui esiste |
| **decine da un IP solo, il giorno dell'asta** | **sono i nostri**: `burst=20` è stretto per quella lega | **prima** alzare `burst` in nginx, poi rimisurare, poi accendere |
| **centinaia da un IP ignoto** | è già in corso quello che temevamo | accendere subito, e guardare `rate_limit_plan.md` § livello 4 |

Il caso da riconoscere è il terzo, e si riconosce da una cosa sola: **l'IP che
compare è uno di quelli che si sono collegati all'asta**. Se il conteggio per
indirizzo mostra un solo IP con molti rifiuti nella data dell'asta, la soglia
della jail non c'entra — è il `burst` di nginx a essere sottodimensionato per
quella lega, e va corretto lì. Alzare `maxretry` in quel caso nasconde il
problema invece di risolverlo.

## Accendere

```bash
scp deploy/fail2ban/jail.d/vfoot.local root@139.162.144.123:/etc/fail2ban/jail.d/
ssh root@139.162.144.123 'fail2ban-client -t && systemctl reload fail2ban && fail2ban-client status'
```

Prima, i due controlli in `deploy/fail2ban/README.md`: che i filtri
`nginx-limit-req` e `nginx-botsearch` esistano sulla macchina, e che i percorsi
dei log siano quelli attesi. Se un filtro manca, la jail non parte e fail2ban lo
dice **solo nel suo log**: sembra tutto a posto e non protegge niente.

## Nelle 48 ore dopo

```bash
ssh root@139.162.144.123 'fail2ban-client status vfoot-auth-limit; fail2ban-client status vfoot-botsearch'
```

- `vfoot-botsearch` deve **iniziare a bannare subito**: gli scanner bussano di
  continuo. Se resta a zero, la jail non sta leggendo niente e va guardata.
- `vfoot-auth-limit` deve **restare a zero** finché nessuno attacca. Se conta
  qualcosa senza un attacco in corso, sta contando i nostri: guardare **subito**
  quale IP è.

Il sintomo di un ban sbagliato non è «il sito è lento»: è **una casa intera che
non entra più e l'asta piantata**, perché cade anche il WebSocket. Si sblocca
con:

```bash
ssh root@139.162.144.123 'fail2ban-client set vfoot-auth-limit unbanip <IP>'
```

## Conservare le prove più a lungo

Se l'asta cade oltre i 14 giorni, il modo più semplice per non perdere il dato è
un conteggio giornaliero che scriva fuori dai log che ruotano:

```bash
# una riga al giorno: data e quanti rifiuti di auth
ssh root@139.162.144.123 'cat >/etc/cron.d/vfoot-authlimit-count <<EOF
5 0 * * * root echo "\$(date -I) \$(grep -c \"zone \\\"vfoot_auth\\\"\" /var/log/nginx/error.log)" >> /root/vfoot_auth_429.log
EOF'
```

Gira alle 00:05, quando il log del giorno prima è ancora quello corrente. Non è
sorveglianza vera — quella è il punto 5 del piano, agganciata a `vfoot-health` —
ma basta a non arrivare a settembre senza niente in mano.

## In breve

1. **Entro il 31/08/2026** guardare il conteggio, o installare il contatore
   giornaliero qui sopra.
2. Il numero utile è quello del **giorno dell'asta**, non il totale.
3. Se i rifiuti vengono da **un IP solo che era in asta**, si corregge il `burst`
   di nginx, non la soglia della jail.
4. Poi accendere, e ricontrollare dopo 48 ore.
