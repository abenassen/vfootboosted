import { useMemo } from 'react';
import clsx from 'clsx';
import {
  ACCESSORIES,
  AvatarOptions,
  BACKGROUND_COLORS,
  CLOTHES_COLORS,
  CLOTHINGS,
  EYES,
  FACIAL_HAIR,
  HAIR_COLORS,
  MOUTHS,
  SKIN_COLORS,
  TOPS,
  avatarDataUri,
  randomAvatar,
} from '../utils/avatar';

// A composable avatar customizer: pick each trait and watch the preview update.
// Trait rows show a MINI avatar per option (current avatar with just that one
// trait swapped) so the effect of every choice is visible before selecting it.

const MINI = 44; // touch-friendly option tiles

function ColorRow({
  label,
  colors,
  value,
  onPick,
}: {
  label: string;
  colors: readonly string[];
  value: string;
  onPick: (c: string) => void;
}) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="flex flex-wrap gap-2">
        {colors.map((c) => {
          const active = c === value;
          const transparent = c === 'transparent';
          return (
            <button
              key={c}
              type="button"
              onClick={() => onPick(c)}
              aria-label={`${label} ${c}`}
              aria-pressed={active}
              className={clsx(
                'h-9 w-9 rounded-full border transition',
                active ? 'ring-2 ring-slate-900 ring-offset-2' : 'border-slate-200 hover:scale-105',
              )}
              style={
                transparent
                  ? { backgroundImage: 'linear-gradient(45deg,#e2e8f0 25%,transparent 25%,transparent 75%,#e2e8f0 75%),linear-gradient(45deg,#e2e8f0 25%,#fff 25%,#fff 75%,#e2e8f0 75%)', backgroundSize: '10px 10px', backgroundPosition: '0 0,5px 5px' }
                  : { backgroundColor: `#${c}` }
              }
            />
          );
        })}
      </div>
    </div>
  );
}

function ChoiceRow({
  label,
  field,
  options,
  base,
  onPick,
}: {
  label: string;
  field: keyof AvatarOptions;
  options: readonly string[];
  base: AvatarOptions;
  onPick: (v: string) => void;
}) {
  // One mini avatar per option = the current avatar with only `field` swapped.
  const tiles = useMemo(
    () =>
      options.map((opt) => ({
        opt,
        uri: avatarDataUri({ ...base, [field]: opt }, MINI * 2),
        active: base[field] === opt,
      })),
    [options, base, field],
  );
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="flex gap-2 overflow-x-auto pb-1" style={{ scrollbarWidth: 'none' }}>
        {tiles.map(({ opt, uri, active }) => (
          <button
            key={opt || '__none__'}
            type="button"
            onClick={() => onPick(opt)}
            aria-label={`${label}: ${opt || 'nessuno'}`}
            aria-pressed={active}
            className={clsx(
              'shrink-0 overflow-hidden rounded-xl border transition',
              active ? 'border-slate-900 ring-2 ring-slate-900' : 'border-slate-200 hover:border-slate-400',
            )}
          >
            <img src={uri} width={MINI} height={MINI} alt="" style={{ width: MINI, height: MINI, display: 'block' }} />
          </button>
        ))}
      </div>
    </div>
  );
}

export default function AvatarBuilder({
  value,
  onChange,
}: {
  value: AvatarOptions;
  onChange: (next: AvatarOptions) => void;
}) {
  const preview = useMemo(() => avatarDataUri(value, 256), [value]);
  const set = (patch: Partial<AvatarOptions>) => onChange({ ...value, ...patch });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <img
          src={preview}
          width={104}
          height={104}
          alt="Anteprima avatar"
          className="rounded-2xl bg-white shadow-card"
          style={{ width: 104, height: 104 }}
        />
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-700">Il tuo avatar</div>
          <div className="text-xs text-slate-500">Combina i tratti come vuoi: migliaia di combinazioni.</div>
          <button
            type="button"
            onClick={() => onChange(randomAvatar())}
            className="mt-2 rounded-xl bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-700"
          >
            🎲 Casuale
          </button>
        </div>
      </div>

      <div className="grid gap-4">
        <ColorRow label="Incarnato" colors={SKIN_COLORS} value={value.skinColor} onPick={(c) => set({ skinColor: c })} />
        <ChoiceRow label="Capelli" field="top" options={TOPS} base={value} onPick={(v) => set({ top: v })} />
        <ColorRow label="Colore capelli" colors={HAIR_COLORS} value={value.hairColor} onPick={(c) => set({ hairColor: c })} />
        <ChoiceRow label="Occhi" field="eyes" options={EYES} base={value} onPick={(v) => set({ eyes: v })} />
        <ChoiceRow label="Bocca" field="mouth" options={MOUTHS} base={value} onPick={(v) => set({ mouth: v })} />
        <ChoiceRow label="Barba" field="facialHair" options={FACIAL_HAIR} base={value} onPick={(v) => set({ facialHair: v })} />
        <ChoiceRow label="Occhiali" field="accessories" options={ACCESSORIES} base={value} onPick={(v) => set({ accessories: v })} />
        <ChoiceRow label="Vestito" field="clothing" options={CLOTHINGS} base={value} onPick={(v) => set({ clothing: v })} />
        <ColorRow label="Colore vestito" colors={CLOTHES_COLORS} value={value.clothesColor} onPick={(c) => set({ clothesColor: c })} />
        <ColorRow label="Sfondo" colors={BACKGROUND_COLORS} value={value.backgroundColor} onPick={(c) => set({ backgroundColor: c })} />
      </div>
    </div>
  );
}
