import { useState } from 'react';
import clsx from 'clsx';
import Crest from './Crest';
import CrestUploader from './CrestUploader';
import {
  CREST_COLORS,
  CREST_PATTERNS,
  CREST_SHAPES,
  CREST_SHAPE_LABELS,
  CREST_SYMBOLS,
  type CrestOptions,
  randomCrest,
  serializeCrest,
} from '../utils/crest';
import { Button } from './ui';

// Crest customizer, same idea as AvatarBuilder: every option is shown as a MINI
// crest — the current one with that single trait swapped — so the effect of a
// choice is visible before making it.
//
// Two tabs, and they do NOT destroy each other's work: uploading keeps the
// composed layers in the descriptor, removing the image brings them straight
// back. That is not politeness, it is the same property the renderer relies on
// when an image fails to load (see Crest.tsx) — one mechanism, used twice.
//
// The composed tab keeps working while an image is set, and its previews show
// the composed crest rather than the picture: they are answering "what is
// underneath", which is exactly what you want to know before removing it.

const MINI = 40;

const PATTERN_LABELS: Record<string, string> = {
  solid: 'Tinta unita',
  stripes: 'Strisce',
  halves: 'Metà',
  sash: 'Banda',
  hoops: 'Fasce',
};

function ColorRow({
  label,
  value,
  onPick,
}: {
  label: string;
  value: string;
  onPick: (c: string) => void;
}) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">{label}</div>
      <div className="flex flex-wrap gap-2">
        {CREST_COLORS.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => onPick(c)}
            aria-label={`${label} ${c}`}
            aria-pressed={c === value}
            className={clsx(
              'h-9 w-9 rounded-full border transition',
              c === value ? 'ring-2 ring-line ring-offset-2' : 'border-line hover:scale-105',
            )}
            style={{ backgroundColor: `#${c}` }}
          />
        ))}
      </div>
    </div>
  );
}

/** A row of whole-crest previews, one per value of `field`. */
function ChoiceRow<K extends keyof CrestOptions>({
  label,
  field,
  options,
  labels,
  value,
  teamName,
  onPick,
}: {
  label: string;
  field: K;
  options: readonly CrestOptions[K][];
  labels?: Record<string, string>;
  value: CrestOptions;
  teamName: string;
  onPick: (v: CrestOptions[K]) => void;
}) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">{label}</div>
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => {
          const active = value[field] === opt;
          return (
            <button
              key={String(opt) || '—'}
              type="button"
              onClick={() => onPick(opt)}
              aria-label={labels?.[String(opt)] ?? String(opt) ?? 'nessuno'}
              aria-pressed={active}
              title={labels?.[String(opt)]}
              className={clsx(
                'rounded-xl border p-1 transition',
                active ? 'border-line bg-surface-2 ring-2 ring-line' : 'border-line hover:bg-surface-2',
              )}
            >
              {/* `img: ''` di proposito: queste anteprime dicono che effetto fa
                  QUESTA scelta sui livelli composti. Con l'immagine addosso
                  sarebbero venti miniature identiche. */}
              <Crest
                descriptor={serializeCrest({ ...value, [field]: opt, img: '' })}
                teamName={teamName}
                size={MINI}
              />
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function CrestBuilder({
  value,
  teamName,
  onChange,
  onPendingChange,
}: {
  value: CrestOptions;
  teamName: string;
  onChange: (next: CrestOptions) => void;
  /** Passa attraverso fino a CrestUploader: è il ritaglio non ancora caricato,
   *  che deve partire dentro il salvataggio di chi ci sta sopra. */
  onPendingChange?: (commit: (() => Promise<string>) | null) => void;
}) {
  const set = <K extends keyof CrestOptions>(field: K, v: CrestOptions[K]) =>
    onChange({ ...value, [field]: v });

  // Si apre sulla scheda che descrive lo stemma attuale: chi ha caricato
  // un'immagine, riaprendo, vuole vedere quella.
  const [tab, setTab] = useState<'compose' | 'upload'>(value.img ? 'upload' : 'compose');

  // Le anteprime della composizione ignorano l'immagine: mostrano cosa c'è
  // sotto, che è la domanda a cui servono a rispondere.
  const composed = serializeCrest({ ...value, img: '' });

  return (
    <div className="space-y-4">
      <div className="flex gap-1 rounded-xl bg-surface-2 p-1">
        {([
          ['compose', '🎨 Componi'],
          ['upload', '📁 Carica'],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            aria-pressed={tab === key}
            className={clsx(
              'flex-1 rounded-lg px-3 py-1.5 text-sm font-semibold transition',
              tab === key ? 'bg-surface shadow-sm text-ink' : 'text-ink-faint hover:text-ink',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'upload' ? (
        <CrestUploader
          value={value}
          teamName={teamName}
          onChange={onChange}
          onPendingChange={onPendingChange}
        />
      ) : (
        <>
      <div className="flex items-center gap-4">
        <Crest descriptor={composed} teamName={teamName} size={96} />
        <div className="min-w-0">
          <div className="text-sm font-bold text-ink">{teamName || 'La tua squadra'}</div>
          <div className="mt-1 text-xs text-ink-faint">
            Senza simbolo lo stemma porta le iniziali del nome squadra, e cambia se
            rinomini la squadra.
          </div>
          {value.img ? (
            <div className="mt-1 text-xs text-ink-faint">
              In questo momento la squadra mostra l'immagine caricata: questo è ciò
              che tornerebbe togliendola.
            </div>
          ) : null}
          <Button size="sm" variant="secondary" className="mt-2" onClick={() => onChange({ ...randomCrest(), img: value.img })}>
            🎲 Sorprendimi
          </Button>
        </div>
      </div>

      <ChoiceRow
        label="Forma"
        field="shape"
        options={CREST_SHAPES}
        labels={CREST_SHAPE_LABELS}
        value={value}
        teamName={teamName}
        onPick={(v) => set('shape', v)}
      />
      <ChoiceRow
        label="Motivo"
        field="pattern"
        options={CREST_PATTERNS}
        labels={PATTERN_LABELS}
        value={value}
        teamName={teamName}
        onPick={(v) => set('pattern', v)}
      />
      <ColorRow label="Colore principale" value={value.primary} onPick={(c) => set('primary', c)} />
      <ColorRow label="Colore secondario" value={value.secondary} onPick={(c) => set('secondary', c)} />
      <ChoiceRow
        label="Simbolo"
        field="symbol"
        options={CREST_SYMBOLS}
        value={value}
        teamName={teamName}
        onPick={(v) => set('symbol', v)}
      />
      <ColorRow label="Colore delle iniziali" value={value.ink} onPick={(c) => set('ink', c)} />
        </>
      )}
    </div>
  );
}
