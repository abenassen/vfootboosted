// Club crest, composed in the browser and stored as an opaque descriptor —
// exactly like the manager's avatar (see utils/avatar.ts), and for the same
// reason: the schema can grow without a backend migration, and there are no
// uploaded files to serve, back up or ship inside the dev-db dump.
//
// Hand-drawn SVG rather than a DiceBear style: a crest has to stay readable at
// 20px in a standings table, which means few shapes, hard edges and real
// contrast — not an illustration shrunk down.

export type CrestShape = 'shield' | 'circle' | 'pennant';
export type CrestPattern = 'solid' | 'stripes' | 'halves' | 'sash' | 'hoops';

export type CrestOptions = {
  shape: CrestShape;
  pattern: CrestPattern;
  /** Hex without '#'. */
  primary: string;
  secondary: string;
  /** Colour of the initials/symbol. */
  ink: string;
  /** An emoji; empty => the team's initials are drawn instead. */
  symbol: string;
};

export const CREST_SHAPES: CrestShape[] = ['shield', 'circle', 'pennant'];
export const CREST_PATTERNS: CrestPattern[] = ['solid', 'stripes', 'halves', 'sash', 'hoops'];

// Kit colours, not a designer palette: these are the ones football clubs
// actually wear, so any pair of them reads as a strip.
export const CREST_COLORS = [
  '1e3a8a', '2563eb', '0ea5e9', '065f46', '16a34a', '84cc16',
  '7f1d1d', 'dc2626', 'f97316', 'facc15', '6b21a8', 'db2777',
  '0f172a', '475569', 'e2e8f0', 'ffffff',
];

export const CREST_SYMBOLS = [
  '', '⚽', '🦁', '🐺', '🦅', '🐂', '🐍', '🦈', '🐉', '🐴',
  '⭐', '⚡', '🔥', '👑', '⚓', '🗡️', '🛡️', '🌋', '🌪️', '🍀',
];

export const DEFAULT_CREST: CrestOptions = {
  shape: 'shield',
  pattern: 'stripes',
  primary: '1e3a8a',
  secondary: 'ffffff',
  ink: 'ffffff',
  symbol: '',
};

function pick<T>(arr: readonly T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

/** A fresh combination — the "sorprendimi" button. */
export function randomCrest(): CrestOptions {
  const primary = pick(CREST_COLORS.filter((c) => c !== 'ffffff' && c !== 'e2e8f0'));
  return {
    shape: pick(CREST_SHAPES),
    pattern: pick(CREST_PATTERNS),
    primary,
    secondary: pick(CREST_COLORS.filter((c) => c !== primary)),
    ink: 'ffffff',
    symbol: Math.random() < 0.6 ? pick(CREST_SYMBOLS.filter((s) => s !== '')) : '',
  };
}

export function serializeCrest(opts: CrestOptions): string {
  return JSON.stringify(opts);
}

/** Parse a stored descriptor; blank/malformed => null, and the caller falls back
 *  to one seeded from the team name. Missing keys are backfilled from
 *  DEFAULT_CREST so old descriptors survive new options. */
export function parseCrest(descriptor: string | null | undefined): CrestOptions | null {
  if (!descriptor) return null;
  try {
    const o = JSON.parse(descriptor);
    if (o && typeof o === 'object') return { ...DEFAULT_CREST, ...o } as CrestOptions;
  } catch {
    /* ignore malformed descriptors */
  }
  return null;
}

/** Up to three letters: initials of a multi-word name, else its first letters.
 *  This is what a crest shows when no symbol was chosen. */
export function crestInitials(teamName: string | null | undefined): string {
  const name = (teamName ?? '').trim();
  if (!name) return '?';
  const words = name.split(/[\s._-]+/).filter(Boolean);
  if (words.length >= 2) return words.slice(0, 3).map((w) => w[0]).join('').toUpperCase();
  return name.slice(0, 3).toUpperCase();
}

/** Deterministic crest for a team that has not composed one: stable per name, so
 *  a league of ten looks like ten different clubs from day one. */
export function defaultCrest(teamName: string | null | undefined): CrestOptions {
  // FNV-1a: a couple of lines, and stable across browsers and reloads — which
  // Math.random() and Date-seeded hashes are not.
  let h = 0x811c9dc5;
  for (const ch of (teamName ?? 'vfoot')) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  const strong = CREST_COLORS.filter((c) => c !== 'ffffff' && c !== 'e2e8f0');
  const primary = strong[h % strong.length];
  return {
    shape: CREST_SHAPES[(h >>> 4) % CREST_SHAPES.length],
    pattern: CREST_PATTERNS[(h >>> 8) % CREST_PATTERNS.length],
    primary,
    secondary: (h >>> 12) % 2 ? 'ffffff' : '0f172a',
    ink: 'ffffff',
    symbol: '',
  };
}

// --- drawing ---------------------------------------------------------------
// One 64x64 viewBox for every shape, so a crest can be swapped without the
// surrounding layout moving.

// Geometry only: the component renders it as JSX. Deliberately NOT an SVG
// string — a crest carries the team name and a descriptor written by another
// member of the league, and injecting either into markup would be stored XSS.
// Handing back plain data lets React escape the text for us.

export const CREST_OUTLINES: Record<CrestShape, string> = {
  shield: 'M32 2 L60 10 V32 C60 48 47 58 32 62 C17 58 4 48 4 32 V10 Z',
  circle: 'M32 2 A30 30 0 1 1 31.99 2 Z',
  pennant: 'M6 4 H58 V40 L32 62 L6 40 Z',
};

export type CrestBand =
  | { kind: 'rect'; x: number; y: number; width: number; height: number }
  | { kind: 'path'; d: string };

/** The pattern bands, painted over the base colour and clipped to the outline. */
export function crestBands(pattern: CrestPattern): CrestBand[] {
  switch (pattern) {
    case 'stripes':
      return [12, 28, 44].map((x) => ({ kind: 'rect', x, y: 0, width: 8, height: 64 }));
    case 'halves':
      return [{ kind: 'rect', x: 32, y: 0, width: 32, height: 64 }];
    case 'sash':
      return [{ kind: 'path', d: 'M-8 44 L44 -8 L60 8 L8 60 Z' }];
    case 'hoops':
      return [8, 28, 48].map((y) => ({ kind: 'rect', x: 0, y, width: 64, height: 9 }));
    case 'solid':
    default:
      return [];
  }
}

/** Only values from our own catalogues are allowed through as colours: the
 *  descriptor is stored verbatim by the server, so a hand-crafted one could
 *  otherwise smuggle arbitrary CSS into a fill attribute. */
export function crestColor(value: string, fallback: string): string {
  return /^[0-9a-fA-F]{6}$/.test(value) ? `#${value}` : `#${fallback}`;
}

/** An emoji, or nothing. Anything longer than a couple of code points is not a
 *  symbol someone picked from the palette — it is a descriptor built by hand. */
export function crestSymbol(value: string): string {
  return [...(value ?? '')].slice(0, 2).join('');
}
