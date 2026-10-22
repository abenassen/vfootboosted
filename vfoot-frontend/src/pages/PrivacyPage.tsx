import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Card } from '../components/ui';
import logo from '../assets/logo.png';

/** INFORMATIVA PRIVACY — artt. 13-14 GDPR, e l'informativa sugli strumenti salvati
 *  nel browser che le Linee guida cookie del Garante (10/06/2021, §§ 5, 7.1, 7.2)
 *  chiedono quando ci sono SOLO strumenti tecnici o statistiche assimilate: niente
 *  banner, basta dirlo qui.
 *
 *  Perché niente banner. Nel browser salviamo solo ciò che serve a far funzionare
 *  l'app (il token di accesso, la lega scelta, il tema) e una sessione casuale per
 *  scheda usata dal registro delle pagine, che è di prima parte, produce solo
 *  statistiche aggregate su questo sito e non consente di risalire a una persona
 *  (niente utente, niente IP, niente orario: v. ``vfoot/models/usage.py``). Se un
 *  giorno entrasse uno strumento di terzi — un analytics esterno, un pixel — questa
 *  premessa cade e il banner diventa obbligatorio: va rivista QUESTA pagina insieme
 *  al codice, non dopo.
 *
 *  Il testo è scritto per chi lo legge, non per un giurista: cosa raccogliamo, a
 *  chi lo diamo, per quanto, e come farselo cancellare. Va fatto rileggere a chi
 *  conosce la materia prima di considerarlo definitivo.
 */

// Da completare prima di pubblicare: chi risponde dei dati e dove scrivergli.
const TITOLARE = '[DA COMPLETARE: nome e cognome o ragione sociale, città]';
const CONTATTO = '[DA COMPLETARE: indirizzo email]';
const AGGIORNATA = '22 ottobre 2026';

