import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { apiProvider } from '../api';
import { postUsageVisits } from '../api/backend';

/** Il registro delle pagine, lato client: misura per quanto ogni pagina resta
 *  DAVANTI a qualcuno e lo manda al server. Cosa conservare lo decide il server
 *  (acceso o spento, staff o no), vedi ``vfoot/models/usage.py``.
 *
 *  Un tratto comincia quando si apre una pagina o la scheda torna in primo piano,
 *  e finisce al cambio di pagina o quando la scheda va in secondo piano: lì si
 *  spedisce subito, perché da «nascosta» spesso non si torna più (il telefono
 *  chiude l'app, la scheda viene chiusa) e quel tratto andrebbe perso. */

type Visit = {
  route: string;
  visible_ms: number;
  device: 'mobile' | 'desktop';
  standalone: boolean;
  session: string;
};

// Sotto questa soglia non è una pagina vista: è un rimando (`/league` → `/home`)
// o un doppio tocco. Contarli riempirebbe le statistiche di pagine mai lette.
const MIN_VISIBLE_MS = 300;
const SESSION_KEY = 'vfoot.usage.session';

/** La pagina, non QUALE partita o squadra: via gli identificativi. Il codice
 *  d'invito è una credenziale e non deve uscire dal dispositivo in nessuna forma. */
export function normalizeRoute(pathname: string): string {
  if (pathname.startsWith('/join/')) return '/join/:code';
  const parts = pathname
    .toLowerCase()
    .split('/')
    .map((seg) => (/\d/.test(seg) ? ':id' : seg));
  const out = parts.join('/').replace(/\/+$/, '') || '/';
  return out.slice(0, 120);
}

function sessionId(): string {
  try {
    const known = window.sessionStorage.getItem(SESSION_KEY);
    if (known) return known;
  } catch {
    // archiviazione bloccata: una sessione per caricamento, va bene lo stesso
  }
  const fresh = Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) =>
    (b % 36).toString(36),
  ).join('') + Date.now().toString(36).slice(-4);
  try {
    window.sessionStorage.setItem(SESSION_KEY, fresh);
  } catch {
    // come sopra
  }
  return fresh;
}

function device(): Visit['device'] {
  return window.matchMedia?.('(pointer: coarse)').matches ? 'mobile' : 'desktop';
}

function standalone(): boolean {
  return Boolean(window.matchMedia?.('(display-mode: standalone)').matches);
}

export function usePageTracking(): void {
  const { pathname } = useLocation();

  useEffect(() => {
    if (apiProvider !== 'backend' || typeof document === 'undefined') return;
    const route = normalizeRoute(pathname);
    const session = sessionId();
    let since: number | null = document.visibilityState === 'visible' ? performance.now() : null;

    const close = () => {
      if (since === null) return;
      const ms = Math.round(performance.now() - since);
      since = null;
      if (ms < MIN_VISIBLE_MS) return;
      postUsageVisits([{ route, visible_ms: ms, device: device(), standalone: standalone(), session }]);
    };
    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        if (since === null) since = performance.now();
      } else {
        close();
      }
    };

    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', close);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', close);
      close();
    };
  }, [pathname]);
}
