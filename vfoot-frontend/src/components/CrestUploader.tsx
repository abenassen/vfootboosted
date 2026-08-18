import { useCallback, useEffect, useId, useRef, useState } from 'react';
import clsx from 'clsx';
import { uploadCrestImage } from '../api';
import Crest from './Crest';
import { Button } from './ui';
import {
  CREST_COLORS,
  CREST_SHAPES,
  CREST_SHAPE_LABELS,
  crestColor,
  serializeCrest,
  type CrestOptions,
  type CrestShape,
} from '../utils/crest';

/** Choose a picture, frame it, upload it.
 *
 *  The frame is square and the output is fixed at 256×256, so there is no aspect
 *  ratio to negotiate: pan and zoom are the whole interaction. Written by hand
 *  rather than pulling in a cropping library — the only genuinely awkward part
 *  is dragging on touch, and pointer events cover mouse and finger with the same
 *  three handlers.
 *
 *  The browser downscales BEFORE uploading, so what leaves the phone is ~15 KB
 *  instead of a 4 MB photo — which matters on a train, and matters more on a
 *  server with one vCPU. The server re-encodes anyway: this is a courtesy, not a
 *  control. Nothing here is trusted over there.
 */

// Il lato del riquadro a schermo. L'uscita è sempre 256, indipendentemente da
// questo: il rapporto fra i due è l'unica cosa che serve per riprodurre il
// ritaglio sul canvas finale.
const VIEW = 240;
const OUT = 256;

// Prima ancora di leggerlo. Il server si ferma a 2 MB DOPO la ricodifica del
// client, quindi qui il tetto serve solo a non far masticare al browser una
// fotografia da venti megapixel per poi buttarla.
const MAX_SOURCE_BYTES = 25 * 1024 * 1024;

const ACCEPTED = 'image/png,image/jpeg,image/webp,image/gif';

type Frame = { scale: number; x: number; y: number };

/** L'immagine ha pixel trasparenti?
 *
 *  Si misura una volta sul file scelto, non a ogni fotogramma: la trasparenza è
 *  una proprietà del file, e leggere 65.000 pixel a ogni pixel di trascinamento
 *  sarebbe lavoro buttato. Il campione a 64×64 basta: una figura ritagliata ha
 *  aree trasparenti grandi, non pixel sparsi.
 *
 *  La sorgente è un blob URL nato da un File, quindi il canvas non è "sporcato"
 *  e `getImageData` si può leggere. Il try/catch è per il caso che non lo sia
 *  comunque: in dubbio rispondiamo "sì", che è la risposta che mostra il
 *  comando invece di nasconderlo. */
function rilevaTrasparenza(img: HTMLImageElement): boolean {
  try {
    const c = document.createElement('canvas');
    c.width = 64;
    c.height = 64;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    if (!ctx) return true;
    ctx.drawImage(img, 0, 0, 64, 64);
    const { data } = ctx.getImageData(0, 0, 64, 64);
    for (let i = 3; i < data.length; i += 4) {
      if (data[i] < 250) return true;
    }
    return false;
  } catch {
    return true;
  }
}

