import { crestColor, defaultCrest, parseCrest } from '../utils/crest';

/** LA MAGLIA DELLA SQUADRA, presa dai colori del suo stemma.
 *
 *  Non dal club reale del giocatore: quegli undici sono UNA squadra, la tua, e
 *  colorarli per ruolo li faceva sembrare quattro squadre diverse scese in campo
 *  insieme. Il club vero non ha niente da dire su una formazione di fantacalcio —
 *  la partita che gioca sta nella scheda, dove serve.
 *
 *  E i colori sono quelli che il fantallenatore si è scelto da solo componendo lo
 *  stemma: nessun dato nuovo da procurarsi, nessuna tabella di vent'anni voci da
 *  riaggiornare ogni estate con promosse e retrocesse, e soprattutto nessuna
 *  questione di marchi — di una maglia vera non c'è niente qui dentro. */

export type Kit = {
  /** Il corpo della maglia. */
  body: string;
  /** Colletto e polsini. */
  trim: string;
  /** Le iniziali sul petto. */
  ink: string;
  /** Il filo attorno alla sagoma: è ciò che la stacca dal prato, ed è il motivo
   *  per cui chi si sceglie uno stemma verde bottiglia resta comunque visibile. */
  outline: string;
};

/** Luminanza relativa sRGB. Serve a decidere due cose per contrasto invece che
 *  per lista di colori vietati: da che parte sta il filo, e se le iniziali si
 *  leggono sul corpo. */
function luminance(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return 0.5;
  const n = parseInt(m[1], 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}

function kit(body: string, trim: string): Kit {
  const lb = luminance(body);
  const contrast = lb > 0.5 ? '#0f172a' : '#ffffff';
  return {
    body,
    trim,
    // Il secondario se davvero si distingue dal corpo, altrimenti bianco o nero:
    // il costruttore dello stemma non impedisce di sceglierne due vicini, e due
    // iniziali illeggibili sono peggio di due iniziali di un colore non scelto.
    ink: Math.abs(luminance(trim) - lb) > 0.22 ? trim : contrast,
    outline: contrast,
  };
}

/** Le due mute della squadra. Quella del portiere sono gli stessi due colori
 *  invertiti — come nel calcio vero, e con una garanzia in regalo: il costruttore
 *  dello stemma obbliga già a sceglierne due che si distinguano fra loro, quindi
 *  il portiere NON PUÒ confondersi con i compagni. L'anello ambra che faceva quel
 *  lavoro era una toppa su un problema che questa impostazione non ha. */
export function kitFromCrest(
  descriptor: string | null | undefined,
  teamName: string | null | undefined,
): { outfield: Kit; keeper: Kit } {
  const o = parseCrest(descriptor) ?? defaultCrest(teamName);
  const primary = crestColor(o.primary, '1e3a8a');
  const secondary = crestColor(o.secondary, 'ffffff');
  return { outfield: kit(primary, secondary), keeper: kit(secondary, primary) };
}

/** La sagoma, in un riquadro 24×24: spalle, maniche, scollo a V. */
const SHIRT =
  'M9.4 2.4 L6.1 3.3 L1.9 7.5 L5.5 10.7 L5.5 21.5 L18.5 21.5 L18.5 10.7 L22.1 7.5 '
  + 'L17.9 3.3 L14.6 2.4 C13.6 4.6 10.4 4.6 9.4 2.4 Z';
/** I polsini: due tratti corti in fondo alle maniche. */
const CUFF_L = 'M2.6 8.2 L5.0 10.3';
const CUFF_R = 'M21.4 8.2 L19.0 10.3';
/** Il colletto, che segue lo scollo. */
const COLLAR = 'M9.4 2.4 C10.4 4.6 13.6 4.6 14.6 2.4';

export function Jersey({
  kit: k,
  label,
  size = 30,
  dashed = false,
  className,
}: {
  kit?: Kit;
  /** Le iniziali sul petto; vuoto su una maglia tratteggiata. */
  label?: string;
  size?: number;
  /** Il posto che aspetta qualcuno: solo la sagoma, vuota. */
  dashed?: boolean;
  className?: string;
}) {
  if (dashed) {
    return (
      <svg viewBox="0 0 24 24" width={size} height={size} className={className} aria-hidden>
        <path
          d={SHIRT}
          fill="rgba(255,255,255,0.14)"
          stroke="rgba(255,255,255,0.85)"
          strokeWidth="1.4"
          strokeDasharray="2.4 2"
          strokeLinejoin="round"
        />
        <path d="M12 9.5 v6 M9 12.5 h6" stroke="rgba(255,255,255,0.9)" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    );
  }
  const c = k ?? kit('#1e3a8a', '#ffffff');
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} aria-hidden>
      <path d={SHIRT} fill={c.body} stroke={c.outline} strokeWidth="1" strokeLinejoin="round" />
      <path d={COLLAR} fill="none" stroke={c.trim} strokeWidth="1.6" strokeLinecap="round" />
      <path d={CUFF_L} fill="none" stroke={c.trim} strokeWidth="2" strokeLinecap="round" />
      <path d={CUFF_R} fill="none" stroke={c.trim} strokeWidth="2" strokeLinecap="round" />
      {label ? (
        <text
          x="12"
          y="17.4"
          textAnchor="middle"
          fill={c.ink}
          style={{ font: '700 7.4px Barlow, ui-sans-serif, sans-serif', letterSpacing: '-0.2px' }}
        >
          {label}
        </text>
      ) : null}
    </svg>
  );
}

export default Jersey;
