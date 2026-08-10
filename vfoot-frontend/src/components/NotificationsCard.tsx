import { useEffect, useState } from 'react';
import { Button, Card, SectionTitle } from './ui';
import IosInstallSteps from './IosInstallSteps';
import {
  installPromptAvailable,
  isIOS,
  isStandalone,
  onAppInstalled,
  onInstallPromptChange,
  promptInstall,
} from '../pwa/install';
import { usePush } from '../pwa/usePush';

/** Notifications and installation, in the one place a user goes looking for them.
 *
 *  The order on screen is deliberate: on iOS the install comes FIRST, because
 *  without it the notification switch cannot work at all — Safari only grants
 *  push to a web app started from the Home Screen. Elsewhere installation is a
 *  nicety and the switch works either way, so it is offered second.
 */
export default function NotificationsCard() {
  const push = usePush();
  const [canInstall, setCanInstall] = useState(installPromptAvailable());
  const [showIosSteps, setShowIosSteps] = useState(false);
  // Due domande diverse, e prima ne rispondevamo a una sola. `isStandalone()` dice
  // «questa finestra È l'app», che nella scheda del browser da cui si preme il
  // bottone è falso e resta falso: da lì l'installazione riuscita non aveva alcun
  // riscontro, e la scheda continuava a offrirla come se non fosse successo nulla.
  const [justInstalled, setJustInstalled] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const running = isStandalone();
  const ios = isIOS();
  const installed = running || justInstalled;

  useEffect(() => onInstallPromptChange(setCanInstall), []);
  useEffect(() => onAppInstalled(() => setJustInstalled(true)), []);

  return (
    <Card className="p-4">
      <SectionTitle>Notifiche e installazione</SectionTitle>

      {!installed && ios ? (
        <div className="mt-3 rounded-xl border-l-4 border-accent bg-accent/10 p-3">
          <div className="text-sm font-bold text-accent">Installa l'app per ricevere le notifiche</div>
          <div className="mt-1 text-sm text-accent">
            Su iPhone e iPad gli avvisi arrivano solo dall'app aggiunta alla schermata
            Home. Safari non lo propone da sé: va fatto una volta a mano.
          </div>
          <button
            type="button"
            className="mt-2 text-sm font-semibold text-accent underline decoration-dotted"
            onClick={() => setShowIosSteps((v) => !v)}
          >
            {showIosSteps ? 'Nascondi i passaggi' : 'Come si fa'}
          </button>
          {showIosSteps ? <IosInstallSteps /> : null}
        </div>
      ) : null}

      {!installed && !ios ? (
        canInstall ? (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                void promptInstall().then((r) => {
                  if (r === 'accepted') setJustInstalled(true);
                  else if (r === 'dismissed') setDismissed(true);
                });
              }}
            >
              Installa l'app
            </Button>
            <span className="text-xs text-ink-faint">
              Si apre in un tocco, come un'app, e ti tiene la lega a portata di mano.
            </span>
          </div>
        ) : (
          /* No captured prompt does NOT mean "not installable": Chrome only fires
             beforeinstallprompt once the user has engaged with the page, and some
             browsers never fire it at all. Without this line the whole install
             option would silently disappear on a first visit. */
          <div className="mt-3 text-xs text-ink-faint">
            Puoi installare l'app dal menu del browser (⋮ → «Installa app»): si apre in
            un tocco e ti tiene la lega a portata di mano. Se la voce non c'è ancora,
            ricarica dopo qualche secondo di navigazione.
          </div>
        )
      ) : null}

      {dismissed && !installed ? (
        <div className="mt-2 text-xs text-ink-faint">
          Installazione annullata. Puoi rifarla dal menu del browser (⋮ → «Installa app»).
        </div>
      ) : null}

      {installed ? (
        <div className="mt-3 text-xs font-semibold text-good">
          {running
            ? 'App installata su questo dispositivo.'
            : 'App installata: la trovi fra le applicazioni del telefono.'}
        </div>
      ) : null}

      {/* Detto SOLO a chi ha appena installato e sta ancora guardando la scheda del
          browser: se l'icona apre una pagina con la barra dell'indirizzo, non è un
          difetto dell'app ma di dove la si sta provando — un'app a schermo intero
          su Android la crea Chrome solo per un indirizzo HTTPS pubblico. In
          produzione non capita; da un IP di rete in sviluppo capita sempre. */}
      {justInstalled && !running && location.protocol !== 'https:' ? (
        <div className="mt-1 text-xs text-ink-faint">
          Su un indirizzo non HTTPS l'icona apre comunque dentro il browser: è un
          limite di questo indirizzo di prova, non dell'app.
        </div>
      ) : null}

      <div className="mt-4 border-t pt-3">
        {/* The order of these branches is the point. `available` starts false —
            it has to, we have not asked the server yet — so putting its message
            first meant that "sto ancora guardando" and "il server non ha le
            chiavi" printed the same sentence, and a hook that never settled printed
            it for ever: the one server whose keys were fine got blamed for the
            worker's crash. Loading is not a diagnosis and must not read like one. */}
        {!push.loaded ? (
          <div className="text-sm text-ink-faint">Controllo le notifiche…</div>
        ) : !push.available ? (
          <div className="text-sm text-ink-faint">
            Le notifiche push non sono attive su questo server. Gli avvisi arrivano per email.
          </div>
        ) : push.blocked ? (
          <div className="text-sm text-ink-faint">{push.blocked}</div>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <Button
              size="sm"
              variant={push.subscribed ? 'secondary' : 'primary'}
              disabled={push.busy}
              onClick={() => void (push.subscribed ? push.disable() : push.enable())}
            >
              {push.busy
                ? 'Attivo le notifiche…'
                : push.subscribed
                  ? 'Disattiva le notifiche'
                  : 'Attiva le notifiche'}
            </Button>
            <span className="text-xs text-ink-faint">
              {push.busy
                ? /* Measured at ~30s on a cold browser: the first subscription
                     makes the browser register with its push service, and a
                     silent half-minute reads as a broken button. */
                  'La prima volta può richiedere una ventina di secondi: il browser si sta registrando al servizio di notifiche.'
                : /* Not a feature list: what we notify about will grow, and copy
                     that enumerates today's features ages badly. */
                  push.subscribed
                  ? 'Ti avviseremo di quello che succede nella tua lega e che ti riguarda.'
                  : 'Solo quello che ti riguarda: niente avvisi inutili.'}
            </span>
          </div>
        )}
        {push.error ? (
          <div className="mt-2 rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">
            {push.error}
          </div>
        ) : null}
      </div>
    </Card>
  );
}
