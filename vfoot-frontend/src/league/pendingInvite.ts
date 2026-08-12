/** Il codice d'invito messo da parte mentre si fa l'accesso.
 *
 *  Chi riceve il link e non ha ancora un account passa per registrazione, mail di
 *  conferma e login: tre pagine e, con la mail, spesso un'altra scheda del
 *  browser. Senza un posto dove ricordare per quale lega era partito, alla fine
 *  del giro si ritrova sulla home come uno qualunque, e il link — che era
 *  proprio la cosa da NON dover ricopiare a mano — è perso.
 *
 *  Sta in `localStorage` e non nell'indirizzo per questo: deve sopravvivere alla
 *  scheda che si chiude. Si consuma appena l'ingresso è avvenuto, o quando il
 *  codice si rivela non valido, così non resta ad aspettare per sempre.
 */
const KEY = 'vfoot_pending_invite';

export function rememberInvite(code: string) {
  if (typeof window === 'undefined' || !code) return;
  try {
    window.localStorage.setItem(KEY, code);
  } catch {
    // Navigazione privata con lo spazio negato: si perde il ricordo, non il giro.
  }
}

export function peekInvite(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function forgetInvite() {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* vedi sopra */
  }
}

/** Dove mandare qualcuno che ha appena fatto l'accesso: nella lega che lo aveva
 *  invitato, se ce n'era una, altrimenti a casa sua. */
export function afterLoginPath(): string {
  const code = peekInvite();
  return code ? `/join/${encodeURIComponent(code)}` : '/home';
}
