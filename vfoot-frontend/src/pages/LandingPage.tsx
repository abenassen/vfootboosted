import { FormEvent, useMemo, useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { Badge, Button, Card } from '../components/ui';
import { ApiError, googleSignIn, resendVerification } from '../api/backend';
import { useAuth } from '../auth/AuthContext';
import GoogleSignInButton from '../components/GoogleSignInButton';
import { afterLoginPath, peekInvite } from '../league/pendingInvite';
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
  const [showPassword, setShowPassword] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Set when the backend says the password was right but the address was never
  // confirmed — the one case where offering "resend" is actually useful.
  const [unconfirmed, setUnconfirmed] = useState<string | null>(null);

  const ctaLabel = useMemo(() => (mode === 'login' ? 'Accedi' : 'Crea account'), [mode]);
  // Chi è arrivato da un link d'invito torna nella LEGA che lo aspettava, non
  // sulla home generica: il giro di registrazione + conferma via mail può durare
  // dei minuti e passare da un'altra scheda, e senza questo il link — che serviva
  // proprio a non dover ricopiare niente — andrebbe perso proprio alla fine.
  const invitedTo = peekInvite();

  if (user) return <Navigate to={afterLoginPath()} replace />;

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setUnconfirmed(null);
    setPending(true);
    try {
      if (mode === 'login') {
        await login({ username, password });
        navigate(afterLoginPath(), { replace: true });
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
      navigate(afterLoginPath(), { replace: true });
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
    <div className="min-h-screen bg-[radial-gradient(circle_at_20%_20%,#dbeafe_0%,#eff6ff_45%,#f8fafc_100%)] text-ink">
      <div className="mx-auto max-w-6xl px-4 py-10 md:py-16">
        {/* `[&>*]:min-w-0`: una cella di griglia non scende sotto la larghezza
            minima del proprio contenuto, e su un telefono da 390 le due schede
            restavano larghe 370 dentro una colonna da 343 — la pagina di
            benvenuto, la prima che si vede, si trascinava di lato. */}
        <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr] [&>*]:min-w-0">
          <Card className="relative overflow-hidden p-6 md:p-8">
            <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-accent/10 blur-2xl" />
            <div className="absolute -bottom-16 -left-16 h-56 w-56 rounded-full bg-indigo-100 blur-2xl" />

            <div className="relative space-y-5">
              <div className="flex items-center gap-3">
                <img src={logo} alt="Vfoot logo" className="h-12 w-12 rounded-xl object-cover shadow-card" />
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Vfoot Boosted</div>
                  <div className="text-lg font-black">Il gioco sul calcio con i voti fatti da noi</div>
                </div>
              </div>

              <h1 className="text-3xl font-black leading-tight md:text-5xl">
                Due modi di giocare
                <br />
                sul calcio.
              </h1>

              <p className="max-w-2xl text-ink-soft md:text-lg">
                Voti calcolati dai dati reali di ogni partita di Serie A, non copiati dai giornali.
                Scegli come vivere la tua lega: alla maniera classica o con la modalità tattica a zone.
              </p>

              <div className="grid gap-3 sm:grid-cols-2">
                <Feature
                  tag="Pronta"
                  tone="green"
                  title="Classic"
                  text="Il gioco sul calcio di sempre — ruoli, formazione e bonus — con i nostri voti al posto di quelli della stampa."
                />
                <Feature
                  tag="In arrivo"
                  tone="slate"
                  title="Aura"
                  text="La sfida tattica per zone: copri il campo giusto e vinci i duelli casa/trasferta."
                />
              </div>
            </div>
          </Card>

          <Card className="p-6 md:p-8">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Account</div>
                <div className="mt-1 text-xl font-black">Accedi a Vfoot</div>
              </div>
            </div>

            {/* Perché si sta facendo l'accesso, quando la ragione è un invito.
                Senza, questa pagina è indistinguibile da un accesso qualunque e
                chi arriva da un link non sa più se il giro sta funzionando. */}
            {invitedTo ? (
              <div className="mb-4 rounded-xl border border-accent/40 bg-accent/10 px-3 py-2 text-sm text-ink-soft">
                <b className="text-accent">Hai un invito in attesa.</b> Appena entri, ti riporto alla
                lega che ti aspetta.{' '}
                <Link to={`/join/${encodeURIComponent(invitedTo)}`} className="font-semibold underline">
                  Vedi quale
                </Link>
              </div>
            ) : null}

            <div className="mb-4 grid grid-cols-2 rounded-xl bg-surface-2 p-1 text-sm font-semibold">
              <button
                type="button"
                onClick={() => setMode('login')}
                className={mode === 'login' ? 'rounded-lg bg-surface py-2' : 'py-2 text-ink-soft'}
              >
                Login
              </button>
              <button
                type="button"
                onClick={() => setMode('register')}
                className={mode === 'register' ? 'rounded-lg bg-surface py-2' : 'py-2 text-ink-soft'}
              >
                Registrati
              </button>
            </div>

            <form onSubmit={onSubmit} className="space-y-3">
              <label className="block text-sm">
                <div className="mb-1 font-semibold text-ink-soft">Username</div>
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  className="w-full rounded-xl border border-line px-3 py-2 outline-none ring-accent/40 focus:ring"
                  placeholder="nomeutente"
                />
              </label>

              {mode === 'register' ? (
                <label className="block text-sm">
                  <div className="mb-1 font-semibold text-ink-soft">Email</div>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    className="w-full rounded-xl border border-line px-3 py-2 outline-none ring-accent/40 focus:ring"
                    placeholder="tu@email.com"
                  />
                  <div className="mt-1 text-xs text-ink-faint">
                    Ti invieremo un link per confermare l’indirizzo.
                  </div>
                </label>
              ) : null}

              <label className="block text-sm">
                <div className="mb-1 font-semibold text-ink-soft">Password</div>
                <div className="relative">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    className="w-full rounded-xl border border-line px-3 py-2 pr-16 outline-none ring-accent/40 focus:ring"
                    placeholder="********"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute inset-y-0 right-0 flex items-center px-3 text-xs font-semibold text-ink-faint hover:text-ink"
                    aria-label={showPassword ? 'Nascondi password' : 'Mostra password'}
                  >
                    {showPassword ? 'Nascondi' : 'Mostra'}
                  </button>
                </div>
                {/* Solo in accesso: in registrazione non c'è ancora una password
                    da recuperare, e l'offerta leggerebbe come un errore. */}
                {mode === 'login' ? (
                  <div className="mt-1.5 text-right">
                    <Link
                      to="/recupera-password"
                      className="text-xs font-semibold text-ink-faint hover:text-ink hover:underline"
                    >
                      Password dimenticata?
                    </Link>
                  </div>
                ) : null}
              </label>

              {mode === 'register' ? (
                <label className="block text-sm">
                  <div className="mb-1 font-semibold text-ink-soft">Conferma password</div>
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={passwordConfirm}
                    onChange={(e) => setPasswordConfirm(e.target.value)}
                    required
                    className="w-full rounded-xl border border-line px-3 py-2 outline-none ring-accent/40 focus:ring"
                    placeholder="********"
                  />
                </label>
              ) : null}

              {error ? <div className="rounded-xl bg-bad-bg px-3 py-2 text-sm font-medium text-bad">{error}</div> : null}
              {notice ? (
                <div className="rounded-xl bg-good-bg px-3 py-2 text-sm font-medium text-good">
                  {notice}
                </div>
              ) : null}

              {unconfirmed ? (
                <div className="space-y-2 rounded-xl bg-warn-bg px-3 py-2 text-sm text-warn">
                  <div className="font-medium">
                    Non hai ricevuto l’email? Inserisci il tuo indirizzo e te la rimandiamo.
                  </div>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full rounded-lg border border-warn/40 px-3 py-1.5 outline-none"
                    placeholder="tu@email.com"
                  />
                  <button
                    type="button"
                    onClick={onResend}
                    disabled={!email}
                    className="rounded-lg bg-warn px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
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
              <div className="mb-3 flex items-center gap-3 text-xs text-ink-faint">
                <div className="h-px flex-1 bg-surface-2" />
                oppure
                <div className="h-px flex-1 bg-surface-2" />
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

function Feature({
  title,
  text,
  tag,
  tone,
}: {
  title: string;
  text: string;
  tag?: string;
  tone?: 'green' | 'slate';
}) {
  return (
    <div className="rounded-xl border border-line bg-surface/80 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-black">{title}</div>
        {tag ? <Badge tone={tone ?? 'slate'}>{tag}</Badge> : null}
      </div>
      <div className="mt-1 text-xs text-ink-soft">{text}</div>
    </div>
  );
}
