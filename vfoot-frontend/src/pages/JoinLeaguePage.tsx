import { FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button, Card } from '../components/ui';
import { ApiError, type LeagueInvitePreview } from '../api/backend';
import { getLeagueInvite, joinLeague } from '../api';
import { useAuth } from '../auth/AuthContext';
import { rememberSelectedLeague } from '../league/LeagueContext';
import { forgetInvite, rememberInvite } from '../league/pendingInvite';
import logo from '../assets/logo.png';

/** IL LINK D'INVITO — `/join/<codice>`.
 *
 *  Prima si passava il codice a voce (o su WhatsApp) e chi lo riceveva doveva
 *  trovare da solo Gestione lega, la scheda giusta, il campo giusto, e ricopiarlo
 *  senza sbagliare una maiuscola. Il codice a mano resta — è la strada per chi
 *  arriva da un messaggio letto altrove — ma non è più l'unica.
 *
 *  Sta fuori dalle rotte protette apposta: un invito lo apre spesso qualcuno che
 *  un account qui non ce l'ha ancora, e mandarlo alla pagina d'accesso senza
 *  dirgli nemmeno DOVE è stato invitato è il modo migliore per perderlo. Chi non
 *  ha la sessione vede comunque il nome della lega e chi lo ha invitato; il
 *  codice viene messo da parte (v. pendingInvite) e ritrovato appena l'accesso è
 *  fatto, anche se nel frattempo è passato dalla mail di conferma.
 */
export default function JoinLeaguePage() {
  const { code = '' } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();

  const [invite, setInvite] = useState<LeagueInvitePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [teamName, setTeamName] = useState('');
  const [busy, setBusy] = useState(false);

  // Messo da parte SUBITO, prima ancora di sapere se il codice è buono: se
  // l'utente tocca «accedi» un istante dopo, il codice deve essere già al sicuro.
  useEffect(() => {
    if (code) rememberInvite(code);
  }, [code]);

  // La sessione decide cosa risponde il server (`already_member`), quindi si
  // aspetta di sapere se c'è prima di chiedere.
  useEffect(() => {
    if (authLoading || !code) return;
    let alive = true;
    setLoading(true);
    void getLeagueInvite(code)
      .then((data) => {
        if (!alive) return;
        setInvite(data);
        setError(null);
      })
      .catch((err) => {
        if (!alive) return;
        // Un codice che non esiste non va tenuto da parte: resterebbe a
        // dirottare ogni accesso futuro verso una lega che non c'è.
        forgetInvite();
        setError(
          err instanceof ApiError && err.status === 404
            ? 'Questo invito non esiste (o è di una lega cancellata).'
            : err instanceof TypeError
              ? 'Impossibile contattare il server. Riprova tra poco.'
              : err instanceof Error
                ? err.message
                : 'Invito non leggibile.',
        );
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [code, authLoading, user]);

  // Chi è già dentro non deve rientrare: lo si porta nella lega e basta. Vale
  // anche per l'admin che apre il proprio link per controllare che funzioni.
  useEffect(() => {
    if (!invite?.already_member) return;
    forgetInvite();
    rememberSelectedLeague(invite.league_id);
    navigate('/home', { replace: true });
  }, [invite, navigate]);

  async function onJoin(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await joinLeague({ invite_code: code, team_name: teamName.trim() });
      forgetInvite();
      rememberSelectedLeague(res.league_id);
      // Nella lega, non sul modulo appena compilato: la domanda successiva di
      // chiunque sia appena entrato è «e adesso cosa c'è qui dentro».
      navigate('/home', {
        replace: true,
        state: { joined: { league: res.name, team: teamName.trim() } },
      });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Ingresso non riuscito.',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    // Sfondo dal tema e non l'azzurro fisso delle altre pagine pubbliche: chi
    // apre un invito al buio si troverebbe una scheda scura appoggiata su un
    // fondo chiaro, e questa è la prima pagina del sito che vede.
    <div className="min-h-screen bg-paper px-4 py-10 pt-[calc(2.5rem_+_var(--vf-safe-top))] text-ink md:py-16 md:pt-[calc(4rem_+_var(--vf-safe-top))]">
      <Card className="mx-auto max-w-md p-6 md:p-8">
        <div className="flex items-center gap-3">
          <img src={logo} alt="" className="h-10 w-10 rounded-xl object-cover shadow-card" />
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Invito</div>
            <div className="text-lg font-black">Vfoot Boosted</div>
          </div>
        </div>

        {authLoading || loading ? (
          <div className="mt-6 text-sm text-ink-soft">Apertura dell’invito…</div>
        ) : error && !invite ? (
          <>
            <div className="mt-6 rounded-xl bg-bad-bg px-3 py-2 text-sm font-medium text-bad">{error}</div>
            <div className="mt-4 text-sm text-ink-soft">
              Se hai il codice, puoi sempre entrare a mano da <b>Gestione lega</b>.
            </div>
            <Link
              to={user ? '/league-admin?tab=user' : '/'}
              className="mt-4 inline-block rounded-xl bg-ink px-4 py-2 text-sm font-semibold text-paper"
            >
              {user ? 'Vai a Gestione lega' : 'Vai all’accesso'}
            </Link>
          </>
        ) : invite ? (
          <>
            <div className="mt-6">
              <div className="text-sm text-ink-soft">Sei stato invitato in</div>
              <div className="mt-0.5 font-cond text-3xl font-bold uppercase leading-none tracking-wide">
                {invite.name}
              </div>
              <div className="mt-2 text-xs text-ink-faint">
                {invite.mode === 'classic' ? 'Fantacalcio classico' : 'Aura'}
                {invite.reference_season ? ` · ${invite.reference_season}` : ''}
                {' · '}
                {invite.teams === 1 ? '1 squadra iscritta' : `${invite.teams} squadre iscritte`}
                {invite.admin_username ? ` · amministra ${invite.admin_username}` : ''}
              </div>
            </div>

            {invite.already_member ? (
              <div className="mt-6 text-sm text-ink-soft">Sei già in questa lega: ti porto dentro…</div>
            ) : user ? (
              <form className="mt-6 space-y-3" onSubmit={onJoin}>
                <label className="block text-sm font-medium text-ink-soft">
                  Come si chiama la tua squadra <span className="text-bad">*</span>
                  <input
                    className="mt-1 w-full rounded-xl border px-3 py-2 font-normal"
                    placeholder="es. Real Sconfitta"
                    value={teamName}
                    onChange={(e) => setTeamName(e.target.value)}
                    autoFocus
                    required
                  />
                </label>
                {error ? (
                  <div className="rounded-xl bg-bad-bg px-3 py-2 text-sm font-medium text-bad">{error}</div>
                ) : null}
                <Button type="submit" disabled={busy || !teamName.trim()}>
                  {busy ? 'Ingresso…' : `Entra in ${invite.name}`}
                </Button>
                <div className="text-[11px] text-ink-faint">
                  Entri come <b>{user.username}</b>. Il nome della squadra si potrà cambiare dal profilo.
                </div>
              </form>
            ) : (
              <>
                <div className="mt-6 rounded-xl border border-line bg-surface-2 p-3 text-sm text-ink-soft">
                  Accedi o crea un account: appena fatto torni qui e ti resta da scegliere solo il nome
                  della squadra.
                </div>
                <Link
                  to="/"
                  className="mt-4 inline-block rounded-xl bg-ink px-4 py-2 text-sm font-semibold text-paper"
                >
                  Accedi o registrati
                </Link>
              </>
            )}
          </>
        ) : null}
      </Card>
    </div>
  );
}
