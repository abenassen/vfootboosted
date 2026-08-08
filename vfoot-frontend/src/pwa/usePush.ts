import { useCallback, useEffect, useState } from 'react';
import { getPushConfig, subscribePush, unsubscribePush } from '../api';
import { pushBlockedReason, supportsPush } from './install';

/** Subscribing this installation to push, and knowing where we stand.
 *
 *  One rule drives the shape: the permission is asked ONCE. If the user says no,
 *  the browser will not let us ask again — the only way back is the site settings,
 *  which nobody finds. So the request must never fire on page load; it fires when
 *  someone presses a button that says what it is for.
 */

export type PushState = {
  /** Server-side: are the VAPID keys configured at all? */
  available: boolean;
  /** This installation is subscribed and will receive notifications. */
  subscribed: boolean;
  /** Why we cannot offer it here (iOS in the browser, permission denied, …). */
  blocked: string | null;
  busy: boolean;
  /** Has the first look settled? Until it has, every other field is a GUESS, and
   *  the initial guess is the gloomiest one there is — so anything that puts a
   *  reason on screen has to wait for this. */
  loaded: boolean;
  error: string | null;
};

/** How long to wait for the service worker before calling it absent.
 *
 *  `navigator.serviceWorker.ready` is a promise that only ever RESOLVES: when the
 *  worker fails to install there is no rejection and no timeout, it simply stays
 *  pending for the life of the page. That is not hypothetical — a throw at the top
 *  of sw.ts left this hook waiting for ever, so the state never moved off its
 *  initial values and the profile page announced that the SERVER had no keys, with
 *  the keys sitting in the config it had just fetched. A silence has to be turned
 *  into an answer before anything can be reported about it.
 *
 *  Generous on purpose: on a first visit the registration is still in flight (we
 *  register after the first render), and a worker that arrives late is normal.
 */
const READY_TIMEOUT_MS = 6000;

const NO_WORKER =
  'Le notifiche non sono disponibili in questa copia dell\'app: il componente che le '
  + 'riceve non si è avviato. Prova a ricaricare la pagina; se il messaggio resta, '
  + 'è un problema nostro, non tuo.';

async function readyRegistration(): Promise<ServiceWorkerRegistration | null> {
  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise<null>((resolve) => {
      setTimeout(() => resolve(null), READY_TIMEOUT_MS);
    }),
  ]);
}

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  // The VAPID public key travels as base64url without padding; the browser wants
  // raw bytes — and specifically over a plain ArrayBuffer, which is why the view
  // is built on one explicitly rather than via Uint8Array.from.
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=');
  const raw = atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

/** Was this subscription created with the key the server signs with TODAY?
 *
 *  The browser binds a subscription to the `applicationServerKey` it was handed at
 *  subscribe time, for good. Change the server's VAPID pair — a redeploy with a new
 *  secret, a dev machine whose keys differ from production's — and every existing
 *  subscription starts answering 403: the install is alive, the push simply cannot
 *  be signed for it any more. Nothing on either side announces this, so the profile
 *  page went on reporting "attive" for notifications that could never arrive.
 *
 *  When the browser will not tell us which key it used (no `options`), we say YES
 *  rather than re-subscribing on every load: a wrong guess here costs a permission
 *  round-trip on every visit, and the server side already gives up on a subscription
 *  that 403s three times. */
function keyMatches(sub: PushSubscription, publicKey: string): boolean {
  const current = sub.options?.applicationServerKey;
  if (!current) return true;
  const mine = new Uint8Array(current);
  const theirs = urlBase64ToUint8Array(publicKey);
  return mine.length === theirs.length && mine.every((b, i) => b === theirs[i]);
}

