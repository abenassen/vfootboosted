import { FormEvent, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Card } from '../components/ui';
import { ApiError, confirmPasswordReset } from '../api/backend';
import { useAuth } from '../auth/AuthContext';

/** Landing page for the reset link: it carries uid+token in the query string and
 *  exchanges them, plus a new password, for a session.
 *
 *  Unlike the confirmation link (VerifyEmailPage) this one must NOT act on load —
 *  it needs the password first. That difference also spares it the double-mount
 *  guard: nothing is spent until the form is submitted. */
export default function NewPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refresh } = useAuth();

  const uid = params.get('uid');
  const token = params.get('token');

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [show, setShow] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!uid || !token) return;
    if (password !== confirm) {
      // Checked here as well as on the server: it is the one error the browser
      // can answer without a round trip, and the round trip would cost the link.
      setError('Le due password non coincidono.');
      return;
    }
    setPending(true);
    setError(null);
    try {
      await confirmPasswordReset({
        uid,
        token,
        new_password: password,
        new_password_confirm: confirm,
      });
      await refresh();
      navigate('/home', { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof TypeError
            ? 'Impossibile contattare il server. Riprova tra poco.'
            : 'Non è stato possibile reimpostare la password.',
      );
    } finally {
      setPending(false);
    }
  }

  const incomplete = !uid || !token;

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_20%_20%,#dbeafe_0%,#eff6ff_45%,#f8fafc_100%)] px-4 py-16 text-ink">
      <Card className="mx-auto max-w-md p-6 md:p-8">
        <div className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Account</div>
        <div className="mt-1 text-xl font-black">Nuova password</div>

        {incomplete ? (
          <>
            <div className="mt-4 rounded-xl bg-bad-bg px-3 py-2 text-sm font-medium text-bad">
              Link incompleto. Aprilo dall’email così com’è, oppure chiedine uno nuovo.
            </div>
            <div className="mt-5">
              <Link
                to="/recupera-password"
                className="inline-block rounded-xl bg-ink px-4 py-2 text-sm font-semibold text-paper"
              >
                Chiedi un nuovo link
              </Link>
            </div>
          </>
        ) : (
          <form className="mt-4 space-y-3" onSubmit={onSubmit}>
            <div className="text-sm text-ink-soft">
              Scegli la nuova password: almeno 8 caratteri, e non una troppo comune.
            </div>

            <label className="block text-sm">
              <div className="mb-1 font-semibold text-ink-soft">Nuova password</div>
              <div className="relative">
                <input
                  type={show ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  autoFocus
                  className="w-full rounded-xl border border-line px-3 py-2 pr-16 outline-none ring-accent/40 focus:ring"
                  placeholder="********"
                />
                <button
                  type="button"
                  onClick={() => setShow((v) => !v)}
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-xs font-semibold text-ink-faint hover:text-ink"
                  aria-label={show ? 'Nascondi password' : 'Mostra password'}
                >
                  {show ? 'Nascondi' : 'Mostra'}
                </button>
              </div>
            </label>

            <label className="block text-sm">
              <div className="mb-1 font-semibold text-ink-soft">Conferma password</div>
              <input
                type={show ? 'text' : 'password'}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                minLength={8}
                className="w-full rounded-xl border border-line px-3 py-2 outline-none ring-accent/40 focus:ring"
                placeholder="********"
              />
            </label>

            {error ? (
              <div className="space-y-2 rounded-xl bg-bad-bg px-3 py-2 text-sm font-medium text-bad">
                <div>{error}</div>
                {/* A dead link is the most likely failure here — it burns on use,
                    and on any sign-in — so the way out is offered with the error
                    instead of leaving the form as the only thing on screen. */}
                <Link to="/recupera-password" className="inline-block font-semibold underline">
                  Chiedi un nuovo link
                </Link>
              </div>
            ) : null}

            <Button type="submit" disabled={pending}>
              {pending ? 'Salvataggio…' : 'Salva ed entra'}
            </Button>
          </form>
        )}
      </Card>
    </div>
  );
}
