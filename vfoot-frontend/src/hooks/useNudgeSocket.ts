import { useEffect, useRef, useState } from 'react';
import { auctionSocketUrl, liveSocketUrl } from '../api';

export type SocketStatus = 'connecting' | 'open' | 'closed';

/**
 * A read-only nudge socket. The server pushes a light `{type:"update"}` whenever
 * anything changes; on every nudge (and on (re)connect) we call `onUpdate`, which
 * re-fetches the authoritative state over REST. Auto-reconnects with a small
 * backoff. When `url` is null the hook stays idle.
 *
 * No state ever travels down the socket, deliberately: the REST endpoint is the
 * only place that knows how to compute what the page shows, so the socket path and
 * the plain-reload path cannot drift apart.
 */
export function useNudgeSocket(url: string | null, onUpdate: () => void): SocketStatus {
  const [status, setStatus] = useState<SocketStatus>('closed');
  // Keep the latest callback without re-opening the socket on every render.
  const cbRef = useRef(onUpdate);
  cbRef.current = onUpdate;

  useEffect(() => {
    if (!url) {
      setStatus('closed');
      return;
    }
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;
    let closedByUs = false;

    const connect = () => {
      setStatus('connecting');
      try {
        ws = new WebSocket(url);
      } catch {
        scheduleReconnect();
        return;
      }
      ws.onopen = () => {
        attempts = 0;
        setStatus('open');
      };
      ws.onmessage = () => cbRef.current();
      ws.onclose = () => {
        setStatus('closed');
        if (!closedByUs) scheduleReconnect();
      };
      ws.onerror = () => ws?.close();
    };

    const scheduleReconnect = () => {
      attempts += 1;
      const delay = Math.min(1000 * 2 ** attempts, 15000);
      retry = setTimeout(connect, delay);
    };

    connect();
    return () => {
      closedByUs = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, [url]);

  return status;
}

/** Live connection to an auction room. */
export function useAuctionSocket(auctionId: number | null, onUpdate: () => void): SocketStatus {
  return useNudgeSocket(auctionId ? auctionSocketUrl(auctionId) : null, onUpdate);
}

/**
 * Live connection to a league's matchday in progress. Every import of a match
 * being played nudges here, and the page re-reads its tabellini.
 */
export function useLiveSocket(leagueId: number | null, onUpdate: () => void): SocketStatus {
  return useNudgeSocket(leagueId ? liveSocketUrl(leagueId) : null, onUpdate);
}
