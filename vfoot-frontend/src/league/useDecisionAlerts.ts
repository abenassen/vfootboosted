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
 * Fetched once per league, not polled: this changes when someone acts, and the
 * pages that act reload it themselves.
 */
export function useDecisionAlerts(leagueId: number | null) {
  const [alerts, setAlerts] = useState({ attention: 0, blocking: 0 });

  useEffect(() => {
    if (leagueId == null) {
      setAlerts({ attention: 0, blocking: 0 });
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const r = await getLeagueDecisions(leagueId);
        if (!cancelled) setAlerts({ attention: r.attention, blocking: r.blocking_open });
      } catch {
        // A badge is not worth an error message: if we cannot count, show nothing.
        if (!cancelled) setAlerts({ attention: 0, blocking: 0 });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [leagueId]);

  return alerts;
}
