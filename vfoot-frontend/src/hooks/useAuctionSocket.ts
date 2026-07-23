import { useEffect, useRef, useState } from 'react';
import { auctionSocketUrl } from '../api';

export type SocketStatus = 'connecting' | 'open' | 'closed';

/**
 * Live connection to an auction room. The server pushes a light `{type:"update"}`
 * nudge whenever anything changes; on every nudge (and on (re)connect) we call
 * `onUpdate`, which re-fetches the authoritative state over REST. Auto-reconnects
 * with a small backoff. When `auctionId` is null the hook stays idle.
 */
export function useAuctionSocket(auctionId: number | null, onUpdate: () => void): SocketStatus {
  const [status, setStatus] = useState<SocketStatus>('closed');
  // Keep the latest callback without re-opening the socket on every render.
  const cbRef = useRef(onUpdate);
  cbRef.current = onUpdate;

  useEffect(() => {
    if (!auctionId) {
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
        ws = new WebSocket(auctionSocketUrl(auctionId));
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
  }, [auctionId]);

  return status;
}