export default function CrestUploader({
  value,
  teamName,
  onChange,
  onPendingChange,
}: {
  value: CrestOptions;
  teamName: string;
  onChange: (next: CrestOptions) => void;
  /** Riceve la funzione che carica il ritaglio in corso, oppure null.
   *
   *  Esiste perché il caricamento NON deve essere un gesto a sé: chi ritaglia
   *  una foto e preme Salva ha finito, e un passo intermedio obbligatorio è solo
   *  un modo di far perdere il lavoro a chi non lo indovina. Il genitore tiene
   *  questa funzione e la esegue dentro il proprio salvataggio, così l'immagine
   *  parte quando parte tutto il resto — e non parte affatto se si annulla. */
  onPendingChange?: (commit: (() => Promise<string>) | null) => void;
}) {
  const [source, setSource] = useState<HTMLImageElement | null>(null);
  const [frame, setFrame] = useState<Frame>({ scale: 1, x: 0, y: 0 });
  const [minScale, setMinScale] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const dragRef = useRef<{ id: number; x: number; y: number } | null>(null);

  // Il ritaglio corrente come data URI. Sta qui e non dentro l'anteprima perché
  // adesso lo usano in due — il riquadro «Come verrà» e le miniature della
  // forma — e calcolarlo due volte vorrebbe dire due encode a ogni pixel di
  // trascinamento.
  const [previewUrl, setPreviewUrl] = useState('');

  // true/false quando l'abbiamo misurato sul file scelto; null quando l'immagine
  // c'è già ma non l'abbiamo vista passare da qui (editor riaperto in seguito).
  // Decide se ha senso mostrare il colore di sfondo: senza trasparenza quel
  // colore non si vede da nessuna parte, e sarebbe un comando che non fa niente.
  const [hasAlpha, setHasAlpha] = useState<boolean | null>(null);

  // Il ritaglio corrente specchiato in un ref: la funzione consegnata al
  // genitore deve restare LA STESSA mentre si trascina (altrimenti si
  // riregistra a ogni pixel), ma deve leggere l'ultimo stato quando viene
  // eseguita, non quello di quando è nata.
  const liveRef = useRef<{ source: HTMLImageElement | null; frame: Frame }>({
    source: null,
    frame: { scale: 1, x: 0, y: 0 },
  });
  useEffect(() => {
    liveRef.current = { source, frame };
  });

  // Il limite di scorrimento: l'immagine deve coprire il riquadro in ogni
  // posizione, altrimenti si vedrebbe il fondo e il ritaglio mentirebbe su cosa
  // finirà nello stemma.
  const clamp = useCallback((img: HTMLImageElement, f: Frame): Frame => {
    const w = img.naturalWidth * f.scale;
    const h = img.naturalHeight * f.scale;
    const maxX = Math.max(0, (w - VIEW) / 2);
    const maxY = Math.max(0, (h - VIEW) / 2);
    return {
      scale: f.scale,
      x: Math.min(maxX, Math.max(-maxX, f.x)),
      y: Math.min(maxY, Math.max(-maxY, f.y)),
    };
  }, []);

  /** Il riquadro visibile, ridisegnato a 256×256: è ESATTAMENTE ciò che parte.
   *  Una sola definizione della trasformazione, usata dall'anteprima e dal
   *  caricamento — se divergessero, l'utente vedrebbe una cosa e ne manderebbe
   *  un'altra. */
  const renderOut = useCallback(
    (img: HTMLImageElement, f: Frame): HTMLCanvasElement | null => {
      const c = document.createElement('canvas');
      c.width = OUT;
      c.height = OUT;
      const ctx = c.getContext('2d');
      if (!ctx) return null;
      const k = OUT / VIEW;
      const w = img.naturalWidth * f.scale * k;
      const h = img.naturalHeight * f.scale * k;
      ctx.drawImage(img, OUT / 2 - w / 2 + f.x * k, OUT / 2 - h / 2 + f.y * k, w, h);
      return c;
    },
    [],
  );

  useEffect(() => {
    if (!source) {
      setPreviewUrl('');
      return;
    }
    const c = renderOut(source, frame);
    if (c) setPreviewUrl(c.toDataURL('image/png'));
  }, [source, frame, renderOut]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !source) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, VIEW, VIEW);
    // Il fondo dello stemma anche qui, non il grigio del pannello: con
    // un'immagine trasparente si inquadra guardando quello che ci sarà dietro.
    // Un riquadro di ritaglio che mostra un colore diverso dal risultato fa
    // scegliere l'inquadratura sbagliata.
    ctx.fillStyle = crestColor(value.primary, '1e3a8a');
    ctx.fillRect(0, 0, VIEW, VIEW);
    const w = source.naturalWidth * frame.scale;
    const h = source.naturalHeight * frame.scale;
    ctx.drawImage(source, VIEW / 2 - w / 2 + frame.x, VIEW / 2 - h / 2 + frame.y, w, h);
  }, [source, frame, value.primary]);

  useEffect(() => {
    draw();
  }, [draw]);

  function pick(file: File | undefined) {
    setError(null);
    if (!file) return;
    if (file.size > MAX_SOURCE_BYTES) {
      setError('Immagine troppo grande: scegline una sotto i 25 MB.');
      return;
    }
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      setHasAlpha(rilevaTrasparenza(img));
      // Lo zoom minimo è quello che copre il riquadro: sotto, resterebbe del
      // vuoto ai lati.
      const cover = Math.max(VIEW / img.naturalWidth, VIEW / img.naturalHeight);
      setMinScale(cover);
      setFrame({ scale: cover, x: 0, y: 0 });
      setSource(img);
      URL.revokeObjectURL(url);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      setError('Non riesco ad aprire questo file come immagine.');
    };
    img.src = url;
  }

  function onPointerDown(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!source) return;
    (e.target as HTMLCanvasElement).setPointerCapture(e.pointerId);
    dragRef.current = { id: e.pointerId, x: e.clientX, y: e.clientY };
  }

  function onPointerMove(e: React.PointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current;
    if (!drag || !source || drag.id !== e.pointerId) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    dragRef.current = { id: e.pointerId, x: e.clientX, y: e.clientY };
    setFrame((f) => clamp(source, { ...f, x: f.x + dx, y: f.y + dy }));
  }

  function onPointerUp(e: React.PointerEvent<HTMLCanvasElement>) {
    if (dragRef.current?.id === e.pointerId) dragRef.current = null;
  }

  function zoomTo(scale: number) {
    if (!source) return;
    // Lo scorrimento si scala insieme allo zoom, così il punto al centro resta
    // al centro invece di scappare via mentre si ingrandisce.
    setFrame((f) => {
      const k = scale / f.scale;
      return clamp(source, { scale, x: f.x * k, y: f.y * k });
    });
  }

  /** Carica il ritaglio corrente e restituisce la sua impronta.
   *
   *  Non tocca il descrittore e non chiude niente: la esegue il salvataggio del
   *  genitore, che è l'unico posto dove ha senso decidere cosa farne. */
  const commit = useCallback(async (): Promise<string> => {
    const { source: img, frame: f } = liveRef.current;
    if (!img) return '';
    const out = renderOut(img, f);
    if (!out) throw new Error('Il browser non mi lascia disegnare l\'immagine.');

    const blob = await new Promise<Blob | null>((resolve) =>
      // WebP con ricaduta su PNG: Safari lo esporta solo dalle versioni
      // recenti, e un toBlob non supportato non fallisce — restituisce un PNG
      // senza dirlo. Va bene: il server ricodifica comunque.
      out.toBlob((b) => resolve(b), 'image/webp', 0.9),
    );
    if (!blob) throw new Error('Non sono riuscito a preparare l\'immagine.');

    const { hash } = await uploadCrestImage(blob);
    return hash;
  }, [renderOut]);

  useEffect(() => {
    onPendingChange?.(source ? commit : null);
  }, [source, commit, onPendingChange]);

  const descriptor = serializeCrest(value);

  return (
    <div className="space-y-4">
      {value.img && !source ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-4">
            <Crest descriptor={descriptor} teamName={teamName} size={96} />
            <div className="min-w-0 space-y-2">
              <div className="text-sm font-bold text-ink">Stemma caricato</div>
              <div className="text-xs text-ink-faint">
                Se lo togli, torna lo stemma composto che c'è sotto — non lo hai
                perso.
              </div>
              <Button size="sm" variant="secondary" onClick={() => onChange({ ...value, img: '' })}>
                Togli l'immagine
              </Button>
            </div>
          </div>
          <ShapeRow value={value} teamName={teamName} onChange={onChange} />
          {hasAlpha !== false ? (
            <BackgroundRow value={value} teamName={teamName} onChange={onChange} />
          ) : null}
        </div>
      ) : null}

      {source ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-start gap-4">
            <div>
              <canvas
                ref={canvasRef}
                width={VIEW}
                height={VIEW}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerUp}
                className="touch-none cursor-move rounded-xl border border-line bg-surface-2"
                style={{ width: VIEW, height: VIEW }}
              />
              <label className="mt-2 block">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                  Ingrandimento
                </span>
                <input
                  type="range"
                  className="mt-1 w-full"
                  min={minScale}
                  max={minScale * 5}
                  step={minScale / 100}
                  value={frame.scale}
                  onChange={(e) => zoomTo(Number(e.target.value))}
                />
              </label>
              <div className="text-xs text-ink-faint">Trascina per spostare.</div>
            </div>

            <div className="space-y-4">
              <div className="space-y-2">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                  Come verrà
                </div>
                <LivePreview url={previewUrl} teamName={teamName} value={value} />
              </div>
              {/* Qui, mentre si ritaglia, e non solo dopo: la forma cambia cosa
                  dell'immagine resta dentro la sagoma, quindi è una decisione
                  che si prende INSIEME al ritaglio, non a cose fatte. */}
              <ShapeRow
                value={value}
                teamName={teamName}
                url={previewUrl}
                onChange={onChange}
              />
              {hasAlpha !== false ? (
                <BackgroundRow
                  value={value}
                  teamName={teamName}
                  url={previewUrl}
                  onChange={onChange}
                />
              ) : null}
            </div>
          </div>

          {/* Qui c'era un «Applica il ritaglio» che caricava l'immagine e basta.
              Non serviva a nessuno: chi ritaglia e preme Salva ha finito, e chi
              lo faceva si vedeva buttare via il ritaglio in silenzio. Adesso il
              ritaglio parte dentro il Salva, e l'unica altra strada è rinunciare. */}
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" disabled={busy} onClick={() => setSource(null)}>
              ✕ Scarta l'immagine
            </Button>
            <span className="text-xs text-ink-faint">
              L'immagine parte quando premi <b className="text-ink-soft">Salva</b>.
            </span>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-line px-3 py-2 text-sm font-semibold hover:bg-surface-2">
            <input
              type="file"
              accept={ACCEPTED}
              className="hidden"
              onChange={(e) => pick(e.target.files?.[0])}
            />
            📁 {value.img ? 'Scegli un\'altra immagine' : 'Scegli un\'immagine'}
          </label>
          <div className="text-xs text-ink-faint">
            PNG, JPEG, WebP o GIF. La ritagli qui, ne scegli la forma, e viene
            ridotta a 256×256: quello che carichi non viene conservato com'è, lo
            riscriviamo noi.
          </div>
        </div>
      )}

      {error ? (
        <div className="rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">{error}</div>
      ) : null}

      <div className="rounded-xl bg-surface-2 px-3 py-2 text-xs text-ink-faint">
        Lo stemma lo vedono gli altri della lega. Se qualcuno ne carica uno
        offensivo, chiunque può segnalarlo e l'admin della lega può toglierlo.
      </div>
    </div>
  );
}

