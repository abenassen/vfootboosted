import { useEffect, useState } from 'react';
import { getLeagueDecisions } from '../api';

/** How many decisions this league is waiting on, for the sidebar badge.
 *
 * Two numbers, because they mean different things to different people: an open
 * CONSULTATION is a question addressed to you, while a BLOCKING decision is the
 * reason the market will not open. A member sees only the first (the API already
 * hides the admin's backlog from him), so one badge serves both without telling
 * anyone about work that is not theirs.
 *
 * It used to be fetched once per league, on the grounds that decisions only change
 * when someone acts and the acting pages reload it themselves. That stopped being
 * true when the Transfermarkt import began opening decisions on its own and
 * pushing a notification about them: a count that disagrees with the notification
 * that sent you there is worse than no count. Web Push and the running app are
 * separate channels, so the badge is brought back into line from three directions,
 * cheapest first:
 *
 *  * the service worker forwards every push to open windows (see `sw.ts`) — the
 *    same event that raised the notification, so the two cannot drift;
 *  * a re-read whenever the tab becomes visible again, which covers a push that
 *    arrived while the app sat in the background;
 *  * a slow poll, so a tab left open for a day is not still showing yesterday.
 *
 * Tapping the notification needs none of them: `notificationclick` NAVIGATES the
 * client, so the app remounts and reads everything fresh.
 */
const POLL_MS = 5 * 60 * 1000;

/** Server-side tag prefix for the "new roles to decide" push (league_decisions). */
const DECISION_TAG = 'decisions-';
/** E quello della consultazione aperta ai partecipanti (league_notifications). */
const CONSULTATION_TAG = 'consultations-';

/** Toglie dalla tendina le notifiche di questa lega quando non resta niente da fare.
 *
 *  È l'altra metà di quello che fa il service worker prima di mostrarne una: là si
 *  tratta di non APRIRE una richiesta già evasa altrove, qui di chiudere quella che
 *  era già a schermo nel momento in cui l'hanno evasa. Sono due casi diversi e
 *  succedono entrambi — chi risponde dal telefono non fa arrivare nessuna push al
 *  computer acceso di là, e la notifica di stamattina resta lì, buona, finché non
 *  la si scaccia a mano.
 *
 *  Silenziosa in ogni suo fallimento: è pulizia, e nessuno deve accorgersi se non
 *  riesce.
 */
async function pulisciTendina(leagueId: number): Promise<void> {
  try {
    const reg = await navigator.serviceWorker?.getRegistration();
    if (!reg) return;
    for (const tag of [`${DECISION_TAG}${leagueId}`, `${CONSULTATION_TAG}${leagueId}`]) {
      for (const n of await reg.getNotifications({ tag })) n.close();
    }
  } catch {
    /* worker assente, permesso mai dato: non c'è niente da pulire */
  }
}

/** Evento di finestra emesso dalla pagina Decisioni quando la coda cambia per
 * mano dell'utente. I tre canali qui sopra guardano tutti FUORI dall'app — una
 * push, un ritorno in primo piano, l'orologio — e nessuno si accorgeva della
 * cosa piu' ovvia: che a decidere fosse stato chi sta guardando il badge. */
export const DECISIONS_CHANGED = 'vfoot:decisions-changed';

const EMPTY = { attention: 0, blocking: 0, isAdmin: false };

export function useDecisionAlerts(leagueId: number | null) {
  const [alerts, setAlerts] = useState(EMPTY);

  useEffect(() => {
    if (leagueId == null) {
      setAlerts(EMPTY);
      return;
    }
    let cancelled = false;

    const read = async () => {
      try {
        const r = await getLeagueDecisions(leagueId);
        if (cancelled) return;
        setAlerts({ attention: r.attention, blocking: r.blocking_open, isAdmin: r.is_admin });
        if (r.attention === 0 && r.blocking_open === 0) void pulisciTendina(leagueId);
      } catch {
        // A badge is not worth an error message: if we cannot count, show nothing.
        if (!cancelled) setAlerts(EMPTY);
      }
    };

    void read();

    const onMessage = (e: MessageEvent) => {
      const tag = (e.data as { type?: string; tag?: string } | null)?.tag;
      // This league's decisions only: another league's push, or a goal, has
      // nothing to say about this number. Le due che ce l'hanno sono la coda
      // dell'amministratore e la consultazione aperta a tutti: il badge le conta
      // entrambe, quindi entrambe lo rimettono in pari.
      if (
        tag === `${DECISION_TAG}${leagueId}` ||
        tag === `${CONSULTATION_TAG}${leagueId}`
      )
        void read();
    };
    navigator.serviceWorker?.addEventListener('message', onMessage);

    const onVisible = () => {
      if (!document.hidden) void read();
    };
    document.addEventListener('visibilitychange', onVisible);

    const onLocalChange = (e: Event) => {
      const id = (e as CustomEvent<{ leagueId: number | null }>).detail?.leagueId;
      if (id == null || id === leagueId) void read();
    };
    window.addEventListener(DECISIONS_CHANGED, onLocalChange);

    const poll = window.setInterval(() => {
      if (!document.hidden) void read();
    }, POLL_MS);

    return () => {
      cancelled = true;
      navigator.serviceWorker?.removeEventListener('message', onMessage);
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener(DECISIONS_CHANGED, onLocalChange);
      window.clearInterval(poll);
    };
  }, [leagueId]);

  return alerts;
}
