import { useEffect, useState } from 'react';
import { Button, Card } from './ui';
import IosInstallSteps from './IosInstallSteps';
import {
  installPromptAvailable,
  isIOS,
  isStandalone,
  onInstallPromptChange,
  promptInstall,
} from '../pwa/install';

/** The one place the app asks to be installed, in Home where people actually go.
 *
 *  Why ours and not the browser's: on iOS there IS no browser invitation — Safari
 *  proposes nothing, ever — and iPhone users are exactly the ones for whom the
 *  install is a PRECONDITION for notifications. Leaving it to the browser would
 *  cover Android and abandon half a league without telling them why.
 *
 *  Shown once. Dismissing it is remembered, because an invitation that returns
 *  every visit is an advert; the offer stays available in Profilo for whoever
 *  closes it and changes their mind.
 */
const DISMISSED_KEY = 'vfoot_install_banner_dismissed';

function wasDismissed(): boolean {
  if (typeof window === 'undefined') return true;
  try {
    return window.localStorage.getItem(DISMISSED_KEY) === '1';
  } catch {
    // Private mode with storage denied: better to show nothing than to crash.
    return true;
  }
}

export default function InstallBanner() {
  const [dismissed, setDismissed] = useState(wasDismissed);
  const [canInstall, setCanInstall] = useState(installPromptAvailable());
  const [showSteps, setShowSteps] = useState(false);
  const ios = isIOS();

  useEffect(() => onInstallPromptChange(setCanInstall), []);

  // Already installed => there is nothing to ask for. Checked at render rather
  // than stored: the same origin can be opened both ways.
  if (dismissed || isStandalone()) return null;

  const close = () => {
    setDismissed(true);
    try {
      window.localStorage.setItem(DISMISSED_KEY, '1');
    } catch {
      /* nothing to remember it with; it will reappear, and that is acceptable */
    }
  };

  return (
    <Card className="border-l-4 border-sky-500 bg-sky-50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-bold text-sky-900">📲 Tieni Vfoot sul telefono</div>
          {/* Deliberately not a feature list: what the app notifies about will grow
              (mercato, asta, giornate), and copy that enumerates today's features
              ages badly. The promise is "non ti perdi niente", which stays true. */}
          <div className="mt-1 text-sm text-sky-800">
            Si apre in un tocco, come un'app, e ti avvisa di quello che succede nella
            tua lega.
          </div>
        </div>
        <button
          type="button"
          onClick={close}
          aria-label="Chiudi l'invito a installare"
          className="shrink-0 rounded-lg px-2 py-1 text-sky-700 hover:bg-sky-100"
        >
          ✕
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        {ios ? (
          <button
            type="button"
            className="text-sm font-semibold text-sky-900 underline decoration-dotted"
            onClick={() => setShowSteps((v) => !v)}
          >
            {showSteps ? 'Nascondi i passaggi' : 'Come si fa su iPhone'}
          </button>
        ) : canInstall ? (
          <Button size="sm" variant="primary" onClick={() => void promptInstall()}>
            Installa
          </Button>
        ) : (
          /* No captured prompt is not the same as "not installable": Chrome only
             fires beforeinstallprompt after some engagement with the page. */
          <span className="text-xs text-sky-800">
            Dal menu del browser (⋮) scegli «Installa app».
          </span>
        )}
        {ios ? (
          <span className="text-xs text-sky-800">
            Su iPhone è l'unico modo per ricevere le notifiche.
          </span>
        ) : null}
      </div>

      {ios && showSteps ? <IosInstallSteps /> : null}
    </Card>
  );
}
