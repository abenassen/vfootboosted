/** How to install on iPhone, since Safari never says.
 *
 *  Shared between the Home banner and the profile card so the wording cannot
 *  drift: the four steps are the only route to notifications on iOS, and getting
 *  them subtly wrong in one of two places is how a user gives up.
 */
export default function IosInstallSteps({ tone = 'sky' }: { tone?: 'sky' | 'slate' }) {
  const text = tone === 'sky' ? 'text-sky-900' : 'text-slate-700';
  return (
    <ol className={`mt-2 list-decimal space-y-1 pl-5 text-sm ${text}`}>
      <li>Tocca il tasto Condividi in basso (il quadrato con la freccia verso l'alto).</li>
      <li>Scorri e scegli «Aggiungi alla schermata Home».</li>
      <li>Conferma: comparirà l'icona di Vfoot fra le tue app.</li>
      <li>Apri Vfoot da quell'icona: da lì potrai attivare le notifiche.</li>
    </ol>
  );
}
