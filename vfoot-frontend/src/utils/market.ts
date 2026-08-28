// Shared presentation helpers for the repair market, used by the manager-facing
// Mercato page and the admin Mercato panel in Gestione lega.
import type {
  MarketRecoveryMode, MarketSessionInfo, MarketSessionPhase,
} from '../types/market';
import { amount } from './currency';

export const ROLE_LABEL: Record<string, string> = {
  POR: 'Portieri', DIF: 'Difensori', CEN: 'Centrocampisti', ATT: 'Attaccanti',
};
export const ROLE_ORDER = ['POR', 'DIF', 'CEN', 'ATT'];

const RECOVERY_LABEL: Record<MarketRecoveryMode, string> = {
  fixed: 'cifra fissa',
  frac30: '30% del prezzo pagato',
  frac50: '50% del prezzo pagato',
  frac75: '75% del prezzo pagato',
};

export function recoveryText(mode: MarketRecoveryMode, fixed: number): string {
  // «1 vfooty fissi» era una stonatura in una riga che si legge come una frase.
  return mode === 'fixed'
    ? `${amount(fixed)} fiss${fixed === 1 ? 'o' : 'i'}`
    : RECOVERY_LABEL[mode];
}

// Sempre fino ai secondi: il tick e' di 1s, e senza il campo che scorre un
// countdown fermo su "3h 12m" per un minuto intero sembra un dato vecchio.
// Minuti e secondi sono a due cifre quando li precede un'unita' piu' grande,
// cosi' la stringa non cambia larghezza a ogni tick.
const pad = (n: number) => String(n).padStart(2, '0');

function spread(ms: number): string {
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  // Oltre le due giornate le ore non si contano piu' a mente ("52h" non dice
  // quando). Sotto, restano il modo piu' diretto di dirlo. Riguarda solo
  // l'attesa dell'apertura: nessun timer di offerta supera le 24h.
  if (h >= 48) return `${Math.floor(h / 24)}g ${pad(h % 24)}h ${pad(m)}m`;
  if (h > 0) return `${h}h ${pad(m)}m ${pad(s)}s`;
  if (m > 0) return `${m}m ${pad(s)}s`;
  return `${s}s`;
}

export function countdown(
  deadlineIso: string | null, nowMs: number, elapsed = 'in validazione',
): string {
  if (!deadlineIso) return '—';
  const ms = new Date(deadlineIso).getTime() - nowMs;
  if (ms <= 0) return elapsed;
  return spread(ms);
}

/** Da quanto e' passato un momento gia' passato — «6h 12m 03s».
 *
 *  Serve a raccontare un'offerta scaduta mentre un rilancio la teneva coperta:
 *  la sua scadenza da sola («ieri alle 14:20») non dice quanto sia vecchia, e
 *  quanto sia vecchia e' il punto. */
export function elapsedSince(iso: string | null, nowMs: number): string {
  if (!iso) return '—';
  return spread(Math.max(0, nowMs - new Date(iso).getTime()));
}

/** Quando si decide davvero il destino di un'offerta in testa: il suo timer di
 *  24h, oppure la chiusura programmata del mercato se arriva prima. Un mercato
 *  che chiude fra tre ore rende irrilevante un timer che ne ha ancora venti. */
export function effectiveDeadline(
  offerDeadline: string | null,
  sessionClosesAt: string | null,
): { iso: string | null; cappedBySession: boolean } {
  if (!sessionClosesAt) return { iso: offerDeadline, cappedBySession: false };
  if (!offerDeadline) return { iso: sessionClosesAt, cappedBySession: true };
  const capped = new Date(sessionClosesAt).getTime() < new Date(offerDeadline).getTime();
  return { iso: capped ? sessionClosesAt : offerDeadline, cappedBySession: capped };
}

export const OFFER_TONE: Record<string, 'green' | 'amber' | 'slate' | 'red' | 'blue'> = {
  leading: 'blue',
  accepted: 'amber',
  settled: 'green',
  outbid: 'slate',
  rejected: 'red',
  cancelled: 'slate',
};
export const OFFER_LABEL: Record<string, string> = {
  leading: 'in testa',
  // "accettata" suonava come una pratica chiusa, e invece e' il contrario: manca
  // ancora la decisione dell'admin, e finche' non arriva le rose non si muovono.
  accepted: 'in attesa di validazione',
  settled: 'conclusa',
  outbid: 'superata',
  rejected: 'rifiutata',
  cancelled: 'annullata',
};

export const SESSION_TONE: Record<string, 'green' | 'amber' | 'slate' | 'blue'> = {
  open: 'green', scheduled: 'blue', suspended: 'amber', closed: 'slate',
};
export const SESSION_LABEL: Record<string, string> = {
  open: 'aperta', scheduled: 'programmata', suspended: 'sospesa', closed: 'chiusa',
};

/** Lo stato che conta a schermo.
 *
 *  Una sessione `open` con l'ora di apertura ancora da venire non e' aperta: e'
 *  annunciata. Il server lo sa gia' (rifiuta le offerte prima del momento
 *  fissato), ma la pagina deve saperlo dire — e deve passare da se' ad "aperta"
 *  quando il conto alla rovescia arriva a zero, senza aspettare il prossimo giro
 *  di polling: l'orologio ce l'ha, ed e' quello del server. */
/** Giorno e ora in forma breve, «27 ago 2026, 16:13». Senza i secondi: nessuna
 *  data del mercato si decide al secondo, e `toLocaleString` da solo li mette
 *  («31/08/2026, 13:13:01», che si legge come un timestamp di log). */
export function stamp(iso: string | null | undefined): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleString('it-IT', {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export function sessionPhase(
  s: Pick<MarketSessionInfo, 'status' | 'opens_at'>, nowMs: number,
): MarketSessionPhase {
  if (s.status === 'open' && s.opens_at && new Date(s.opens_at).getTime() > nowMs) {
    return 'scheduled';
  }
  return s.status;
}
