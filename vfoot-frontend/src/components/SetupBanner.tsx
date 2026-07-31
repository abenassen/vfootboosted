import { useEffect, useState } from 'react';
import { Button, Card } from './ui';
import IosInstallSteps from './IosInstallSteps';
import {
  installPromptAvailable,
  isIOS,
  isStandalone,
  onInstallPromptChange,
  promptInstall,
} from '../pwa/install';
import { usePush } from '../pwa/usePush';

/** Il passo successivo per ricevere gli avvisi, in Home dove la gente passa.
 *
 *  Sono DUE passi, non uno, ed e' il motivo per cui questo banner ha due facce.
 *  Su iOS installare non basta: le notifiche vanno accese a parte, e il permesso
 *  non lo chiede nessuno da solo — ne' Safari, ne' noi (vedi usePush: si puo'
 *  chiedere una volta sola, quindi la richiesta parte solo da un tocco su un
 *  bottone che dice a cosa serve).
 *
 *  Prima il banner spariva appena l'app risultava installata: cioe' esattamente
 *  quando l'utente aveva fatto quello che gli avevamo chiesto, lasciandolo con
 *  la promessa di avvisi che poi non arrivavano. Un'app muta non protesta,
 *  quindi non se ne sarebbe accorto. Ora al posto dell'invito compare il passo
 *  che manca.
 *
 *  Ogni faccia si chiude per conto suo: chi aveva scacciato l'invito a installare
 *  e poi ha installato lo stesso merita comunque di sapere delle notifiche.
 *  L'offerta resta sempre in Profilo per chi cambia idea.
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

function Frame({ title, onClose, children }: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <Card className="border-l-4 border-sky-500 bg-sky-50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 text-sm font-bold text-sky-900">{title}</div>
        <button type="button" onClick={onClose} aria-label="Chiudi"
          className="shrink-0 rounded-lg px-2 py-1 text-sky-700 hover:bg-sky-100">
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
  const [canInstall, setCanInstall] = useState(installPromptAvailable());
  const [showSteps, setShowSteps] = useState(false);
  // usePush parte occupato: senza questo il banner delle notifiche lampeggerebbe
  // a ogni caricamento, prima ancora di sapere se serve.
  const [ready, setReady] = useState(false);
  const ios = isIOS();

  useEffect(() => onInstallPromptChange(setCanInstall), []);
  useEffect(() => { if (!push.busy) setReady(true); }, [push.busy]);

  // Installata ma muta: il passo che manca davvero.
  if (isStandalone()) {
    if (!ready || dismissedPush || !push.available || push.subscribed || push.blocked) return null;
    return (
      <Frame title="🔔 Ci sei quasi: attiva le notifiche"
        onClose={() => { setDismissedPush(true); remember(DISMISSED_PUSH); }}>
        <div className="mt-1 text-sm text-sky-800">
          L'app è installata, ma gli avvisi sono ancora spenti: vanno accesi una volta,
          da qui. Solo quello che ti riguarda.
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button size="sm" variant="primary" disabled={push.busy}
            onClick={() => void push.enable()}>
            {push.busy ? 'Attivo…' : 'Attiva le notifiche'}
          </Button>
          {push.busy && (
            // Misurati ~30s a browser freddo: mezzo minuto muto sembra un bottone rotto.
            <span className="text-xs text-sky-800">
              La prima volta può richiedere una ventina di secondi.
            </span>
          )}
        </div>
        {push.error && (
          <div className="mt-2 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700">{push.error}</div>
        )}
      </Frame>
    );
  }

  if (dismissedInstall) return null;

  return (
    <Frame title="📲 Tieni Vfoot sul telefono"
      onClose={() => { setDismissedInstall(true); remember(DISMISSED_INSTALL); }}>
      {/* Di proposito non un elenco di funzioni: cio' di cui l'app avvisa
          crescera' (mercato, asta, giornate), e un testo che elenca quelle di
          oggi invecchia male. La promessa e' "non ti perdi niente". */}
      <div className="mt-1 text-sm text-sky-800">
        Si apre in un tocco, come un'app, e ti avvisa di quello che succede nella
        tua lega.
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        {ios ? (
          <button type="button"
            className="text-sm font-semibold text-sky-900 underline decoration-dotted"
            onClick={() => setShowSteps((v) => !v)}>
            {showSteps ? 'Nascondi i passaggi' : 'Come si fa su iPhone'}
          </button>
        ) : canInstall ? (
          <Button size="sm" variant="primary" onClick={() => void promptInstall()}>
            Installa
          </Button>
        ) : (
          /* Nessun prompt catturato non significa "non installabile": Chrome
             emette beforeinstallprompt solo dopo un po' di uso della pagina. */
          <span className="text-xs text-sky-800">
            Dal menu del browser (⋮) scegli «Installa app».
          </span>
        )}
        {ios ? (
          <span className="text-xs text-sky-800">
            Su iPhone è l'unico modo per ricevere le notifiche — che poi vanno accese
            dall'app installata.
          </span>
        ) : null}
      </div>

      {ios && showSteps ? <IosInstallSteps /> : null}
    </Frame>
  );
}
