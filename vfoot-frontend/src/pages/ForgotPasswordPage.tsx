import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, Card } from '../components/ui';
import { ApiError, requestPasswordReset } from '../api/backend';

/** Ask for a reset link. Deliberately asks for the EMAIL and not the username:
 *  the address is the thing we can prove you own, and it is what someone who has
 *  forgotten their way in is most likely to still remember. */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [pending, setPending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      await requestPasswordReset(email);
      setSent(true);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof TypeError
            ? 'Impossibile contattare il server. Riprova tra poco.'
            : 'Richiesta non riuscita.',
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_20%_20%,#dbeafe_0%,#eff6ff_45%,#f8fafc_100%)] px-4 py-16 text-ink">
      <Card className="mx-auto max-w-md p-6 md:p-8">
        <div className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Account</div>
        <div className="mt-1 text-xl font-black">Password dimenticata</div>

        {sent ? (
          <>
            {/* The same words whether or not the address was found: the server
                answers identically on purpose, and a page that said "non
                registrata" would undo that and turn this into a way to find out
                who has an account. */}
            <div className="mt-4 rounded-xl bg-good-bg px-3 py-2 text-sm font-medium text-good">
              Se l’indirizzo è registrato, ti abbiamo inviato un link per
              reimpostare la password. Controlla la posta, anche nello spam.
            </div>
            <div className="mt-3 text-sm text-ink-soft">
              Il link vale una volta sola e scade dopo tre giorni.
            </div>
            <div className="mt-5">
              <Link
                to="/"
                className="inline-block rounded-xl bg-ink px-4 py-2 text-sm font-semibold text-paper"
              >
                Torna all’accesso
              </Link>
            </div>
          </>
        ) : (
          <form className="mt-4 space-y-3" onSubmit={onSubmit}>
            <div className="text-sm text-ink-soft">
              Inserisci l’indirizzo con cui ti sei registrato: ti mandiamo un link
              per scegliere una nuova password.
            </div>

            <label className="block text-sm">
              <div className="mb-1 font-semibold text-ink-soft">Email</div>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
                className="w-full rounded-xl border border-line px-3 py-2 outline-none ring-accent/40 focus:ring"
                placeholder="tu@email.com"
              />
            </label>

            {error ? (
              <div className="rounded-xl bg-bad-bg px-3 py-2 text-sm font-medium text-bad">{error}</div>
            ) : null}

            <Button type="submit" disabled={pending}>
              {pending ? 'Invio…' : 'Mandami il link'}
            </Button>

            <div className="pt-1 text-sm">
              <Link to="/" className="font-semibold text-accent hover:underline">
                Torna all’accesso
              </Link>
            </div>
          </form>
        )}
      </Card>
    </div>
  );
}
