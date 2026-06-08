// Human-friendly names for pitch zones. Internally zones are StatsBomb-style
// keys "Z_<col>_<row>" with 0-based indices: col 0..4 along the length
// (own defense -> attack), row 0..3 across the width (flank -> flank).
//
// Orientation is empirically confirmed from the data (xG and clearances
// concentrate at col 4 and col 0 respectively; shots concentrate in the
// central rows). Names read from the team's own attacking perspective.

export const ZONE_COLS = 5;
export const ZONE_ROWS = 4;

// col (length): defense -> attack
const COL_NAMES = ['Difesa', 'Costruzione', 'Centrocampo', 'Rifinitura', 'Attacco'];
const COL_SHORT = ['DIF', 'COS', 'CC', 'RIF', 'ATT'];

// row (width): flank -> central -> flank
const ROW_NAMES = ['Fascia sinistra', 'Interno sinistro', 'Interno destro', 'Fascia destra'];
const ROW_SHORT = ['Fsx', 'Isx', 'Idx', 'Fdx'];

export interface ZonePos {
  col: number;
  row: number;
}

export function parseZoneKey(zoneKey: string): ZonePos | null {
  const m = /^Z_(\d+)_(\d+)$/.exec(zoneKey);
  if (!m) return null;
  return { col: Number(m[1]), row: Number(m[2]) };
}

export function zoneName(zoneKey: string): string {
  const p = parseZoneKey(zoneKey);
  if (!p) return zoneKey;
  const col = COL_NAMES[p.col] ?? `Col ${p.col}`;
  const row = ROW_NAMES[p.row] ?? `Riga ${p.row}`;
  return `${col} · ${row.toLowerCase()}`;
}

export function zoneShortName(zoneKey: string): string {
  const p = parseZoneKey(zoneKey);
  if (!p) return zoneKey;
  return `${COL_SHORT[p.col] ?? p.col} ${ROW_SHORT[p.row] ?? p.row}`;
}
