// Shared presentation helpers for the repair market, used by the manager-facing
// Mercato page and the admin Mercato panel in Gestione lega.
import type { MarketRecoveryMode } from '../types/market';

export const ROLE_LABEL: Record<string, string> = {
  POR: 'Portieri', DIF: 'Difensori', CEN: 'Centrocampisti', ATT: 'Attaccanti',
};
export const ROLE_ORDER = ['POR', 'DIF', 'CEN', 'ATT'];

const RECOVERY_LABEL: Record<MarketRecoveryMode, string> = {
  fixed: 'credito fisso',
  frac30: '30% del prezzo pagato',
  frac50: '50% del prezzo pagato',
  frac75: '75% del prezzo pagato',
};

export function recoveryText(mode: MarketRecoveryMode, fixed: number): string {
  return mode === 'fixed' ? `${fixed} credito${fixed === 1 ? '' : 'i'} fisso` : RECOVERY_LABEL[mode];
}

// Sempre fino ai secondi: il tick e' di 1s, e senza il campo che scorre un
// countdown fermo su "3h 12m" per un minuto intero sembra un dato vecchio.
// Minuti e secondi sono a due cifre quando li precede un'unita' piu' grande,
// cosi' la stringa non cambia larghezza a ogni tick.
const pad = (n: number) => String(n).padStart(2, '0');

export function countdown(deadlineIso: string | null, nowMs: number): string {
  if (!deadlineIso) return '—';
  const ms = new Date(deadlineIso).getTime() - nowMs;
  if (ms <= 0) return 'in validazione';
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  if (h > 0) return `${h}h ${pad(m)}m ${pad(s)}s`;
  if (m > 0) return `${m}m ${pad(s)}s`;
  return `${s}s`;
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
  accepted: 'accettata',
  settled: 'conclusa',
  outbid: 'superata',
  rejected: 'rifiutata',
  cancelled: 'annullata',
};

export const SESSION_TONE: Record<string, 'green' | 'amber' | 'slate'> = {
  open: 'green', suspended: 'amber', closed: 'slate',
};
export const SESSION_LABEL: Record<string, string> = {
  open: 'aperta', suspended: 'sospesa', closed: 'chiusa',
};
