import { useEffect, useState } from 'react';
import logo from '../assets/logo.png';
import { applyUpdate, onUpdateReady } from '../pwa/registerSW';

/** IL CARTELLO DELL'APERTURA — pagina temporanea, fatta per essere cancellata.
 *
 *  Sta davanti alla sola porta d'ingresso (`/`) e solo per chi non ha una
 *  sessione: le API, i link d'invito e chi è già dentro non la incontrano mai.
 *  All'ora dell'apertura si toglie da sé — a deciderlo è l'orologio, non un
 *  deploy — quindi passata quella non resta niente da fare: quando si vorrà,
 *  si cancella questo file e in App.tsx tornano le due righe di prima.
 *
 *  Per lo stesso motivo è tutta qui dentro, colori e animazioni comprese,
 *  invece di passare dai token del tema come il resto del sito: è l'unica
 *  pagina che non deve somigliare alle altre, e va via in un colpo solo. */

/** L'istante dell'apertura, con il fuso scritto: `+02:00` è l'ora legale
 *  italiana, e senza di lui «17:00» significherebbe un'ora diversa per ogni
 *  browser che apre la pagina. */
export const LAUNCH_AT = Date.parse('2026-08-13T17:00:00+02:00');

export function isLaunched(): boolean {
  return Date.now() >= LAUNCH_AT;
}

/** LA CHIAVE DI CHI FA IL SITO: `vfoot.it/?entra`, e nient'altro. Non è scritta
 *  da nessuna parte nella pagina di proposito — un link «hai già un account?»
 *  c'era, e faceva saltare il conto alla rovescia a chiunque ci passasse sopra,
 *  che è esattamente ciò che il cartello serve a non far succedere.
 *
 *  Chi ha già una sessione non ne ha comunque bisogno: entra e basta. Serve nel
 *  caso opposto — sessione scaduta prima dell'ora — e vale per la scheda aperta
 *  e basta. Resta una cortesia, non una serratura: chi conosce l'indirizzo entra
 *  lo stesso, e a chiudere davvero sarebbe nginx, non questa pagina. */
const BYPASS_KEY = 'vfoot.apertura.entra';

export function wantsBypass(): boolean {
  try {
    if (new URLSearchParams(window.location.search).has('entra')) rememberBypass();
    return window.sessionStorage.getItem(BYPASS_KEY) === '1';
  } catch {
    // sessionStorage può lanciare (navigazione privata, cookie di terze parti
    // bloccati): senza scorciatoia si vede il conto alla rovescia, non un errore.
    return false;
  }
}

export function rememberBypass(): void {
  try {
    window.sessionStorage.setItem(BYPASS_KEY, '1');
  } catch {
    /* vedi sopra */
  }
}

const HOUR_FMT = new Intl.DateTimeFormat('it-IT', {
  timeZone: 'Europe/Rome',
  hour: '2-digit',
  minute: '2-digit',
});
const DAY_FMT = new Intl.DateTimeFormat('it-IT', {
  timeZone: 'Europe/Rome',
  weekday: 'long',
  day: 'numeric',
  month: 'long',
});

/** «oggi alle 17:00», e la data intera se per qualsiasi ragione l'apertura non
 *  è più oggi: l'ora da sola, letta domani, sarebbe una bugia. */
function launchLabel(): string {
  const launch = new Date(LAUNCH_AT);
  const sameDay = DAY_FMT.format(launch) === DAY_FMT.format(new Date());
  const when = sameDay ? 'oggi' : DAY_FMT.format(launch);
  return `${when} alle ${HOUR_FMT.format(launch)}`;
}

/** La finestra su cui si riempie la barra: le ultime ventiquattr'ore. */
const WINDOW_MS = 24 * 60 * 60 * 1000;

function useRemaining(): number {
  const [remaining, setRemaining] = useState(() => LAUNCH_AT - Date.now());
  useEffect(() => {
    // Quattro volte al secondo, non una: un intervallo da mille millisecondi si
    // sfasa e ogni tanto salta un secondo sullo schermo.
    const id = window.setInterval(() => setRemaining(LAUNCH_AT - Date.now()), 250);
    return () => window.clearInterval(id);
  }, []);
  return remaining;
}

