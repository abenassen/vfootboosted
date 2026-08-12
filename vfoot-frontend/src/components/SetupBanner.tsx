import { useState } from 'react';
import { Button, Card } from './ui';
import IosInstallSteps from './IosInstallSteps';
import { isIOS, isStandalone } from '../pwa/install';
import { usePush } from '../pwa/usePush';

/** Il passo che manca DAVVERO per ricevere gli avvisi, in Home dove la gente passa.
 *
 *  La domanda non e' "hai installato l'app?" ma "cosa ti manca per essere
 *  avvisato?", e la risposta dipende dalla piattaforma:
 *
 *  - **iOS**: le push esistono solo dall'app aggiunta alla schermata Home, e
 *    Safari non lo propone mai. Li' l'installazione e' un prerequisito vero,
 *    quindi viene prima. Poi, dall'app installata, resta il permesso da dare.
 *  - **tutto il resto**: le push funzionano dalla scheda del browser senza
 *    installare niente. Proporre l'installazione come strada per le notifiche
 *    sarebbe chiedere un passo inutile e tacere l'unico che serve. L'app si
 *    installa lo stesso, per comodita', da Profilo.
 *
 *  Il permesso non lo chiede nessuno da solo — ne' il browser, ne' noi: si puo'
 *  chiedere una volta sola e un rifiuto e' definitivo (vedi usePush), quindi la
 *  richiesta parte solo da un tocco su un bottone che dice a cosa serve.
 *
 *  Prima il banner spariva appena l'app risultava installata: cioe' esattamente
 *  quando l'utente aveva fatto quello che gli avevamo chiesto, lasciandolo con
 *  la promessa di avvisi che poi non arrivavano. Un'app muta non protesta,
 *  quindi non se ne sarebbe accorto.
 *
 *  Ogni faccia si chiude per conto suo: chi aveva scacciato l'invito a installare
 *  e poi ha installato lo stesso merita comunque di sapere delle notifiche.
 *  Senza chiavi VAPID sul server non compare nulla: offrire avvisi che nessuno
 *  puo' mandare e' peggio del silenzio.
 */
const DISMISSED_INSTALL = 'vfoot_install_banner_dismissed';
const DISMISSED_PUSH = 'vfoot_push_banner_dismissed';

function wasDismissed(key: string): boolean {
  if (typeof window === 'undefined') return true;
  try {
    return window.localStorage.getItem(key) === '1';
  } catch {
    // Modalita' privata con storage negato: meglio non mostrare nulla che rompere.
    return true;
  }
}

function remember(key: string): void {
  try {
    window.localStorage.setItem(key, '1');
  } catch {
    /* niente in cui ricordarlo: tornera', ed e' accettabile */
  }
}

/** `closeLabel` is not decoration: the two faces are two different invitations, and
 *  a screen reader (or a test) hearing "Chiudi" twice cannot tell which one it is
 *  looking at. Named per face, the accessible name identifies the banner without
 *  depending on the marketing copy above it, which is meant to be tuned. */
function Frame({ title, closeLabel, onClose, children }: {
  title: string;
  closeLabel: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <Card className="border-l-4 border-accent bg-accent/10 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 text-sm font-bold text-accent">{title}</div>
        <button type="button" onClick={onClose} aria-label={closeLabel}
          className="shrink-0 rounded-lg px-2 py-1 text-accent hover:bg-accent/10">
          ✕
        </button>
      </div>
      {children}
    </Card>
  );
}