export function usePush() {
  const [state, setState] = useState<PushState>({
    available: false,
    subscribed: false,
    blocked: null,
    busy: true,
    loaded: false,
    error: null,
  });

  const refresh = useCallback(async () => {
    let blocked = pushBlockedReason();
    try {
      const cfg = await getPushConfig();
      let subscribed = false;
      if (cfg.enabled && supportsPush() && !blocked) {
        const reg = await readyRegistration();
        if (!reg) {
          // Three situations used to arrive here as one sentence about the server,
          // and they have three different remedies: the admin generates keys, a
          // developer fixes the worker, and the third one — "still looking" — needs
          // nobody. Naming this one as OURS is the difference between a reader who
          // reloads and a reader who goes hunting for a key that was already there.
          blocked = NO_WORKER;
        } else {
          const sub = await reg.pushManager.getSubscription();
          // A subscription signed for a key we no longer hold is not a subscription:
          // reporting it as one is how the profile page came to promise notifications
          // that the push service was rejecting. Saying "not subscribed" puts the
          // Attiva button back, and pressing it repairs the whole thing — with no
          // permission prompt, since that was granted long ago.
          subscribed = sub !== null && keyMatches(sub, cfg.public_key ?? '');
        }
      }
      setState({ available: cfg.enabled, subscribed, blocked, busy: false, loaded: true,
                 error: null });
    } catch {
      setState({ available: false, subscribed: false, blocked, busy: false, loaded: true,
                 error: null });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const enable = useCallback(async () => {
    setState((s) => ({ ...s, busy: true, error: null }));
    try {
      // FIRST, and before any await that goes to the network. The permission
      // request has to run inside the click's transient activation, and a fetch —
      // even a fast one — outlives it: Chrome then treats the call as
      // unsolicited, resolves it with 'default' and SHOWS NOTHING AT ALL. No
      // bubble, no crossed-out bell in the omnibox, nothing to click. From the
      // outside it looks exactly like the browser refusing, and the app dutifully
      // reported "permesso non concesso" for a prompt that was never put on
      // screen. (The previous version fetched the config first; on a fast
      // localhost it sometimes squeaked through, which is the worst kind of bug.)
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        setState((s) => ({
          ...s,
          busy: false,
          // 'denied' and 'default' are two different situations with two
          // different ways out, and saying "permesso non concesso" for both sent
          // people looking for a window that was never shown. Chrome suppresses
          // the prompt when it is in quiet mode and puts a small CROSSED-OUT BELL
          // in the address bar instead — findable only if you know it is there.
          // So the message says where to look.
          error:
            permission === 'denied'
              ? 'Notifiche negate. Per riattivarle serve passare dalle impostazioni del browser.'
              : "Il browser non ha mostrato la richiesta. Cerca l'icona della campanella "
                + 'sbarrata nella barra degli indirizzi, in alto a destra: cliccala e '
                + 'scegli di consentire le notifiche.',
        }));
        return;
      }

      // Now the gesture has done its job and we can go to the network. The button
      // is only offered when `available` is true, so the keys are already known to
      // be there — this reads the public one, it does not decide anything.
      const cfg = await getPushConfig();
      if (!cfg.enabled || !cfg.public_key) throw new Error('Notifiche non configurate sul server.');

      // Same guarded wait as in `refresh`: without it a missing worker turned the
      // press of a button into a spinner that never came back.
      const reg = await readyRegistration();
      if (!reg) throw new Error(NO_WORKER);
      let existing = await reg.pushManager.getSubscription();
      if (existing && !keyMatches(existing, cfg.public_key)) {
        // Reusing it would re-save an endpoint that answers 403 for ever, and the
        // browser refuses to re-subscribe with a different key while this one
        // lives. Our server is told first, for the same reason `disable` does:
        // an endpoint dropped here and kept there is one we would push into the
        // void.
        await unsubscribePush(existing.endpoint).catch(() => {});
        await existing.unsubscribe();
        existing = null;
      }
      const sub =
        existing ??
        (await reg.pushManager.subscribe({
          // Required: we promise every push results in something visible. Silent
          // pushes are not allowed on the web, and iOS revokes for it.
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(cfg.public_key),
        }));
      await subscribePush(sub.toJSON() as { endpoint: string; keys: Record<string, string> });
      setState((s) => ({ ...s, subscribed: true, busy: false, error: null }));
    } catch (e) {
      setState((s) => ({
        ...s,
        busy: false,
        error: e instanceof Error ? e.message : 'Attivazione non riuscita.',
      }));
    }
  }, []);

  const disable = useCallback(async () => {
    setState((s) => ({ ...s, busy: true, error: null }));
    try {
      const reg = await readyRegistration();
      if (!reg) throw new Error(NO_WORKER);
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        // Tell our server FIRST: if the browser-side unsubscribe succeeded and
        // the call failed, we would keep pushing to an endpoint that is gone.
        await unsubscribePush(sub.endpoint);
        await sub.unsubscribe();
      }
      setState((s) => ({ ...s, subscribed: false, busy: false, error: null }));
    } catch (e) {
      setState((s) => ({
        ...s,
        busy: false,
        error: e instanceof Error ? e.message : 'Disattivazione non riuscita.',
      }));
    }
  }, []);

  return { ...state, enable, disable, refresh };
}
