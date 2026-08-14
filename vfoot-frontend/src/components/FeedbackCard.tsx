import { useState } from 'react';
import clsx from 'clsx';
import { Card } from './ui';
import { ApiError, sendFeedback, type FeedbackKind } from '../api/backend';

/** LO SPAZIO PER DIRCI CHE QUALCOSA NON VA.
 *
 *  Il sito è in prova, e chi lo prova vede cose che noi non vediamo — ma finora
 *  per raccontarcele doveva conoscerci e scriverci a mano, cioè poteva farlo solo
 *  chi già ci conosce. Qui la stessa cosa costa una frase.
 *
 *  Aperto, non da aprire. Un pulsante «Segnala un problema» che apre un pannello
 *  costa un tocco in più proprio nel momento in cui l'utente sta già facendo
 *  un'altra cosa, ed è il tocco su cui la maggior parte delle segnalazioni si
 *  perde. Costa una scheda bassa in fondo alla home: è il posto giusto, perché
 *  non è il motivo per cui si apre l'app, ma è dove si torna sempre.
 *
 *  Tre pastiglie e nient'altro da compilare. Pagina, schermo e browser li
 *  raccogliamo da soli (v. sendFeedback): sono i tre dati che servono a
 *  riprodurre un problema e i tre che nessuno pensa a scrivere.
 *
 *  Il grazie resta a schermo finché non si scrive dell'altro: una segnalazione
 *  mandata e sparita nel nulla insegna a non mandarne più.
 */

const KINDS: Array<{ id: FeedbackKind; label: string }> = [
  { id: 'bug', label: 'Non funziona' },
  { id: 'idea', label: 'Proposta' },
  { id: 'altro', label: 'Altro' },
];

export default function FeedbackCard() {
  const [kind, setKind] = useState<FeedbackKind>('bug');
  const [text, setText] = useState('');
  const [pending, setPending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    const message = text.trim();
    if (message.length < 3 || pending) return;
    setPending(true);
    setError(null);
    try {
      await sendFeedback(kind, message);
      setText('');
      setSent(true);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof TypeError
            ? 'Non riesco a raggiungere il server. Riprova tra poco.'
            : 'Invio non riuscito.',
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <Card className="p-4">
      {/* IL TITOLO NOMINA LA COSA, non la chiede. «Com'è andata?» — che è quello
          che c'era scritto — in un sito di fantacalcio non si legge come una
          domanda sul sito: si legge come una domanda sulla GIORNATA, in fondo
          alla pagina che parla appunto della giornata. E una domanda a cui si
          risponde «bene» non fa venire in mente di segnalare un pulsante rotto. */}
      <div className="flex items-baseline gap-2">
        <span aria-hidden>💬</span>
        <h2 className="font-cond text-lg font-bold text-ink">Segnalazioni e idee</h2>
      </div>
      <p className="mt-0.5 text-xs text-ink-faint">
        Il sito è in prova: se qualcosa non funziona, o lo faresti diverso, scrivilo qui. Lo
        leggiamo.
      </p>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {KINDS.map((k) => (
          <button
            key={k.id}
            type="button"
            onClick={() => setKind(k.id)}
            aria-pressed={kind === k.id}
            className={clsx(
              'rounded-full border px-3 py-1.5 text-xs font-semibold transition',
              kind === k.id
                ? 'border-brand bg-brand/15 text-brand-strong'
                : 'border-line bg-surface-2 text-ink-faint hover:border-ink-faint',
            )}
          >
            {k.label}
          </button>
        ))}
      </div>

      <label className="mt-2 block">
        <span className="sr-only">La tua segnalazione</span>
        <textarea
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            // Il grazie se ne va appena si ricomincia a scrivere: altrimenti
            // resterebbe sopra il secondo messaggio, a dire che è già partito.
            if (sent) setSent(false);
          }}
          rows={2}
          maxLength={4000}
          placeholder={
            kind === 'bug'
              ? 'Cosa hai fatto e cosa è successo. Anche due righe bastano.'
              : kind === 'idea'
                ? 'Cosa faresti diverso?'
                : 'Dicci pure.'
          }
          className="w-full resize-y rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none ring-accent/40 focus:ring"
        />
      </label>

      {error ? (
        <div className="mt-2 rounded-xl bg-bad-bg px-3 py-2 text-sm font-medium text-bad">
          {error}
        </div>
      ) : null}

      <div className="mt-2 flex items-center justify-between gap-3">
        {/* aria-live: chi usa un lettore di schermo non vede sparire il testo dal
            riquadro, e senza questo non saprebbe mai che è partito. */}
        <div className="min-w-0 text-xs" aria-live="polite">
          {sent ? (
            <span className="font-semibold text-good">Ricevuta, grazie. Scrivine pure un'altra.</span>
          ) : (
            <span className="text-ink-faint">
              Ci arrivano da sole la pagina da cui scrivi e il tuo schermo.
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => void send()}
          disabled={pending || text.trim().length < 3}
          className="shrink-0 rounded-xl bg-ink px-4 py-2 text-sm font-bold text-paper transition hover:opacity-90 disabled:opacity-40"
        >
          {pending ? 'Invio…' : 'Manda'}
        </button>
      </div>
    </Card>
  );
}
