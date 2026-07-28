import { createAvatar } from '@dicebear/core';
import { avataaars } from '@dicebear/collection';

// Composable, client-side avatar built on DiceBear's `avataaars` style. The user
// picks a handful of traits; every choice is pinned so the descriptor fully
// determines the drawing. We ALWAYS render with the same fixed seed so residual
// (un-exposed) options stay constant too — a given descriptor always yields the
// exact same SVG, everywhere. Nothing runs on the server: the option string is
// opaque to the backend and the SVG is generated here in the browser.

export type AvatarOptions = {
  skinColor: string;
  top: string; // '' => bald (no hair rendered)
  hairColor: string;
  clothing: string;
  clothesColor: string;
  eyes: string;
  eyebrows: string;
  mouth: string;
  accessories: string; // '' => none
  facialHair: string; // '' => none
  backgroundColor: string; // 'transparent' allowed
};

// Fixed seed: with every meaningful trait pinned, the seed only fixes the few
// options we don't expose (nose, exact style internals) so they never drift.
const SEED = 'vfoot';

// --- Curated catalogs (subset of the full avataaars schema) --------------------
// Skin tones span a deliberately inclusive range.
export const SKIN_COLORS = ['ffdbb4', 'edb98a', 'fd9841', 'd08b5b', 'ae5d29', '614335'];
export const HAIR_COLORS = ['2c1b18', '4a312c', '724133', 'a55728', 'b58143', 'd6b370', 'c93305', 'e8e1e1', 'ecdcbf', 'f59797'];
export const CLOTHES_COLORS = ['262e33', '3c4f5c', '25557c', '5199e4', '65c9ff', '929598', 'e6e6e6', 'ffffff', 'ff5c5c', 'ff488e', 'ffafb9', 'a7ffc4', 'ffffb1'];
export const BACKGROUND_COLORS = ['b6e3f4', 'c0aede', 'd1d4f9', 'ffd5dc', 'ffdfbf', 'transparent'];

// '' is the bald option (rendered by dropping the top). The rest mix covered
// styles (hijab/turban/hat), short and long hair.
export const TOPS = [
  '', 'shortFlat', 'shortCurly', 'shortRound', 'shortWaved', 'theCaesar', 'sides', 'dreads01', 'fro',
  'longButNotTooLong', 'straight01', 'straight02', 'bob', 'bun', 'curly', 'curvy', 'bigHair', 'miaWallace',
  'frida', 'hijab', 'turban', 'hat', 'winterHat02',
];
export const CLOTHINGS = ['shirtCrewNeck', 'shirtVNeck', 'shirtScoopNeck', 'collarAndSweater', 'hoodie', 'blazerAndShirt', 'blazerAndSweater', 'graphicShirt', 'overall'];
export const EYES = ['default', 'happy', 'wink', 'squint', 'surprised', 'hearts', 'side', 'closed'];
export const MOUTHS = ['smile', 'default', 'twinkle', 'serious', 'tongue', 'grimace', 'eating', 'disbelief'];
export const ACCESSORIES = ['', 'round', 'prescription02', 'sunglasses', 'wayfarers', 'eyepatch'];
export const FACIAL_HAIR = ['', 'beardLight', 'beardMedium', 'beardMajestic', 'moustacheFancy', 'moustacheMagnum'];

export const DEFAULT_AVATAR: AvatarOptions = {
  skinColor: 'edb98a',
  top: 'shortFlat',
  hairColor: '4a312c',
  clothing: 'shirtCrewNeck',
  clothesColor: '3c4f5c',
  eyes: 'default',
  eyebrows: 'default',
  mouth: 'smile',
  accessories: '',
  facialHair: '',
  backgroundColor: 'b6e3f4',
};

function pick<T>(arr: readonly T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

/** A fresh, unique combination — the "sorprendimi" button. */
export function randomAvatar(): AvatarOptions {
  return {
    skinColor: pick(SKIN_COLORS),
    top: pick(TOPS.filter((t) => t !== '')),
    hairColor: pick(HAIR_COLORS),
    clothing: pick(CLOTHINGS),
    clothesColor: pick(CLOTHES_COLORS),
    eyes: pick(EYES),
    eyebrows: 'default',
    mouth: pick(MOUTHS),
    accessories: Math.random() < 0.35 ? pick(ACCESSORIES.filter((a) => a !== '')) : '',
    facialHair: Math.random() < 0.35 ? pick(FACIAL_HAIR.filter((f) => f !== '')) : '',
    backgroundColor: pick(BACKGROUND_COLORS),
  };
}

export function serializeAvatar(opts: AvatarOptions): string {
  return JSON.stringify(opts);
}

/** Parse a stored descriptor; unknown/blank => null (caller falls back to a
 *  username-seeded default). Missing keys are backfilled from DEFAULT_AVATAR so
 *  descriptors survive future additions to AvatarOptions. */
export function parseAvatar(descriptor: string | null | undefined): AvatarOptions | null {
  if (!descriptor) return null;
  try {
    const o = JSON.parse(descriptor);
    if (o && typeof o === 'object') return { ...DEFAULT_AVATAR, ...o } as AvatarOptions;
  } catch {
    /* ignore malformed descriptors */
  }
  return null;
}

function build(opts: AvatarOptions, size: number) {
  const hasHair = !!opts.top;
  const hasAcc = !!opts.accessories;
  const hasBeard = !!opts.facialHair;
  // The avataaars option values are typed as string-literal unions; ours come
  // from user selection at runtime, so the whole option bag is cast once. The
  // catalogs in this file are the single source of truth for valid values.
  const options = {
    seed: SEED,
    size,
    radius: 50,
    backgroundColor: [opts.backgroundColor],
    skinColor: [opts.skinColor],
    top: [hasHair ? opts.top : 'shortFlat'],
    topProbability: hasHair ? 100 : 0,
    hairColor: [opts.hairColor],
    clothing: [opts.clothing],
    clothesColor: [opts.clothesColor],
    eyes: [opts.eyes],
    eyebrows: [opts.eyebrows],
    mouth: [opts.mouth],
    accessories: [hasAcc ? opts.accessories : 'round'],
    accessoriesProbability: hasAcc ? 100 : 0,
    facialHair: [hasBeard ? opts.facialHair : 'beardLight'],
    facialHairProbability: hasBeard ? 100 : 0,
    facialHairColor: [opts.hairColor],
  };
  return createAvatar(avataaars, options as Parameters<typeof createAvatar>[1]);
}

/** A data: URI for the composed avatar — cheap to drop into an <img src>. */
export function avatarDataUri(opts: AvatarOptions, size = 96): string {
  return build(opts, size).toDataUri();
}

/** Deterministic fallback for users who haven't picked an avatar: a unique but
 *  stable illustration seeded from their username. */
export function defaultAvatarDataUri(seed: string, size = 96): string {
  return createAvatar(avataaars, { seed: seed || 'vfoot', size, radius: 50 }).toDataUri();
}
