import { useState } from 'react';
import CopyButton from './CopyButton';

/** COME SI FA ENTRARE QUALCUNO: un link, e sotto il codice.
 *
 *  Il codice da solo obbliga chi lo riceve a cercarsi Gestione lega, la scheda
 *  giusta e il campo giusto, e a ricopiare otto caratteri con le maiuscole al
 *  posto loro. Il link fa tutto quello al posto suo (v. pages/JoinLeaguePage) e
 *  quindi sta in cima; il codice resta sotto perché è la strada per chi l'invito
 *  se lo sente dire a voce, o lo legge su un telefono diverso da quello con cui
 *  gioca.
 *
 *  L'indirizzo si compone qui e non sul server: il backend pubblica il pezzo che
 *  conosce (`invite_link` = `/join/<codice>`) e il dominio giusto lo sa solo il
 *  browser che sta guardando — in prova è un IP di rete locale, in produzione
 *  vfoot.it, e sbagliarlo vuol dire mandare in giro un link morto.
 */
export default function InviteShare({
  code,
  path,
  leagueName,
  compact,
}: {
  code: string;
  /** Il `invite_link` del server. Ricostruito dal codice se manca. */
  path?: string | null;
  leagueName?: string | null;
  /** Senza intestazione, per quando la scheda attorno la dice già. */
  compact?: boolean;
}) {
  const [shared, setShared] = useState(false);
  const origin = typeof window === 'undefined' ? '' : window.location.origin;
  const url = `${origin}${path || `/join/${code}`}`;
  const message = leagueName
    ? `Ti invito nella lega «${leagueName}» su Vfoot Boosted: ${url}`
    : `Ti invito nella mia lega su Vfoot Boosted: ${url}`;

  // Il foglio di condivisione del telefono, che è il modo in cui un invito parte
  // davvero: WhatsApp, Telegram, il messaggio. Sul desktop di solito non c'è, e
  // lì il bottone semplicemente non compare — copiare basta.
  const canShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function';

  async function share() {
    try {
      await navigator.share({ title: leagueName ?? 'Vfoot Boosted', text: message, url });
      setShared(true);
      window.setTimeout(() => setShared(false), 1500);
    } catch {
      /* annullato dall'utente, o negato: il link resta lì da copiare */
    }
  }

  return (
    <div className={compact ? '' : 'rounded-xl border border-line bg-surface p-3'}>
      {compact ? null : (
        <div className="text-xs font-bold uppercase tracking-wide text-ink-faint">Invita i partecipanti</div>
      )}
      <div className={compact ? '' : 'mt-2'}>
        <div className="flex flex-wrap items-center gap-2">
          {/* `break-all`: un indirizzo non si spezza sugli spazi perché non ne ha,
              e su un telefono allargava da solo tutta la scheda. */}
          <code className="min-w-0 flex-1 break-all rounded-lg bg-surface-2 px-2 py-1 font-mono text-xs text-ink">
            {url}
          </code>
          <CopyButton value={url} label="Copia link" />
          {canShare ? (
            <button
              type="button"
              onClick={() => void share()}
              className="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-1 text-xs font-semibold text-ink-soft hover:bg-surface-2"
            >
              <span>{shared ? '✓' : '📤'}</span>
              {shared ? 'Inviato' : 'Condividi'}
            </button>
          ) : null}
        </div>
        <div className="mt-1.5 text-[11px] text-ink-faint">
          Chi lo apre entra da solo: se ha già l’accesso gli resta da scegliere il nome della squadra.
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-ink-faint">
          <span>Oppure a mano, col codice</span>
          <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs font-bold text-ink">{code}</code>
          <CopyButton value={code} label="Copia codice" />
        </div>
      </div>
    </div>
  );
}
