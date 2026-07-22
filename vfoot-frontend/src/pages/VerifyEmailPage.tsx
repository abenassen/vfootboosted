import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Card } from '../components/ui';
import { ApiError, verifyEmail } from '../api/backend';
import { useAuth } from '../auth/AuthContext';

type State =
  | { kind: 'working' }
  | { kind: 'done'; signedIn: boolean; message: string }
  | { kind: 'failed'; message: string };

/** Landing page for the link sent by email. It carries uid+token in the query
 *  string and exchanges them for a session. */
export default function VerifyEmailPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [state, setState] = useState<State>({ kind: 'working' });
  // React 18 mounts effects twice in dev; without this the second run would
  // re-post a token the first run has already consumed and report a failure.
  const started = useRef(false);

  const uid = params.get('uid');
  const token = params.get('token');

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    if (!uid || !token) {
      setState({ kind: 'failed', message: 'Link di conferma incompleto.' });
      return;
    }
    (async () => {
      try {
        const res = await verifyEmail({ uid, token });
        if (res.token) {
          await refresh();
          setState({
            kind: 'done',
            signedIn: true,
            message: 'Email confermata: il tuo account è attivo.',
          });
        } else {
          setState({
            kind: 'done',
            signedIn: false,
            message: res.detail ?? 'Account già attivo: puoi accedere.',
          });
        }
      } catch (err) {
        setState({
          kind: 'failed',
          message:
            err instanceof ApiError
              ? err.message
              : err instanceof TypeError
                ? 'Impossibile contattare il server. Riprova tra poco.'
                : 'Conferma non riuscita.',
        });
      }
    })();
  }, [uid, token, refresh]);

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_20%_20%,#dbeafe_0%,#eff6ff_45%,#f8fafc_100%)] px-4 py-16 text-slate-900">
      <Card className="mx-auto max-w-md p-6 md:p-8">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Account</div>
        <div className="mt-1 text-xl font-black">Conferma email</div>

        <div className="mt-4 text-sm">
          {state.kind === 'working' ? (
            <div className="text-slate-600">Verifica in corso…</div>
          ) : state.kind === 'done' ? (
            <div className="rounded-xl bg-emerald-50 px-3 py-2 font-medium text-emerald-800">
              {state.message}
            </div>
          ) : (
            <div className="rounded-xl bg-red-50 px-3 py-2 font-medium text-red-700">
              {state.message}
            </div>
          )}
        </div>

        <div className="mt-5">
          {state.kind === 'done' && state.signedIn ? (
            <Button type="button" onClick={() => navigate('/home', { replace: true })}>
              Entra
            </Button>
          ) : state.kind === 'working' ? null : (
            <Link
              to="/"
              className="inline-block rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white"
            >
              Vai all’accesso
            </Link>
          )}
        </div>
      </Card>
    </div>
  );
}
