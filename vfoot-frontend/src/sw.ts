/// <reference lib="webworker" />
/** The service worker: offline shell, and the only place a push can be received.
 *
 *  It runs on its own thread with no DOM, and the browser starts it from cold to
 *  deliver a push — which is why everything here is self-contained and why the
 *  notification must be shown from inside `event.waitUntil`: return before the
 *  promise settles and the worker is killed mid-notification.
 *
 *  Deliberately NOT cached: anything under /api/. See vite.config.ts.
 */
import {
  cleanupOutdatedCaches,
  createHandlerBoundToURL,
  precacheAndRoute,
} from 'workbox-precaching';
import { NavigationRoute, registerRoute } from 'workbox-routing';

declare const self: ServiceWorkerGlobalScope & {
  __WB_MANIFEST: Array<{ url: string; revision: string | null }>;
};

// Injected by the build — and EMPTY under `npm run dev`, where Vite serves every
// file fresh and there is nothing to precache. That difference is what makes the
// offline route below conditional.
const manifest = self.__WB_MANIFEST || [];

precacheAndRoute(manifest);
cleanupOutdatedCaches();

// Every client-side route has to resolve to the one shell we precached.
// Without this the precache only answers for the exact URLs in it: `/` worked
// and `/home` — the manifest's start_url, i.e. what the INSTALLED APP OPENS —
// died on the browser's offline page. Measured before adding this.
//
// Only when there IS a precache, and the `if` is not defensive tidiness:
// `createHandlerBoundToURL` THROWS ('non-precached-url') when handed a URL that
// was not precached, which is exactly the dev case. A throw HERE is not a feature
// quietly missing — it happens while the worker is still evaluating, so the browser
// discards the WHOLE script, `push` and `notificationclick` included. That is how
// `npm run dev` ended up with no worker at all and no notification able to arrive,
// while the app blamed the server for having no VAPID keys. In dev the shell comes
// from the dev server anyway: an offline fallback for a server that is always there
// is the one thing we lose, and we lose nothing.
if (manifest.length) {
  registerRoute(
    new NavigationRoute(createHandlerBoundToURL('/index.html'), {
      // A navigation to these must reach the server, not be answered with the SPA:
      // /api and /ws are the backend, /admin is Django's own UI, /static its assets.
      // (Fetches from the app carry mode:"cors" and never match a NavigationRoute
      // anyway — this is about someone typing the URL or following a link.)
      //
      // mobile-frame.html is a real FILE in public/, not a client route, so answering
      // it with the shell gets the app's own 404 — and only on localhost, where the
      // worker is registered, which makes it look like the preview tool is broken on
      // one machine and fine on another. pwa-check.html is the same kind of file, and
      // failing that way would be worse: it is the page you open precisely when you
      // suspect the worker, so the worker eating it would answer the question wrong.
      //
      // /benchmark-voto/ è lo stesso caso ma di un'altra natura: non un file in
      // public/, una CARTELLA che serve nginx da fuori l'app (40 pagine statiche in
      // /srv/vfoot-benchmark, il confronto dei nostri voti con quelli di
      // fantacalcio.it, che si dà per link diretto a chi chiede conto di un voto).
      // Il 12/08/2026 quel link ha risposto il 404 DELL'APP a chi lo apriva, e non
      // serve avere la PWA installata per finirci: il worker si registra alla prima
      // visita normale, quindi riguarda chiunque abbia aperto il sito una volta.
      // L'indirizzo vive in due posti che devono restare d'accordo — qui e nella
      // location di vfoot.it.conf: se un giorno cambia, va cambiato in entrambi.
      // /admin e /admin/ entrambi: il worker risponde a una NAVIGAZIONE, cioe' a
      // un indirizzo digitato a mano, e a mano la barra finale non la scrive
      // nessuno. Senza il `$` quella navigazione la mangia il guscio dell'app.
      denylist: [/^\/api\//, /^\/admin(\/|$)/, /^\/ws\//, /^\/static\//, /^\/media\//,
                 /^\/benchmark-voto\//,
                 /^\/mobile-frame\.html/, /^\/pwa-check\.html/],
    }),
  );
}

// The page asks for this once the user has accepted the update prompt. Without
// it a new deploy sits in "waiting" until every tab closes — which on a phone
// kept open never happens, so people stay on the old version for days.
self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') void self.skipWaiting();
});

type PushPayload = {
  title?: string;
  body?: string;
  url?: string;
  tag?: string;
  /** Gettone firmato per chiedere al server se questa notifica ha ancora senso.
   *  Ce l'hanno solo quelle che CHIEDONO qualcosa — v. `ancoraDaFare`. */
  check?: string;
};

/** La stessa base che usa l'app (src/api/backend.ts): relativa in produzione,
 *  dove nginx fa da proxy, e su un'altra porta in sviluppo. Ripetuta qui invece
 *  che importata perché il worker è autonomo per costruzione — v. l'intestazione:
 *  quello che tira dentro se lo porta appresso in ogni risveglio a freddo. */
