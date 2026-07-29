/** Registering the service worker, and handling the version that comes after.
 *
 *  The awkward part of a PWA is not the first install, it is the second deploy.
 *  A new worker installs and then WAITS until every tab of the app is closed
 *  before taking over — on a phone with the app permanently open, that day never
 *  comes, and users sit on last week's build wondering why a fix did not land.
 *
 *  So we watch for the waiting worker and let the app offer a reload. The switch
 *  is the user's, not ours: reloading under someone in the middle of an auction
 *  would be worse than being one version behind.
 */

let waiting: ServiceWorker | null = null;
const listeners = new Set<(updateReady: boolean) => void>();

function announce(ready: boolean) {
  listeners.forEach((fn) => fn(ready));
}

export function onUpdateReady(fn: (updateReady: boolean) => void): () => void {
  listeners.add(fn);
  fn(waiting !== null);
  return () => listeners.delete(fn);
}

/** Tell the waiting worker to take over, then reload once it has. */
export function applyUpdate(): void {
  if (!waiting) return;
  // controllerchange fires when the new worker is in charge; reloading before
  // that would just re-run the old one.
  navigator.serviceWorker.addEventListener('controllerchange', () => window.location.reload(), {
    once: true,
  });
  waiting.postMessage({ type: 'SKIP_WAITING' });
  waiting = null;
  announce(false);
}

/** Where the worker lives, which is NOT the same in dev and in production.
 *
 *  The dev server transforms the worker on the fly and serves it from
 *  `/dev-sw.js?dev-sw` as an ES module; the build emits a classic script at
 *  `/sw.js`. Registering the production path during `npm run dev` gets the SPA's
 *  index.html back with the wrong MIME type and the registration fails silently
 *  — which is exactly the kind of "works on my machine, dead in dev" split worth
 *  spelling out.
 */
function workerUrl(): { url: string; type: WorkerType } {
  return import.meta.env.DEV
    ? { url: '/dev-sw.js?dev-sw', type: 'module' }
    : { url: '/sw.js', type: 'classic' };
}

export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (typeof window === 'undefined' || !('serviceWorker' in navigator)) return null;
  try {
    const { url, type } = workerUrl();
    const reg = await navigator.serviceWorker.register(url, { type, scope: '/' });

    if (reg.waiting && navigator.serviceWorker.controller) {
      waiting = reg.waiting;
      announce(true);
    }
    reg.addEventListener('updatefound', () => {
      const installing = reg.installing;
      if (!installing) return;
      installing.addEventListener('statechange', () => {
        // `controller` distinguishes an UPDATE from the very first install: on a
        // first install there is nothing to warn anybody about.
        if (installing.state === 'installed' && navigator.serviceWorker.controller) {
          waiting = installing;
          announce(true);
        }
      });
    });
    return reg;
  } catch (err) {
    // A failed registration must never take the app down with it: without a
    // service worker this is simply the website it has always been.
    console.warn('Service worker non registrato:', err);
    return null;
  }
}
