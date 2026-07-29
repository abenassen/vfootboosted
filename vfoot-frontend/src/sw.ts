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
import { cleanupOutdatedCaches, precacheAndRoute } from 'workbox-precaching';

declare const self: ServiceWorkerGlobalScope & {
  __WB_MANIFEST: Array<{ url: string; revision: string | null }>;
};

precacheAndRoute(self.__WB_MANIFEST || []);
cleanupOutdatedCaches();

// The page asks for this once the user has accepted the update prompt. Without
// it a new deploy sits in "waiting" until every tab closes — which on a phone
// kept open never happens, so people stay on the old version for days.
self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') void self.skipWaiting();
});

type PushPayload = { title?: string; body?: string; url?: string; tag?: string };

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
    self.registration.showNotification(data.title || 'Vfoot Boosted', {
      body: data.body || '',
      icon: '/icons/icon-192.png',
      badge: '/icons/maskable-192.png',
      // Same tag => the new notification REPLACES the old one instead of
      // stacking. Keyed per subject by the server (decision-<id>), so three
      // updates about one decision stay one line in the shade.
      tag: data.tag || 'vfoot',
      data: { url: data.url || '/home' },
    }),
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
