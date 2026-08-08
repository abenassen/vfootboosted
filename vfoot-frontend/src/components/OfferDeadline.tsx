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

  // La chiusura del mercato fa da scadenza: chi e' in testa in quel momento
  // passa in validazione, 24 ore compiute o no. Quindi non e' un avvertimento
  // ma il vero conto alla rovescia — l'ultimo istante utile per rilanciare.
  return (
    <span className="text-warn"
      title="Il mercato chiude prima delle 24 ore: chi è in testa alla chiusura passa in validazione.">
      il mercato chiude tra <span className="tabular-nums">{text}</span>
    </span>
  );
}