export default function CountdownPage({ onOpen }: { onOpen: () => void }) {
  const remaining = useRemaining();
  const done = remaining <= 0;
  const label = launchLabel();

  useEffect(() => {
    const previous = document.title;
    document.title = `Vfoot Boosted — si apre ${label}`;
    return () => {
      document.title = previous;
    };
  }, [label]);

  /** IL CARTELLO SI AGGIORNA DA SOLO, senza chiedere.
   *
   *  Ovunque nell'app l'aggiornamento è una scelta dell'utente (UpdateBanner):
   *  ricaricare sotto chi sta rilanciando a un'asta sarebbe peggio che restare
   *  indietro di una versione. Qui non c'è niente da perdere in un
   *  ricaricamento — e soprattutto questa pagina sta FUORI dall'app, quindi
   *  quel banner non la raggiunge: chi l'aveva aperta una volta restava sulla
   *  copia del service worker per sempre. È già successo il 13/08/2026, con una
   *  correzione al testo che sembrava non arrivare mentre il server la serviva
   *  da un pezzo. */
  useEffect(() => onUpdateReady((ready) => ready && applyUpdate()), []);

  // Passata l'ora: qualche secondo di festa, poi la pagina si fa da parte anche
  // se nessuno tocca il pulsante — una scheda lasciata aperta deve ritrovarsi
  // l'app, non un cartello scaduto.
  useEffect(() => {
    if (!done) return;
    const id = window.setTimeout(onOpen, 9000);
    return () => window.clearTimeout(id);
  }, [done, onOpen]);

  const left = Math.max(0, remaining);
  const days = Math.floor(left / 86_400_000);
  const hours = Math.floor(left / 3_600_000) % 24;
  const minutes = Math.floor(left / 60_000) % 60;
  const seconds = Math.floor(left / 1000) % 60;

  const progress = Math.min(100, Math.max(0, ((WINDOW_MS - left) / WINDOW_MS) * 100));

  return (
    <div className="vfc">
      <style>{CSS}</style>

      <div className="vfc-sky" />
      <div className="vfc-beam" />
      <div className="vfc-beam vfc-beam--b" />
      <div className="vfc-pitch">
        <div className="vfc-halfline" />
        <div className="vfc-circle" />
      </div>
      <div className="vfc-horizon" />
      <div className="vfc-vignette" />
      {done ? <div className="vfc-flare" /> : null}

      <main className="vfc-content">
        <span className="vfc-kicker">
          <i className="vfc-dot" />
          {done ? 'siamo online' : 'in apertura'}
        </span>

        <img src={logo} alt="" className="vfc-logo" />

        <h1 className="vfc-title">
          Vfoot
          <br />
          Boosted
        </h1>

        <p className="vfc-claim">
          Il gioco sul calcio con i voti indipendenti calcolati dai dati veri di ogni
          partita di Serie A.
        </p>

        {done ? (
          <>
            <p className="vfc-open">È aperto.</p>
            <button type="button" className="vfc-cta" onClick={onOpen}>
              Entra ora
            </button>
          </>
        ) : (
          <>
            {/* Le cifre cambiano ogni secondo: a un lettore di schermo verrebbero
                rilette da capo per ore. Il conto è decorazione, la frase sotto è
                l'informazione — e quella è l'unica cosa che viene annunciata. */}
            <div className="vfc-tiles" aria-hidden="true">
              {days > 0 ? <Tile value={days} unit={days === 1 ? 'giorno' : 'giorni'} /> : null}
              <Tile value={hours} unit="ore" />
              <Tile value={minutes} unit="min" />
              <Tile value={seconds} unit="sec" />
            </div>

            <div className="vfc-rail">
              <span style={{ width: `${progress}%` }} />
            </div>

            <p className="vfc-when">
              Si apre <b>{label}</b>
            </p>
          </>
        )}

        <div className="vfc-chips">
          <span className="vfc-chip vfc-chip--on">Classic · pronta</span>
          <span className="vfc-chip">Aura · in arrivo</span>
        </div>
      </main>
    </div>
  );
}

function Tile({ value, unit }: { value: number; unit: string }) {
  const text = String(value).padStart(2, '0');
  return (
    <div className="vfc-tile">
      {/* `key` sul valore: cambiando cifra l'elemento è nuovo, quindi l'animazione
          d'ingresso riparte — è così che il numero "scatta" invece di sostituirsi. */}
      <span key={text} className="vfc-num">
        {text}
      </span>
      <span className="vfc-unit">{unit}</span>
    </div>
  );
}