/** La forma, scegliibile QUI e non solo nella scheda «Componi».
 *
 *  La sagoma è una proprietà dello stemma, non dell'immagine, e questo la rende
 *  facile da spiegare e impossibile da scoprire: chi arriva dritto al
 *  caricamento vede la sua fotografia ritagliata in un modo solo e conclude che
 *  quello sia l'unico. Una riga di testo che rimanda a un'altra scheda non
 *  ripara niente — è l'opzione che deve essere lì, con l'effetto sotto gli occhi.
 *
 *  Stesso principio delle miniature di `ChoiceRow`, con una differenza che conta:
 *  lì la miniatura mostra lo stemma composto, qui mostra **l'immagine
 *  dell'utente** in ciascuna forma. È la sua foto che deve stare nel tondo o
 *  nello scudo, non un campione astratto.
 */
function ShapeRow({
  value,
  teamName,
  /** Il ritaglio in corso, come data URI. Assente => si mostra l'immagine già
   *  caricata, che <Crest> sa disegnare da sé. */
  url,
  onChange,
}: {
  value: CrestOptions;
  teamName: string;
  url?: string;
  onChange: (next: CrestOptions) => void;
}) {
  const bg = crestColor(value.primary, '1e3a8a');
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        Forma
      </div>
      <div className="flex flex-wrap gap-2">
        {CREST_SHAPES.map((shape: CrestShape) => {
          const active = value.shape === shape;
          return (
            <button
              key={shape}
              type="button"
              onClick={() => onChange({ ...value, shape })}
              aria-label={CREST_SHAPE_LABELS[shape]}
              aria-pressed={active}
              title={CREST_SHAPE_LABELS[shape]}
              className={clsx(
                'rounded-xl border p-1 transition',
                active ? 'border-line bg-surface-2 ring-2 ring-line' : 'border-line hover:bg-surface-2',
              )}
            >
              {url ? (
                <ClippedPreview url={url} shape={shape} size={40} bg={bg} />
              ) : (
                <Crest
                  descriptor={serializeCrest({ ...value, shape })}
                  teamName={teamName}
                  size={40}
                />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Il colore che si vede ATTRAVERSO l'immagine, quando l'immagine ha buchi.
 *
 *  È lo stesso `primary` del colore principale nella scheda «Componi» — un PNG
 *  ritagliato non poggia su un fondo suo, poggia sul colore della squadra. Il
 *  motivo per cui compare anche qui è lo stesso della forma: chi arriva dritto
 *  al caricamento non ha idea che quel colore esista, se lo scopre solo dopo
 *  aver salvato, vedendosi comparire dietro la figura un giallo che non aveva
 *  scelto.
 *
 *  Compare solo quando serve: dietro un'immagine piena non si vedrebbe mai, e un
 *  comando che non produce nessun effetto visibile insegna solo a diffidare.
 */
function BackgroundRow({
  value,
  teamName,
  url,
  onChange,
}: {
  value: CrestOptions;
  teamName: string;
  url?: string;
  onChange: (next: CrestOptions) => void;
}) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        Sfondo
      </div>
      <div className="flex flex-wrap gap-2">
        {CREST_COLORS.map((c) => {
          const active = value.primary === c;
          return (
            <button
              key={c}
              type="button"
              onClick={() => onChange({ ...value, primary: c })}
              aria-label={`Sfondo ${c}`}
              aria-pressed={active}
              className={clsx(
                'rounded-xl border p-1 transition',
                active ? 'border-line bg-surface-2 ring-2 ring-line' : 'border-line hover:bg-surface-2',
              )}
            >
              {url ? (
                <ClippedPreview
                  url={url}
                  shape={value.shape}
                  size={32}
                  bg={crestColor(c, '1e3a8a')}
                />
              ) : (
                <Crest
                  descriptor={serializeCrest({ ...value, primary: c })}
                  teamName={teamName}
                  size={32}
                />
              )}
            </button>
          );
        })}
      </div>
      <div className="mt-1 text-[11px] text-ink-faint">
        Si vede attraverso le parti trasparenti dell'immagine. È lo stesso colore
        principale dello stemma composto.
      </div>
    </div>
  );
}

/** L'anteprima alle due misure che contano: quella grande della scheda squadra,
 *  e i 20 px della tabella di classifica. La seconda è quella che convince — è
 *  lì che una fotografia diventa fango, e vederlo prima di salvare vale più di
 *  qualunque avvertimento scritto. */
function LivePreview({
  url,
  teamName,
  value,
}: {
  url: string;
  teamName: string;
  value: CrestOptions;
}) {
  const bg = crestColor(value.primary, '1e3a8a');
  // Non passa da <Crest>: quello disegna un'immagine GIÀ caricata, cioè un
  // indirizzo che qui non esiste ancora. Stessa sagoma, stesso bordo, ritagliati
  // a mano su un data URI — l'anteprima deve mostrare il risultato, non
  // aspettare di averlo prodotto.
  return (
    <div className="flex items-end gap-4">
      <div className="text-center">
        <ClippedPreview url={url} shape={value.shape} size={96} bg={bg} />
        <div className="mt-1 text-[10px] text-ink-faint">scheda</div>
      </div>
      {/* I 20 px NON da soli: in classifica lo stemma non si guarda isolato, si
          guarda accanto al nome, ed è in quell'accostamento che si vede se
          regge. Il nome sta qui dentro, non a fianco come etichetta libera. */}
      <div>
        <div className="flex items-center gap-2 rounded-lg border border-line px-2 py-1">
          <ClippedPreview url={url} shape={value.shape} size={20} bg={bg} />
          <span className="text-sm font-bold text-ink">{teamName || 'La tua squadra'}</span>
        </div>
        <div className="mt-1 text-center text-[10px] text-ink-faint">in classifica</div>
      </div>
    </div>
  );
}

function ClippedPreview({
  url,
  shape,
  size,
  bg,
}: {
  url: string;
  shape: string;
  size: number;
  /** Lo stesso fondo che dipinge <Crest>. Passato e non fissato qui: era
   *  fissato, e per le immagini con la trasparenza l'anteprima mostrava un
   *  colore e il risultato ne mostrava un altro. */
  bg: string;
}) {
  // Come in Crest.tsx: gli id dei clipPath sono globali al documento, e due
  // anteprime con lo stesso id verrebbero ritagliate entrambe dalla prima.
  const clipId = `prev-${useId()}`;
  const outline =
    shape === 'circle'
      ? 'M32 2 A30 30 0 1 1 31.99 2 Z'
      : shape === 'pennant'
        ? 'M6 4 H58 V40 L32 62 L6 40 Z'
        : 'M32 2 L60 10 V32 C60 48 47 58 32 62 C17 58 4 48 4 32 V10 Z';
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} role="img" aria-label="Anteprima stemma">
      <defs>
        <clipPath id={clipId}>
          <path d={outline} />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clipId})`}>
        <rect x={0} y={0} width={64} height={64} fill={bg} />
        {url ? <image href={url} x={0} y={0} width={64} height={64} /> : null}
      </g>
      <path d={outline} fill="none" stroke="var(--vf-crest-edge)" strokeWidth={2.5} />
    </svg>
  );
}