export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_20%_20%,#dbeafe_0%,#eff6ff_45%,#f8fafc_100%)] text-ink">
      <div className="mx-auto max-w-3xl px-4 py-8 pt-[calc(2rem_+_var(--vf-safe-top))] md:py-14 md:pt-[calc(3.5rem_+_var(--vf-safe-top))]">
        <div className="mb-6 flex items-center justify-between gap-3">
          <Link to="/" className="flex items-center gap-2.5 rounded-lg hover:opacity-80">
            <img src={logo} alt="Vfoot logo" className="h-9 w-9 rounded-lg object-cover shadow-card" />
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                Vfoot Boosted
              </div>
              <div className="text-sm font-black leading-tight">Il gioco sul calcio</div>
            </div>
          </Link>
          <Link
            to="/"
            className="shrink-0 rounded-xl bg-ink px-3.5 py-2 text-sm font-bold text-paper hover:opacity-90"
          >
            Entra
          </Link>
        </div>

        <header className="mb-5 space-y-3">
          <h1 className="text-3xl font-black leading-tight md:text-4xl">Privacy</h1>
          <p className="text-ink-soft md:text-lg">
            Quali dati teniamo, perché, a chi li affidiamo e come farteli cancellare. Niente
            pubblicità, niente profilazione, nessun dato venduto o ceduto a nessuno.
          </p>
          <p className="text-xs text-ink-faint">Ultimo aggiornamento: {AGGIORNATA}</p>
        </header>

        <div className="space-y-4">
          <Blocco titolo="Chi risponde dei tuoi dati">
            <p>
              Il titolare del trattamento è <b className="text-ink">{TITOLARE}</b>. Per qualunque
              domanda o richiesta sui tuoi dati scrivi a <b className="text-ink">{CONTATTO}</b>.
            </p>
          </Blocco>

          <Blocco titolo="Cosa raccogliamo">
            <ul className="list-disc space-y-1.5 pl-4 marker:text-ink-faint">
              <li>
                <b className="text-ink">L'account</b>: nome utente, email e password (salvata solo in
                forma cifrata, non la può leggere nessuno). Se entri con Google riceviamo da Google il
                tuo indirizzo email e un identificativo dell'account, nient'altro.
              </li>
              <li>
                <b className="text-ink">Il profilo</b>: l'avatar che componi. Il nome utente e l'avatar
                sono visibili agli altri iscritti con cui giochi.
              </li>
              <li>
                <b className="text-ink">Il gioco</b>: leghe, squadre, rose, formazioni, offerte,
                rilanci all'asta, scambi e decisioni di lega. Sono visibili agli altri membri della
                stessa lega, perché è così che il gioco funziona.
              </li>
              <li>
                <b className="text-ink">Le notifiche</b>, se le attivi: l'indirizzo a cui il tuo
                browser riceve le notifiche push, e il tipo di browser.
              </li>
              <li>
                <b className="text-ink">Le segnalazioni</b> che ci mandi dall'app: il testo, la pagina
                da cui scrivi, il tipo di browser e la dimensione dello schermo, per capire il
                problema.
              </li>
              <li>
                <b className="text-ink">Come si usano le pagine</b>: quali pagine dell'app vengono
                aperte e per quanto restano sullo schermo, se da telefono o computer, dall'app
                installata o dal browser. Queste righe <b className="text-ink">non sono collegate al
                tuo account</b>, non contengono il tuo indirizzo IP né l'ora, e servono solo a
                statistiche complessive per migliorare l'app. Non registriamo nulla di ciò che scrivi
                o di cosa guardi dentro una pagina.
              </li>
            </ul>
            <p>
              I voti, le statistiche e i dati delle partite riguardano i calciatori di Serie A e
              vengono da fonti sportive pubbliche: non sono dati su di te.
            </p>
          </Blocco>

          <Blocco titolo="Perché, e su quale base">
            <ul className="list-disc space-y-1.5 pl-4 marker:text-ink-faint">
              <li>
                Account, profilo, gioco e notifiche servono a <b className="text-ink">fornirti il
                servizio</b> che hai chiesto iscrivendoti (art. 6.1.b GDPR).
              </li>
              <li>
                Le email che ti mandiamo — conferma dell'indirizzo, recupero della password, avvisi
                della tua lega — fanno parte dello stesso servizio. Non mandiamo newsletter né
                pubblicità.
              </li>
              <li>
                Le segnalazioni e le statistiche sulle pagine servono a correggere errori e migliorare
                l'app: è un nostro <b className="text-ink">legittimo interesse</b> (art. 6.1.f), con
                dati ridotti al minimo e non riconducibili a te.
              </li>
              <li>
                Le copie di sicurezza e i registri tecnici del server servono a proteggere il servizio
                e a ripararlo quando si rompe (art. 6.1.f).
              </li>
            </ul>
          </Blocco>

          <Blocco titolo="Cosa salviamo nel tuo browser">
            <p>
              Non usiamo cookie di profilazione, pubblicità o analytics di terzi, quindi non ti
              chiediamo un consenso con un banner. Nel browser salviamo solo ciò che serve a far
              funzionare l'app:
            </p>
            <ul className="list-disc space-y-1.5 pl-4 marker:text-ink-faint">
              <li>il gettone che ti tiene connesso, finché non esci;</li>
              <li>
                le tue scelte: lega e stagione selezionate, tema chiaro o scuro, notifiche sì o no,
                avvisi già chiusi, un invito a una lega rimasto in sospeso;
              </li>
              <li>
                una sessione casuale che dura quanto la scheda aperta, usata solo per le statistiche
                sulle pagine descritte sopra;
              </li>
              <li>una copia dell'app, perché si apra anche con la rete lenta o assente.</li>
            </ul>
            <p>
              Il pulsante «Accedi con Google» viene caricato da Google, che lo gestisce secondo la
              propria informativa.
            </p>
          </Blocco>

          <Blocco titolo="A chi li affidiamo">
            <p>I tuoi dati non vengono venduti né ceduti. Li trattano per nostro conto solo:</p>
            <ul className="list-disc space-y-1.5 pl-4 marker:text-ink-faint">
              <li>
                <b className="text-ink">Akamai (Linode)</b>, che ospita il server, in un centro dati a
                Francoforte, in Germania;
              </li>
              <li>
                <b className="text-ink">Brevo</b> (Francia), che recapita le nostre email;
              </li>
              <li>
                <b className="text-ink">Google</b>, se scegli di entrare con il tuo account Google;
              </li>
              <li>
                il servizio di notifiche del tuo browser (Google, Apple o Mozilla), se attivi le
                notifiche: riceve il testo della notifica per consegnartela.
              </li>
            </ul>
            <p>
              Alcuni di questi fornitori sono gruppi con sede negli Stati Uniti. Quando un dato può
              uscire dall'Unione Europea, il trasferimento avviene con le garanzie previste dal GDPR
              (decisione di adeguatezza UE-USA o clausole contrattuali standard).
            </p>
          </Blocco>

          <Blocco titolo="Per quanto li teniamo">
            <ul className="list-disc space-y-1.5 pl-4 marker:text-ink-faint">
              <li>account, profilo e dati di gioco: finché hai l'account;</li>
              <li>statistiche sulle pagine: 180 giorni, poi si cancellano da sole;</li>
              <li>copie di sicurezza: 21 giorni;</li>
              <li>registri tecnici del server: poche settimane;</li>
              <li>segnalazioni: finché servono a risolvere il problema che descrivono.</li>
            </ul>
          </Blocco>

          <Blocco titolo="I tuoi diritti">
            <p>
              Puoi chiederci in qualunque momento di vedere i dati che abbiamo su di te, di
              correggerli, di cancellarli insieme all'account, di riceverne una copia, o di opporti a
              un trattamento basato sul nostro legittimo interesse. Basta scrivere a{' '}
              <b className="text-ink">{CONTATTO}</b>: rispondiamo entro un mese.
            </p>
            <p>
              Se pensi che trattiamo i tuoi dati in modo scorretto puoi rivolgerti al{' '}
              <a
                href="https://www.garanteprivacy.it"
                target="_blank"
                rel="noreferrer"
                className="font-semibold text-accent underline decoration-dotted"
              >
                Garante per la protezione dei dati personali
              </a>
              .
            </p>
          </Blocco>
        </div>
      </div>
    </div>
  );
}

function Blocco({ titolo, children }: { titolo: string; children: ReactNode }) {
  return (
    <Card className="p-5">
      <h2 className="font-cond text-xl font-bold text-ink">{titolo}</h2>
      <div className="mt-2 space-y-3 text-sm leading-relaxed text-ink-soft">{children}</div>
    </Card>
  );
}
