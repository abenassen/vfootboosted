// Quanto manca a un'offerta in testa. Non e' sempre il suo timer di 24h: se il
// mercato chiude prima, e' la chiusura a decidere il suo destino, ed e' quella
// la cifra che conta per chi sta pensando di rilanciare.
import { countdown, effectiveDeadline } from '../utils/market';

export function OfferDeadline({
  deadlineAt, sessionClosesAt, nowMs,
}: {
  deadlineAt: string | null;
  sessionClosesAt: string | null | undefined;
  nowMs: number;
}) {
  const { iso, cappedBySession } = effectiveDeadline(deadlineAt, sessionClosesAt ?? null);
  const text = countdown(iso, nowMs);

  if (!cappedBySession) return <>scade tra <span className="tabular-nums">{text}</span></>;

  // Un'offerta che alla chiusura non ha compiuto le sue 24h viene annullata,
  // non accettata: dirlo qui evita di scoprirlo a mercato chiuso.
  return (
    <span className="text-amber-600"
      title="Il mercato chiude prima che l’offerta compia 24 ore: se non le compie, viene annullata.">
      mercato chiuso tra <span className="tabular-nums">{text}</span>
    </span>
  );
}
