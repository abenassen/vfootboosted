/** What we can tell about how the app is being run, and how it can be installed.
 *
 *  The whole reason this file exists is that the two platforms behave nothing
 *  alike. Android fires `beforeinstallprompt`, which we capture and replay from
 *  our own button. Safari on iOS fires nothing at all: installing is Share →
 *  "Aggiungi alla schermata Home", done by hand, and if we do not say so nobody
 *  discovers it. And on iOS that gesture is not cosmetic — push notifications
 *  work ONLY from the installed app, never from the site in the browser.
 */

/** True when we are running as an installed app rather than in a browser tab. */
export function isStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  // iOS predates the standard and only exposes the legacy flag.
  const legacy = (window.navigator as Navigator & { standalone?: boolean }).standalone;
  return window.matchMedia('(display-mode: standalone)').matches || legacy === true;
}

export function isIOS(): boolean {
  if (typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent;
  // iPadOS 13+ reports itself as a Mac; the touch points give it away.
  const iPadAsMac = /Macintosh/.test(ua) && navigator.maxTouchPoints > 1;
  return /iPad|iPhone|iPod/.test(ua) || iPadAsMac;
}

/** Does this browser have the plumbing at all? Push needs both a service worker
 *  and a push manager; iOS Safari has them only once installed. */
export function supportsPush(): boolean {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  );
}

/** Why we cannot offer notifications here, in words a user can act on — or null
 *  when we can. */
export function pushBlockedReason(): string | null {
  if (!supportsPush()) {
    if (isIOS() && !isStandalone())
      return 'Su iPhone e iPad le notifiche funzionano solo dall\'app installata sulla schermata Home.';
    return 'Questo browser non supporta le notifiche push.';
  }
  if (isIOS() && !isStandalone())
    return 'Su iPhone e iPad le notifiche funzionano solo dall\'app installata sulla schermata Home.';
  if (typeof Notification !== 'undefined' && Notification.permission === 'denied')
    return 'Hai negato le notifiche per questo sito: va riattivato dalle impostazioni del browser.';
  return null;
}

type InstallPromptEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<unknown> };

let deferred: InstallPromptEvent | null = null;
const listeners = new Set<(available: boolean) => void>();

/** Capture Android's install prompt so it can be offered at a moment that makes
 *  sense to the user, instead of the browser's own timing. Call once at startup. */
export function watchInstallPrompt(): void {
  if (typeof window === 'undefined') return;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault(); // otherwise the browser shows its own mini-infobar
    deferred = e as InstallPromptEvent;
    listeners.forEach((fn) => fn(true));
  });
  window.addEventListener('appinstalled', () => {
    deferred = null;
    listeners.forEach((fn) => fn(false));
  });
}

export function installPromptAvailable(): boolean {
  return deferred !== null;
}

export function onInstallPromptChange(fn: (available: boolean) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Show the captured prompt. Single-shot: the browser will not let us replay it. */
export async function promptInstall(): Promise<boolean> {
  if (!deferred) return false;
  const e = deferred;
  deferred = null;
  listeners.forEach((fn) => fn(false));
  await e.prompt();
  await e.userChoice;
  return true;
}