export default function SetupBanner() {
  const push = usePush();
  const [dismissedInstall, setDismissedInstall] = useState(() => wasDismissed(DISMISSED_INSTALL));
  const [dismissedPush, setDismissedPush] = useState(() => wasDismissed(DISMISSED_PUSH));
  const [showSteps, setShowSteps] = useState(false);
  const ios = isIOS();

  // 1. Su iPhone senza app installata non c'e' altro da proporre: il permesso
  //    per le notifiche non e' nemmeno raggiungibile da Safari.
  if (ios && !isStandalone()) {
    if (dismissedInstall) return null;
    return (
      <Frame title="📲 Tieni Vfoot sul telefono"
        closeLabel="Chiudi l'invito a installare"
        onClose={() => { setDismissedInstall(true); remember(DISMISSED_INSTALL); }}>
        {/* Di proposito non un elenco di funzioni: cio' di cui l'app avvisa
            crescera' (mercato, asta, giornate), e un testo che elenca quelle di
            oggi invecchia male. La promessa e' "non ti perdi niente". */}
        <div className="mt-1 text-sm text-accent">
          Si apre in un tocco, come un'app, e ti avvisa di quello che succede nella
          tua lega.
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button type="button"
            className="text-sm font-semibold text-accent underline decoration-dotted"
            onClick={() => setShowSteps((v) => !v)}>
            {showSteps ? 'Nascondi i passaggi' : 'Come si fa su iPhone'}
          </button>
          <span className="text-xs text-accent">
            Su iPhone è l'unico modo per ricevere le notifiche — che poi vanno accese
            dall'app installata.
          </span>
        </div>
        {showSteps ? <IosInstallSteps /> : null}
      </Frame>
    );
  }

  // 2. Ovunque altro (e su iPhone dall'app installata): manca solo il permesso.
  //    `loaded` e non `busy`: prima di sapere se serve, questo banner non esiste --
  //    altrimenti lampeggerebbe a ogni caricamento -- ma `busy` torna vero anche
  //    mentre l'iscrizione e' in corso, e li' il banner deve RESTARE, col suo
  //    bottone occupato e la riga dei venti secondi.
  if (!push.loaded || dismissedPush || !push.available || push.subscribed || push.blocked)
    return null;
  // IL PERMESSO PUO' ESSERCI GIA'. Segnalato il 12/08/2026: il browser diceva
  // «notifiche: consentite» e questo banner chiedeva di attivarle, cioe' di ridare una
  // cosa gia' data — e chi legge conclude che l'app non sa quello che dice. Ora
  // l'iscrizione perduta col permesso concesso la rimette a posto usePush da solo, in
  // silenzio; se il banner compare COMUNQUE vuol dire che quella riparazione non e'
  // riuscita, e allora le parole devono dire quello. Le due situazioni hanno rimedi
  // diversi: una e' un permesso da dare, l'altra un collegamento da rifare.
  const permessoGiaDato = typeof Notification !== 'undefined'
    && Notification.permission === 'granted';
  return (
    <Frame title={permessoGiaDato
      ? '🔔 Avvisi da ricollegare su questo dispositivo'
      : '🔔 Ci sei quasi: attiva le notifiche'}
      closeLabel="Chiudi l'invito alle notifiche"
      onClose={() => { setDismissedPush(true); remember(DISMISSED_PUSH); }}>
      <div className="mt-1 text-sm text-accent">
        {permessoGiaDato
          ? 'Il permesso c’è già, ma questo dispositivo non risulta collegato agli avvisi — '
            + 'può succedere dopo una pulizia dei dati del browser. Si rimette con un tocco.'
          : isStandalone()
            ? 'L’app è installata, ma gli avvisi sono ancora spenti: vanno accesi una volta, da qui.'
            : 'Ti avvisiamo di quello che succede nella tua lega, anche quando non sei sul sito.'
              + ' Solo quello che ti riguarda.'}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button size="sm" variant="primary" disabled={push.busy}
          onClick={() => void push.enable()}>
          {push.busy ? 'Attivo…' : permessoGiaDato ? 'Ricollega gli avvisi' : 'Attiva le notifiche'}
        </Button>
        {push.busy && (
          // Misurati ~30s a browser freddo: mezzo minuto muto sembra un bottone rotto.
          <span className="text-xs text-accent">
            La prima volta può richiedere una ventina di secondi.
          </span>
        )}
      </div>
      {push.error && (
        <div className="mt-2 rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">{push.error}</div>
      )}
    </Frame>
  );
}
