import { useEffect, useState } from 'react';
import { Button, Card, SectionTitle } from './ui';
import IosInstallSteps from './IosInstallSteps';
import {
  installPromptAvailable,
  isIOS,
  isStandalone,
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
  const installed = isStandalone();
  const ios = isIOS();

  useEffect(() => onInstallPromptChange(setCanInstall), []);

  return (
    <Card className="p-4">
      <SectionTitle>Notifiche e installazione</SectionTitle>

      {!installed && ios ? (
        <div className="mt-3 rounded-xl border-l-4 border-sky-500 bg-sky-50 p-3">
          <div className="text-sm font-bold text-sky-900">Installa l'app per ricevere le notifiche</div>
          <div className="mt-1 text-sm text-sky-800">
            Su iPhone e iPad gli avvisi arrivano solo dall'app aggiunta alla schermata
            Home. Safari non lo propone da sé: va fatto una volta a mano.
          </div>
          <button
            type="button"
            className="mt-2 text-sm font-semibold text-sky-900 underline decoration-dotted"
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
            <Button size="sm" variant="secondary" onClick={() => void promptInstall()}>
              Installa l'app
            </Button>
            <span className="text-xs text-slate-500">
              Si apre in un tocco, come un'app, e ti tiene la lega a portata di mano.
            </span>
          </div>
        ) : (
          /* No captured prompt does NOT mean "not installable": Chrome only fires
             beforeinstallprompt once the user has engaged with the page, and some
             browsers never fire it at all. Without this line the whole install
             option would silently disappear on a first visit. */
          <div className="mt-3 text-xs text-slate-500">
            Puoi installare l'app dal menu del browser (⋮ → «Installa app»): si apre in
            un tocco e ti tiene la lega a portata di mano. Se la voce non c'è ancora,
            ricarica dopo qualche secondo di navigazione.
          </div>
        )
      ) : null}

      {installed ? (
        <div className="mt-3 text-xs font-semibold text-emerald-700">
          App installata su questo dispositivo.
        </div>
      ) : null}

      <div className="mt-4 border-t pt-3">
        {!push.available ? (
          <div className="text-sm text-slate-500">
            Le notifiche push non sono attive su questo server. Gli avvisi arrivano per email.
          </div>
        ) : push.blocked ? (
          <div className="text-sm text-slate-500">{push.blocked}</div>
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
            <span className="text-xs text-slate-500">
              {push.busy
                ? /* Measured at ~30s on a cold browser: the first subscription
                     makes the browser register with its push service, and a
                     silent half-minute reads as a broken button. */
                  'La prima volta può richiedere una ventina di secondi: il browser si sta registrando al servizio di notifiche.'
                : /* Not a feature list: what we notify about will grow, and copy
                     that enumerates today's features ages badly. */
                  push.subscribed
                  ? 'Ti avviseremo di quello che succede nella tua lega e ti riguarda.'
                  : 'Solo quello che ti riguarda: niente avvisi inutili.'}
            </span>
          </div>
        )}
        {push.error ? (
          <div className="mt-2 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {push.error}
          </div>
        ) : null}
      </div>
    </Card>
  );
}
