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
 *
 *  E QUALCUNO DEVE CHIEDERE, perche' il browser da solo quasi non lo fa. Il
 *  controllo su `sw.js` parte a una NAVIGAZIONE vera, e in un'app installata
 *  toccare una voce della barra in basso non lo e': e' il router lato client, e
 *  li' non si controlla niente. Chi tiene l'app aperta sul telefono puo' quindi
 *  restare sulla versione di settimane prima senza che la banda compaia mai —
 *  non perche' abbia rifiutato l'aggiornamento, ma perche' non gli e' mai stato
 *  offerto. Successo in produzione il 01/09/2026: un bundle vecchio chiedeva al
 *  server la rosa sbagliata e mostrava tre portieri ceduti da giorni, con i dati
 *  freschissimi e la domanda di agosto.
 *
 *  Da qui `reg.update()` al ritorno in primo piano. NON aggiorna niente: fa
 *  comparire la banda in modo affidabile invece che per caso. Applicarlo resta
 *  una scelta di chi guarda.
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

/** Quanto deve passare fra un controllo e il successivo.
 *
 *  Chi passa avanti e indietro fra due app fa scattare `visibilitychange` a
 *  raffica, e senza una soglia ogni passaggio sarebbe una richiesta. Un minuto
 *  e' abbondante per lo scopo — qui si cerca un rilascio, non un gol.
 */
const UPDATE_CHECK_MIN_MS = 60_000;

/** Chiedi al browser se c'e' una versione nuova, quando l'app torna in primo
 *  piano.
 *
 *  Il controllo e' su `sw.js`, che nginx serve `no-cache`: quando non c'e'
 *  niente di nuovo e' un 304 su 21 KB, e non piu' di uno al minuto.
 *
 *  Niente `setInterval`: una scheda lasciata in primo piano per giorni ce l'ha
 *  gia' il controllo automatico del browser, ogni 24 ore, e il caso che qui
 *  interessa e' l'altro — il telefono in tasca, dove le 24 ore non arrivano mai
 *  perche' non c'e' mai una navigazione.
 */
function checkForUpdatesOnFocus(reg: ServiceWorkerRegistration): void {
  // `register()` ha appena fatto il suo di controllo: il primo utile e' fra un
  // minuto, non subito.
  let last = Date.now();
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    const now = Date.now();
    if (now - last < UPDATE_CHECK_MIN_MS) return;
    last = now;
    // Offline, o server irraggiungibile: non c'e' niente da dire e niente da
    // fare. Senza il `catch` e' una promessa rifiutata a ogni risalita dalla
    // metropolitana, cioe' rumore in console per una cosa che va come deve.
    void reg.update().catch(() => {});
  });
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
    checkForUpdatesOnFocus(reg);
    return reg;
  } catch (err) {
    // A failed registration must never take the app down with it: without a
    // service worker this is simply the website it has always been.
    console.warn('Service worker non registrato:', err);
    return null;
  }
}
