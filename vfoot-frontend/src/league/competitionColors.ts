// Per-competition accent palette. Each competition in a league gets a distinct
// colour (by its position in the competition list) so the competition-scoped pages
// (Partite, Risultati), the accent strip and the switcher all share the SAME colour
// as the current competition — and it differs from the other competitions.
//
// Tailwind purges unseen class names, so every class string is written out literally
// here (this file is scanned by the content globs).
export interface CompColor {
  bg700: string;
  text700: string;
  text400: string;
  hover50: string;
  border600: string;
  border300: string;
  bg50: string;
  text900: string;
  text800: string;
  text500: string;
  dot: string;
}

export const COMP_COLORS: CompColor[] = [
  {
    bg700: 'bg-indigo-700', text700: 'text-indigo-700', text400: 'text-indigo-400',
    hover50: 'hover:bg-indigo-50', border600: 'border-indigo-600', border300: 'border-indigo-300',
    bg50: 'bg-indigo-50', text900: 'text-indigo-900', text800: 'text-indigo-800', text500: 'text-indigo-500',
    dot: 'bg-indigo-500',
  },
  {
    bg700: 'bg-emerald-700', text700: 'text-emerald-700', text400: 'text-emerald-400',
    hover50: 'hover:bg-emerald-50', border600: 'border-emerald-600', border300: 'border-emerald-300',
    bg50: 'bg-emerald-50', text900: 'text-emerald-900', text800: 'text-emerald-800', text500: 'text-emerald-500',
    dot: 'bg-emerald-500',
  },
  {
    bg700: 'bg-amber-600', text700: 'text-amber-700', text400: 'text-amber-400',
    hover50: 'hover:bg-amber-50', border600: 'border-amber-500', border300: 'border-amber-300',
    bg50: 'bg-amber-50', text900: 'text-amber-900', text800: 'text-amber-800', text500: 'text-amber-500',
    dot: 'bg-amber-500',
  },
  {
    bg700: 'bg-rose-700', text700: 'text-rose-700', text400: 'text-rose-400',
    hover50: 'hover:bg-rose-50', border600: 'border-rose-600', border300: 'border-rose-300',
    bg50: 'bg-rose-50', text900: 'text-rose-900', text800: 'text-rose-800', text500: 'text-rose-500',
    dot: 'bg-rose-500',
  },
  {
    bg700: 'bg-sky-700', text700: 'text-sky-700', text400: 'text-sky-400',
    hover50: 'hover:bg-sky-50', border600: 'border-sky-600', border300: 'border-sky-300',
    bg50: 'bg-sky-50', text900: 'text-sky-900', text800: 'text-sky-800', text500: 'text-sky-500',
    dot: 'bg-sky-500',
  },
  {
    bg700: 'bg-violet-700', text700: 'text-violet-700', text400: 'text-violet-400',
    hover50: 'hover:bg-violet-50', border600: 'border-violet-600', border300: 'border-violet-300',
    bg50: 'bg-violet-50', text900: 'text-violet-900', text800: 'text-violet-800', text500: 'text-violet-500',
    dot: 'bg-violet-500',
  },
];

export function compColor(index: number): CompColor {
  if (index < 0) index = 0;
  return COMP_COLORS[index % COMP_COLORS.length];
}