const CSS = `
.vfc {
  position: relative;
  min-height: 100vh;
  min-height: 100dvh;
  overflow: hidden;
  background: #04120b;
  color: #eaf7ef;
  isolation: isolate;
}

/* IL CIELO — due luci lontane su fondo notte. */
.vfc-sky, .vfc-vignette, .vfc-beam, .vfc-pitch { position: absolute; pointer-events: none; }
.vfc-sky {
  inset: 0;
  background:
    radial-gradient(1100px 620px at 50% -12%, rgba(46,204,113,.30), transparent 62%),
    radial-gradient(900px 520px at 88% 108%, rgba(56,189,248,.22), transparent 60%),
    linear-gradient(180deg, #04120b 0%, #030d14 55%, #04120b 100%);
}

/* I FARI: due lame di luce che oscillano piano sopra il campo. */
.vfc-beam {
  top: -34vh;
  left: 50%;
  width: 62vw;
  height: 124vh;
  transform-origin: 50% 0;
  filter: blur(30px);
  background: linear-gradient(180deg, rgba(46,204,113,.18), transparent 70%);
  animation: vfc-sweep 15s ease-in-out infinite alternate;
}
.vfc-beam--b {
  background: linear-gradient(180deg, rgba(56,189,248,.16), transparent 70%);
  animation-duration: 21s;
  animation-direction: alternate-reverse;
}
@keyframes vfc-sweep {
  from { transform: translateX(-50%) rotate(-17deg); }
  to   { transform: translateX(-50%) rotate(17deg); }
}

/* IL CAMPO in prospettiva: le bande dell'erba, la linea di metà campo e il
   cerchio, sfumati verso l'alto perché non disturbino il testo. */
.vfc-pitch {
  left: -30%;
  right: -30%;
  bottom: -4vh;
  height: 52vh;
  transform: perspective(560px) rotateX(71deg);
  transform-origin: bottom center;
  background:
    repeating-linear-gradient(90deg, rgba(255,255,255,.075) 0 72px, rgba(255,255,255,0) 72px 144px),
    linear-gradient(0deg, rgba(18,161,80,.85), rgba(18,161,80,.18) 55%, rgba(18,161,80,.02) 80%, transparent);
  -webkit-mask-image: linear-gradient(to top, #000 10%, transparent 94%);
  mask-image: linear-gradient(to top, #000 10%, transparent 94%);
}
/* L'ORIZZONTE: la riga di luce dove il campo finisce e comincia la notte. È lei
   a far leggere il piano inclinato come un campo visto dalla tribuna. */
.vfc-horizon {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 15vh;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(125,211,252,.3), rgba(46,204,113,.5), rgba(125,211,252,.3), transparent);
  box-shadow: 0 0 40px 5px rgba(46,204,113,.18);
  pointer-events: none;
}
.vfc-circle {
  position: absolute;
  left: 50%;
  bottom: 8%;
  width: 34vw;
  height: 34vw;
  margin-left: -17vw;
  border: 2px solid rgba(255,255,255,.12);
  border-radius: 50%;
}
.vfc-halfline {
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(8% + 17vw);
  height: 2px;
  background: rgba(255,255,255,.09);
}

.vfc-vignette {
  inset: 0;
  background: radial-gradient(125% 95% at 50% 42%, transparent 38%, rgba(0,0,0,.62) 100%);
}

/* IL CONTENUTO */
.vfc-content {
  position: relative;
  z-index: 1;
  display: flex;
  min-height: 100vh;
  min-height: 100dvh;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1.1rem;
  /* La pagina occupa lo schermo intero anche sotto l'orologio, quando è
     installata: il respiro in cima e in fondo si somma alla sua riserva. */
  padding: calc(2.5rem + var(--vf-safe-top)) 1.25rem calc(2.5rem + var(--vf-safe-bottom));
  text-align: center;
  animation: vfc-enter .9s cubic-bezier(.2,.8,.2,1) both;
}
@keyframes vfc-enter {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: none; }
}

.vfc-kicker {
  display: inline-flex;
  align-items: center;
  gap: .55rem;
  border: 1px solid rgba(255,255,255,.14);
  border-radius: 999px;
  background: rgba(255,255,255,.05);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
  padding: .35rem .85rem;
  font-size: .68rem;
  font-weight: 600;
  letter-spacing: .26em;
  text-transform: uppercase;
  color: #bfe8d2;
}
.vfc-dot {
  width: .45rem;
  height: .45rem;
  border-radius: 50%;
  background: #2ecc71;
  box-shadow: 0 0 12px #2ecc71;
  animation: vfc-pulse 1.9s ease-in-out infinite;
}
@keyframes vfc-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: .35; transform: scale(.72); }
}

.vfc-logo {
  width: clamp(3.4rem, 14vw, 4.6rem);
  height: clamp(3.4rem, 14vw, 4.6rem);
  border-radius: 1.1rem;
  object-fit: cover;
  border: 1px solid rgba(255,255,255,.16);
  box-shadow: 0 24px 60px -24px rgba(46,204,113,.85);
}

.vfc-title {
  margin: -.2rem 0 0;
  font-family: 'Barlow Condensed', 'Barlow', ui-sans-serif, system-ui, sans-serif;
  font-weight: 700;
  text-transform: uppercase;
  line-height: .9;
  letter-spacing: .01em;
  font-size: clamp(3rem, 15vw, 6.5rem);
  /* La sfumatura è larga il doppio del testo e scorre: è il riflesso che passa
     sulle scritte delle grafiche televisive, ed è tutto ciò che serve perché il
     titolo non stia fermo come un'immagine. */
  background: linear-gradient(100deg, #eafff3 0%, #6ee7a8 30%, #7dd3fc 50%, #6ee7a8 70%, #eafff3 100%);
  background-size: 220% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: vfc-shine 9s ease-in-out infinite alternate;
}
@keyframes vfc-shine {
  from { background-position: 0% 50%; }
  to   { background-position: 100% 50%; }
}

.vfc-claim {
  max-width: 34rem;
  margin: 0;
  font-size: clamp(.95rem, 3.6vw, 1.1rem);
  line-height: 1.5;
  color: rgba(234,247,239,.72);
}

/* IL CONTO */
.vfc-tiles {
  display: flex;
  gap: clamp(.45rem, 2.4vw, .9rem);
  margin-top: .4rem;
}
.vfc-tile {
  min-width: clamp(4.4rem, 23vw, 7rem);
  padding: .55rem .3rem .5rem;
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 1.25rem;
  background: linear-gradient(180deg, rgba(255,255,255,.11), rgba(255,255,255,.02));
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
  box-shadow: 0 30px 60px -34px rgba(0,0,0,.95), inset 0 1px 0 rgba(255,255,255,.16);
  overflow: hidden;
}
.vfc-num {
  display: block;
  font-family: 'Barlow Condensed', 'Barlow', ui-sans-serif, system-ui, sans-serif;
  font-weight: 700;
  font-size: clamp(2.4rem, 12vw, 4.4rem);
  line-height: 1;
  font-variant-numeric: tabular-nums;
  color: #fff;
  text-shadow: 0 0 28px rgba(46,204,113,.4);
  animation: vfc-tick .45s cubic-bezier(.2,.9,.2,1) both;
}
@keyframes vfc-tick {
  from { opacity: 0; transform: translateY(-32%) scale(.96); filter: blur(3px); }
  to   { opacity: 1; transform: none; filter: none; }
}
.vfc-unit {
  display: block;
  margin-top: .2rem;
  font-size: .6rem;
  font-weight: 600;
  letter-spacing: .28em;
  text-transform: uppercase;
  color: #9fc7b1;
}

.vfc-rail {
  position: relative;
  width: min(26rem, 80vw);
  height: 3px;
  border-radius: 999px;
  background: rgba(255,255,255,.10);
  overflow: hidden;
}
.vfc-rail span {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  border-radius: 999px;
  background: linear-gradient(90deg, #12a150, #2ecc71 60%, #7dd3fc);
  box-shadow: 0 0 18px rgba(46,204,113,.6);
  transition: width 1s linear;
}

.vfc-when {
  margin: 0;
  font-size: .95rem;
  color: rgba(234,247,239,.72);
}
.vfc-when b { color: #eafff3; }

/* L'APERTURA */
.vfc-flare {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 62vmax;
  height: 62vmax;
  margin: -31vmax;
  border-radius: 50%;
  pointer-events: none;
  background: radial-gradient(circle, rgba(46,204,113,.55), rgba(125,211,252,.18) 45%, transparent 62%);
  animation: vfc-flare 1.8s ease-out both;
}
@keyframes vfc-flare {
  from { opacity: .95; transform: scale(.18); }
  to   { opacity: 0; transform: scale(2.6); }
}
.vfc-open {
  margin: .2rem 0 0;
  font-family: 'Barlow Condensed', 'Barlow', ui-sans-serif, system-ui, sans-serif;
  font-size: clamp(1.6rem, 7vw, 2.4rem);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: #eafff3;
}
.vfc-cta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 999px;
  padding: .85rem 1.7rem;
  font: inherit;
  font-size: 1rem;
  font-weight: 700;
  color: #04120b;
  cursor: pointer;
  background: linear-gradient(90deg, #2ecc71, #7dd3fc);
  box-shadow: 0 20px 44px -18px rgba(46,204,113,.9);
  transition: filter .15s ease, transform .15s ease;
}
.vfc-cta:hover { filter: brightness(1.08); }
.vfc-cta:active { transform: scale(.98); }

/* IL PIEDE */
.vfc-chips {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: .5rem;
  margin-top: .3rem;
}
.vfc-chip {
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 999px;
  padding: .3rem .75rem;
  font-size: .72rem;
  font-weight: 600;
  letter-spacing: .04em;
  color: rgba(234,247,239,.6);
}
.vfc-chip--on {
  border-color: rgba(46,204,113,.45);
  background: rgba(46,204,113,.12);
  color: #9ff0c1;
}

.vfc button:focus-visible {
  outline: 2px solid #7dd3fc;
  outline-offset: 3px;
}
`;
