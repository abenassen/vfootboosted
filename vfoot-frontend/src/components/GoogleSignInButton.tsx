import { useEffect, useRef, useState } from 'react';

/** Google's own button, rendered by Google's script.
 *
 *  We load the script only when a client id is configured, so an unconfigured
 *  build simply shows nothing rather than a button that cannot work. The script
 *  hands us an ID token; verifying it is the backend's job.
 */
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (opts: {
            client_id: string;
            callback: (res: { credential?: string }) => void;
          }) => void;
          renderButton: (el: HTMLElement, opts: Record<string, unknown>) => void;
        };
      };
    };
  }
}

const SRC = 'https://accounts.google.com/gsi/client';

function loadScript(): Promise<void> {
  const existing = document.querySelector<HTMLScriptElement>(`script[src="${SRC}"]`);
  if (existing) {
    return existing.dataset.loaded === 'true'
      ? Promise.resolve()
      : new Promise((resolve, reject) => {
          existing.addEventListener('load', () => resolve());
          existing.addEventListener('error', () => reject(new Error('load failed')));
        });
  }
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = SRC;
    s.async = true;
    s.defer = true;
    s.addEventListener('load', () => {
      s.dataset.loaded = 'true';
      resolve();
    });
    s.addEventListener('error', () => reject(new Error('load failed')));
    document.head.appendChild(s);
  });
}

export default function GoogleSignInButton({
  onCredential,
  text = 'signin_with',
}: {
  onCredential: (credential: string) => void;
  text?: 'signin_with' | 'signup_with';
}) {
  const clientId = (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined)?.trim();
  const holder = useRef<HTMLDivElement | null>(null);
  const [failed, setFailed] = useState(false);
  // Keep the latest callback without re-rendering Google's button on every
  // parent render, which would make it flicker.
  const cb = useRef(onCredential);
  cb.current = onCredential;

  useEffect(() => {
    if (!clientId || !holder.current) return;
    let cancelled = false;
    loadScript()
      .then(() => {
        if (cancelled || !holder.current || !window.google) return;
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: (res) => {
            if (res.credential) cb.current(res.credential);
          },
        });
        window.google.accounts.id.renderButton(holder.current, {
          theme: 'outline',
          size: 'large',
          width: 320,
          locale: 'it',
          text,
        });
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [clientId, text]);

  if (!clientId) return null;
  if (failed) {
    return (
      <div className="text-xs text-slate-500">
        Login con Google non disponibile al momento.
      </div>
    );
  }
  return <div ref={holder} className="flex justify-center" />;
}