const API_BASE = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() ||
  'http://localhost:8000/api/v1'
).replace(/\/+$/, '');

/** Quanto si aspetta la risposta prima di mostrare comunque la notifica. Il
 *  browser tiene in vita il worker solo finché la promessa di `waitUntil` non si
 *  chiude, e una rete lenta non deve trasformare una notifica in un silenzio. */
const CHECK_TIMEOUT_MS = 3000;

/** C'è ancora qualcosa da fare, o qualcuno l'ha già fatto?
 *
 *  Una push non è un messaggio istantaneo: il servizio del dispositivo la tiene
 *  in coda e la consegna quando quel browser si ricollega. Chi decide un ruolo
 *  dal telefono e più tardi accende il computer se la ritrova lì identica, e
 *  cliccandola arriva su una pagina dove non c'è più niente da risolvere. Le due
 *  notifiche sono la stessa cosa mandata a due installazioni, e al momento della
 *  partenza erano entrambe giuste: l'unico posto in cui la domanda ha una
 *  risposta è qui, un istante prima di aprire la tendina.
 *
 *  In dubbio si mostra — timeout, rete assente, server che risponde storto, non
 *  autenticato in questo browser. Una notifica di troppo è una seccatura, una
 *  notifica in meno è un mercato fermo di cui nessuno viene avvisato.
 */
async function ancoraDaFare(check: string): Promise<boolean> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), CHECK_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE}/push/relevance?t=${encodeURIComponent(check)}`, {
      signal: ctrl.signal,
      cache: 'no-store',
    });
    if (!res.ok) return true;
    return ((await res.json()) as { stale?: boolean }).stale !== true;
  } catch {
    return true;
  } finally {
    clearTimeout(timer);
  }
}

self.addEventListener('push', (event) => {
  let data: PushPayload = {};
  try {
    data = event.data ? (event.data.json() as PushPayload) : {};
  } catch {
    // A push with a body we cannot parse still deserves to be shown: on iOS a
    // subscription with `userVisibleOnly` that shows nothing gets penalised.
    data = { title: 'Vfoot Boosted', body: event.data?.text() ?? '' };
  }
  event.waitUntil(
    (async () => {
      // Same tag => the new notification REPLACES the old one instead of
      // stacking. Keyed per subject by the server (decision-<id>), so three
      // updates about one decision stay one line in the shade.
      const tag = data.tag || 'vfoot';
      if (!data.check || (await ancoraDaFare(data.check))) {
        await self.registration.showNotification(data.title || 'Vfoot Boosted', {
          body: data.body || '',
          icon: '/icons/icon-192.png',
          // NON un'icona qualsiasi, e nemmeno una delle altre: quella piccola in
          // cima allo schermo Android la disegna da sé, prendendo del file solo
          // il CANALE ALFA e riempiendo di bianco tutto ciò che è opaco. Qui
          // c'era la maskable, che per definizione è piena fino ai bordi — e
          // infatti nella barra di stato compariva un quadrato bianco anonimo
          // accanto alle altre app (segnalato il 20/08/2026). badge-96 è lo
          // scudo del logo ritagliato in silhouette, sfondo trasparente, senza
          // la scritta: a 24dp una parola non si legge comunque.
          badge: '/icons/badge-96.png',
          tag,
          data: { url: data.url || '/home' },
        });
      } else {
        // Già risolto altrove. Niente da mostrare — e se questo dispositivo ne
        // aveva ancora una vecchia in tendina, se ne va con l'occasione.
        //
        // Il patto di `userVisibleOnly` dice che ogni push produce qualcosa di
        // visibile, e non mostrare niente attinge al credito che il browser
        // concede ai siti frequentati; esaurito quello, mostra lui un generico
        // «il sito è stato aggiornato in background». È il prezzo accettato
        // consapevolmente: si arriva qui solo quando la richiesta è già evasa,
        // cioè di rado, e l'alternativa è mandare la persona su una pagina vuota.
        for (const n of await self.registration.getNotifications({ tag })) n.close();
      }
      // ...and tell any window that is already open, so the app and the shade do
      // not disagree. Web Push and the running SPA are two separate channels: a
      // notification saying "3 roles to decide" beside a badge still reading zero
      // is worse than no badge at all. Tapping the notification is already
      // consistent (notificationclick NAVIGATES the client, remounting the app);
      // this covers the case where the reader simply switches to a tab that was
      // open all along. The message carries no state — only "something about
      // <tag> moved" — so whoever listens re-reads over REST, same as everywhere.
      // Anche quando non si è mostrato niente: che la coda si sia svuotata è una
      // notizia esattamente come che si sia riempita.
      const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const client of clients) {
        client.postMessage({ type: 'push', tag });
      }
    })(),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data?.url as string) || '/home';
  event.waitUntil(
    (async () => {
      const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      // Focus a window we already have and navigate it, rather than opening a
      // second copy of the app on top of the first.
      for (const client of all) {
        if ('focus' in client) {
          await client.focus();
          if ('navigate' in client) await client.navigate(target);
          return;
        }
      }
      await self.clients.openWindow(target);
    })(),
  );
});
