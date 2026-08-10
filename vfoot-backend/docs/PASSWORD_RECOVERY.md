# Recupero password

Due endpoint e due pagine. Il pezzo interessante è **quello che non c'è**: nessun
modello, nessuna tabella di token da scrivere, far scadere e ripulire.

## Il token non si salva, si deriva

`django.contrib.auth.tokens.PasswordResetTokenGenerator` costruisce l'hash a
partire da `pk`, **password attuale**, `last_login` e dall'istante di emissione.
Non c'è niente da conservare, e soprattutto:

- appena la password cambia, l'hash cambia → **il link si brucia da solo**, senza
  che nessuno debba ricordarsi di invalidarlo;
- vale per un solo utente: l'hash contiene la sua `pk`;
- scade da sé dopo `PASSWORD_RESET_TIMEOUT` (72 ore, `DJANGO_TOKEN_TIMEOUT`).

È la stessa scelta di `email_verification.py`, che però ha bisogno di un
generatore suo (ci mette dentro `is_active`, perché è l'attivazione a dover
bruciare quel link). Qui va bene quello di serie.

**Conseguenza da conoscere**: `last_login` è nell'hash, e `issue_token()` lo
aggiorna a ogni accesso. Quindi **un accesso normale brucia i link di reset in
sospeso**. È il verso giusto — se ti sei ricordato la password, il link pendente
non deve più contare — ma significa che un link non si può collaudare accedendo
prima.

## I due endpoint

| | |
|---|---|
| `POST /auth/password-reset` | `{email}` → manda il link. **Risposta identica** che l'indirizzo esista o no |
| `POST /auth/password-reset/confirm` | `{uid, token, new_password, new_password_confirm}` → cambia la password e restituisce un token di sessione |

La risposta indistinguibile è deliberata, come in `ResendVerificationView`: dire
"indirizzo sconosciuto" trasformerebbe l'endpoint in un modo per scoprire chi è
registrato. Per la stessa ragione `confirm` dà **un solo** messaggio per "uid
inesistente" e "token sbagliato": distinguerli confermerebbe che un id esiste.

### Cosa succede al momento del reset

- **Le sessioni esistenti muoiono tutte.** Il reset è l'unico momento in cui si
  deve dare per scontato che la vecchia sessione fosse di qualcun altro: lasciarla
  viva conserverebbe proprio l'accesso che il reset serve a chiudere.
- **Chi non aveva mai confermato l'email viene confermato.** Aprire un link
  mandato a quell'indirizzo dimostra esattamente ciò che dimostra l'email di
  conferma. Senza questo, chi ha perso sia la mail di conferma sia la password non
  avrebbe alcun modo di rientrare.
- **Chi è entrato con Google può darsi una password.** Quegli account nascono con
  `set_unusable_password()`, e `google_auth.py` dice già che è da qui che se ne
  danno una. Continuano ad avere anche Google.
- La password è validata **nella view e non nel serializer**, perché solo lì l'uid
  è già risolto: "password uguale al tuo username" è una domanda che ha senso solo
  conoscendo l'utente.

## Il limite di frequenza

`POST /auth/password-reset` manda posta a un indirizzo che chi chiama non possiede,
quindi è a scopo `password_reset`, 5/ora per IP (`DJANGO_PASSWORD_RESET_RATE`).
Senza, uno script lo trasforma in un modo per intasare la casella di qualcuno — e
per bruciare la reputazione del dominio mittente, che è la parte che non torna.

Non c'è `DEFAULT_THROTTLE_CLASSES`: il limite vale solo per le view che lo
chiedono per scope. Un limite globale metterebbe il contatore anche al polling
live e all'asta, dove molte richieste al minuto sono la forma normale.

> **Trappola, costata un test che passava per finta.** DRF lega `THROTTLE_RATES`
> come attributo **di classe** quando importa `rest_framework.throttling`. Un
> `override_settings(REST_FRAMEWORK=...)` cambia `api_settings` e lascia il
> throttle a leggere il dizionario catturato all'avvio: sembra applicato e non lo
> è. Nei test si patcha `ScopedRateThrottle.THROTTLE_RATES` direttamente, e si
> svuota `ScopedRateThrottle.cache` fra un test e l'altro — il contatore vive
> nella cache e sopravvive al singolo test.

## Le pagine

- `/recupera-password` — chiede l'**email**, non l'username: l'indirizzo è la cosa
  di cui possiamo provare il possesso, ed è quella che chi ha perso l'accesso
  ricorda più facilmente. Il messaggio di conferma è lo stesso in ogni caso, per
  non disfare l'anti-enumerazione del server.
- `/nuova-password` — riceve `uid` e `token` dalla query string. A differenza di
  `/verifica-email` **non agisce al caricamento**: serve prima la password. Il
  fallimento più probabile è il link morto, quindi accanto all'errore c'è sempre
  "chiedi un nuovo link".

Il link "Password dimenticata?" compare sotto il campo password della landing,
**solo in modalità accesso**: in registrazione non c'è ancora una password da
recuperare.

## Provarlo in sviluppo

`./vfoot-sim` stampa le email invece di spedirle (`backend.log`) — il `.env` punta
al relay Brevo vero, e provare il recupero manderebbe posta vera all'indirizzo
scritto nel form, con tanto di rimbalzo se è inventato. Per la consegna vera, una
volta e verso un indirizzo che esiste: `VFOOT_SIM_REAL_EMAIL=1 ./vfoot-sim`.

Il link si può anche generare senza spedire niente:

```python
from django.contrib.auth.models import User
from vfoot.services.password_reset import reset_link
print(reset_link(User.objects.get(username="andrea")))
```

Test: `manage.py test vfoot.tests_password_reset` (16 casi).
