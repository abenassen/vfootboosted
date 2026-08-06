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
        if (!cancelled)
          setAlerts({ attention: r.attention, blocking: r.blocking_open, isAdmin: r.is_admin });
      } catch {
        // A badge is not worth an error message: if we cannot count, show nothing.
        if (!cancelled) setAlerts(EMPTY);
      }
    };

    void read();

    const onMessage = (e: MessageEvent) => {
      const tag = (e.data as { type?: string; tag?: string } | null)?.tag;
      // This league's decisions only: another league's push, or a goal, has
      // nothing to say about this number.
      if (typeof tag === 'string' && tag === `${DECISION_TAG}${leagueId}`) void read();
    };
    navigator.serviceWorker?.addEventListener('message', onMessage);

    const onVisible = () => {
      if (!document.hidden) void read();
    };
    document.addEventListener('visibilitychange', onVisible);

    const poll = window.setInterval(() => {
      if (!document.hidden) void read();
    }, POLL_MS);

    return () => {
      cancelled = true;
      navigator.serviceWorker?.removeEventListener('message', onMessage);
      document.removeEventListener('visibilitychange', onVisible);
      window.clearInterval(poll);
    };
  }, [leagueId]);

  return alerts;
}
