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
  error: string | null;
};

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

export function usePush() {
  const [state, setState] = useState<PushState>({
    available: false,
    subscribed: false,
    blocked: null,
    busy: true,
    error: null,
  });

  const refresh = useCallback(async () => {
    const blocked = pushBlockedReason();
    try {
      const cfg = await getPushConfig();
      let subscribed = false;
      if (cfg.enabled && supportsPush() && !blocked) {
        const reg = await navigator.serviceWorker.ready;
        subscribed = (await reg.pushManager.getSubscription()) !== null;
      }
      setState({ available: cfg.enabled, subscribed, blocked, busy: false, error: null });
    } catch {
      setState({ available: false, subscribed: false, blocked, busy: false, error: null });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const enable = useCallback(async () => {
    setState((s) => ({ ...s, busy: true, error: null }));
    try {
      const cfg = await getPushConfig();
      if (!cfg.enabled || !cfg.public_key) throw new Error('Notifiche non configurate sul server.');

      // Must come from the user's click: browsers reject a permission request
      // that is not tied to a gesture, and a denial is permanent.
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        setState((s) => ({
          ...s,
          busy: false,
          error:
            permission === 'denied'
              ? 'Notifiche negate. Per riattivarle serve passare dalle impostazioni del browser.'
              : 'Permesso non concesso.',
        }));
        return;
      }

      const reg = await navigator.serviceWorker.ready;
      const sub =
        (await reg.pushManager.getSubscription()) ??
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
      const reg = await navigator.serviceWorker.ready;
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
