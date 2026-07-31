/** Text matching for name search: forgiving about how a name is spelled.
 *
 *  Player names are a minefield of things nobody types the way they are stored —
 *  diacritics ("Leão", "Martínez", "Süle"), apostrophes that vary by source
 *  ("D'Ambrosio" vs "D’Ambrosio", and our own data has doubled ones), and
 *  spellings you have to have seen to reproduce ("Mkhitaryan", "Szczęsny").
 *  Requiring the exact string means the search hides the player and looks broken.
 */

/** Case-, accent- and punctuation-free form, for comparing what was typed with
 *  what is stored. NFD splits a letter into base + combining mark; the mark is
 *  then dropped. */
export function fold(value: string | null | undefined): string {
  return (value ?? '')
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .replace(/[’'`´\-.]/g, '')
    .toLowerCase()
    .trim();
}

/** Levenshtein distance, abandoned as soon as it cannot come in under `max`.
 *  The early exit is what keeps this cheap enough to run over every row of the
 *  listone on each keystroke. */
function editDistanceWithin(a: string, b: string, max: number): number {
  if (Math.abs(a.length - b.length) > max) return max + 1;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const row = [i];
    let best = i;
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      const v = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost);
      row.push(v);
      if (v < best) best = v;
    }
    // Every path through this row already costs more than we allow.
    if (best > max) return max + 1;
    prev = row;
  }
  return prev[b.length];
}

/** How wrong a word may be and still count as the one that was meant. Short
 *  needles get no slack: on three letters, one error matches half the roster. */
function allowedErrors(needle: string): number {
  if (needle.length <= 3) return 0;
  if (needle.length <= 6) return 1;
  return 2;
}

/** Does `needle` match `field`, allowing for accents, punctuation and a typo or
 *  two? A substring hit always wins; otherwise each word of the field is
 *  compared, including against just its opening letters, so "mkitarian" still
 *  finds "Mkhitaryan" and "martine" still finds "Martínez". */
function matchesField(needle: string, field: string | null | undefined): boolean {
  const hay = fold(field);
  if (!hay) return false;
  if (hay.includes(needle)) return true;

  const slack = allowedErrors(needle);
  if (!slack) return false;

  for (const word of hay.split(/\s+/)) {
    if (!word) continue;
    if (editDistanceWithin(word, needle, slack) <= slack) return true;
    // Compare only the opening of a longer word, so a typo in a prefix still
    // lands: "gianluigy" vs "gianluigi donnarumma".
    if (word.length > needle.length) {
      const head = word.slice(0, needle.length + slack);
      if (editDistanceWithin(head, needle, slack) <= slack) return true;
    }
  }
  return false;
}

/** Does any of `fields` match `needle`? Empty needle matches everything. */
export function foldedMatch(needle: string, fields: Array<string | null | undefined>): boolean {
  const q = fold(needle);
  if (!q) return true;
  return fields.some((f) => matchesField(q, f));
}
