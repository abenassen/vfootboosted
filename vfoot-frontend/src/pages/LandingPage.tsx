import { FormEvent, useMemo, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { Badge, Button, Card } from '../components/ui';
import { apiProvider } from '../api';
import { ApiError, googleSignIn, resendVerification } from '../api/backend';
import { useAuth } from '../auth/AuthContext';
import GoogleSignInButton from '../components/GoogleSignInButton';
import logo from '../assets/logo.png';

type Mode = 'login' | 'register';

export default function LandingPage() {
  const navigate = useNavigate();
  const { user, login, register, refresh } = useAuth();

  const [mode, setMode] = useState<Mode>('login');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Set when the backend says the password was right but the address was never
  // confirmed — the one case where offering "resend" is actually useful.
  const [unconfirmed, setUnconfirmed] = useState<string | null>(null);

  const ctaLabel = useMemo(() => (mode === 'login' ? 'Accedi' : 'Crea account'), [mode]);

  if (user) return <Navigate to="/home" replace />;

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setUnconfirmed(null);
    setPending(true);
    try {
      if (mode === 'login') {
        await login({ username, password });
        navigate('/home', { replace: true });
      } else {
        // No navigation: the account is not usable until the link is opened.
        const res = await register({ username, email, password, password_confirm: passwordConfirm });
        setNotice(res.detail);
        setPassword('');
        setPasswordConfirm('');
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setUnconfirmed(username);
      // ApiError already carries a message written for the user; a bare TypeError
      // here means fetch never reached the server (backend down / wrong address).
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof TypeError
            ? 'Impossibile contattare il server. Verifica che sia avviato e riprova.'
            : err instanceof Error
              ? err.message
              : 'Operazione non riuscita.',
      );
    } finally {
      setPending(false);
    }
  }

  async function onGoogleCredential(credential: string) {
    setError(null);
    setNotice(null);
    setUnconfirmed(null);
    setPending(true);
    try {
      await googleSignIn(credential);
      await refresh();
      navigate('/home', { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Accesso con Google non riuscito.');
    } finally {
      setPending(false);
    }
  }

  async function onResend() {
    setError(null);
    try {
      const res = await resendVerification(email);
      setNotice(res.detail);
      setUnconfirmed(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Invio non riuscito.');
    }
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_20%_20%,#dbeafe_0%,#eff6ff_45%,#f8fafc_100%)] text-slate-900">
      <div className="mx-auto max-w-6xl px-4 py-10 md:py-16">
        <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
          <Card className="relative overflow-hidden p-6 md:p-8">
            <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-sky-100 blur-2xl" />
            <div className="absolute -bottom-16 -left-16 h-56 w-56 rounded-full bg-indigo-100 blur-2xl" />

            <div className="relative space-y-5">
              <div className="flex items-center gap-3">
                <img src={logo} alt="Vfoot logo" className="h-12 w-12 rounded-xl object-cover shadow-card" />
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Vfoot Boosted</div>
                  <div className="text-lg font-black">Spatial Fantasy Football</div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Badge tone="green">Vfoot Engine</Badge>
                <Badge tone="slate">Provider: {apiProvider}</Badge>
              </div>

              <h1 className="text-3xl font-black leading-tight md:text-5xl">
                Fantacalcio tattico,
                <br />
                guidato dalle zone.
              </h1>

              <p className="max-w-2xl text-slate-600 md:text-lg">
                In Vfoot il ruolo non e fissato: emerge dai dati reali di campo. Gestisci la tua squadra
                per coprire le zone giuste, vincere i duelli e trasformare la strategia in punteggio.
              </p>

              <div className="grid gap-3 sm:grid-cols-3">
                <Feature title="Heatmap reali" text="Presenza per zona normalizzata, partita per partita." />
                <Feature title="Duelli locali" text="Ogni zona genera un confronto casa/trasferta." />
                <Feature title="Anti exploit" text="Overcrowding penalizzato con rinormalizzazione." />
              </div>
            </div>
          </Card>

          <Card className="p-6 md:p-8">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Account</div>
                <div className="mt-1 text-xl font-black">Accedi a Vfoot</div>
              </div>
            </div>

            <div className="mb-4 grid grid-cols-2 rounded-xl bg-slate-100 p-1 text-sm font-semibold">
              <button
                type="button"
                onClick={() => setMode('login')}
                className={mode === 'login' ? 'rounded-lg bg-white py-2' : 'py-2 text-slate-600'}
              >
                Login
              </button>
              <button
                type="button"
                onClick={() => setMode('register')}
                className={mode === 'register' ? 'rounded-lg bg-white py-2' : 'py-2 text-slate-600'}
              >
                Registrati
              </button>
            </div>

            <form onSubmit={onSubmit} className="space-y-3">
              <label className="block text-sm">
                <div className="mb-1 font-semibold text-slate-700">Username</div>
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  className="w-full rounded-xl border border-slate-300 px-3 py-2 outline-none ring-sky-200 focus:ring"
                  placeholder="nomeutente"
                />
              </label>

              {mode === 'register' ? (
                <label className="block text-sm">
                  <div className="mb-1 font-semibold text-slate-700">Email</div>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    className="w-full rounded-xl border border-slate-300 px-3 py-2 outline-none ring-sky-200 focus:ring"
                    placeholder="tu@email.com"
                  />
                  <div className="mt-1 text-xs text-slate-500">
                    Ti invieremo un link per confermare l’indirizzo.
                  </div>
                </label>
              ) : null}

              <label className="block text-sm">
                <div className="mb-1 font-semibold text-slate-700">Password</div>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="w-full rounded-xl border border-slate-300 px-3 py-2 outline-none ring-sky-200 focus:ring"
                  placeholder="********"
                />
              </label>

              {mode === 'register' ? (
                <label className="block text-sm">
                  <div className="mb-1 font-semibold text-slate-700">Conferma password</div>
                  <input
                    type="password"
                    value={passwordConfirm}
                    onChange={(e) => setPasswordConfirm(e.target.value)}
                    required
                    className="w-full rounded-xl border border-slate-300 px-3 py-2 outline-none ring-sky-200 focus:ring"
                    placeholder="********"
                  />
                </label>
              ) : null}

              {error ? <div className="rounded-xl bg-red-50 px-3 py-2 text-sm font-medium text-red-700">{error}</div> : null}
              {notice ? (
                <div className="rounded-xl bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-800">
                  {notice}
                </div>
              ) : null}

              {unconfirmed ? (
                <div className="space-y-2 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  <div className="font-medium">
                    Non hai ricevuto l’email? Inserisci il tuo indirizzo e te la rimandiamo.
                  </div>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full rounded-lg border border-amber-300 px-3 py-1.5 outline-none"
                    placeholder="tu@email.com"
                  />
                  <button
                    type="button"
                    onClick={onResend}
                    disabled={!email}
                    className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                  >
                    Rimanda l’email di conferma
                  </button>
                </div>
              ) : null}

              <Button type="submit" disabled={pending}>
                {pending ? 'Attendere…' : ctaLabel}
              </Button>
            </form>

            <div className="mt-4">
              <div className="mb-3 flex items-center gap-3 text-xs text-slate-400">
                <div className="h-px flex-1 bg-slate-200" />
                oppure
                <div className="h-px flex-1 bg-slate-200" />
              </div>
              <GoogleSignInButton
                onCredential={onGoogleCredential}
                text={mode === 'register' ? 'signup_with' : 'signin_with'}
              />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Feature({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white/80 p-3">
      <div className="text-sm font-black">{title}</div>
      <div className="mt-1 text-xs text-slate-600">{text}</div>
    </div>
  );
}
