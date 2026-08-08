// Per-competition accent palette. Each competition in a league gets a distinct
// colour (by its position in the competition list) so the competition-scoped pages
// (Partite, Risultati), the accent strip and the switcher all share the SAME colour
// as the current competition — and it differs from the other competitions.
//
// DUE VOCABOLARI DI COLORE, E NON DEVONO TOCCARSI
// -----------------------------------------------
// Nell'app il colore dice due cose diverse. Qui dice IDENTITÀ — quale
// competizione — e non ha significato: è un'etichetta, e potrebbe essere
// qualunque tinta. Altrove dice STATO, e allora il significato è tutto:
//
//     ambra    attenzione, e ciò che è in evidenza (un avviso, un trofeo)
//     emerald  fatto, riuscito, da concludere adesso
//     violet   si sta giocando: un numero che si muove ancora
//     rose     è andato storto, o non si sbloccherà
//
// Questa palette conteneva ambra, emerald, violet e rose, e quindi la terza
// competizione di una lega si presentava col colore degli avvisi e la seconda con
// quello delle cose fatte. Non è un dettaglio estetico: chi guarda impara che
// l'ambra vuol dire "guarda qui", e poi la ritrova addosso a un torneo che non
// sta chiedendo niente. È già successo con un banner d'avviso e con l'albo d'oro.
//
// Le tinte qui sotto sono scelte per NON appartenere a quel vocabolario, e le
// prime tre — quelle che una lega usa davvero — sono anche le più distinte fra
// loro: blu, magenta, verde-azzurro. Aggiungendone una, la prova è doppia: che si
// distingua dalle altre competizioni, e che non somigli a uno dei quattro stati.
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
  /** Il fondo tenue della competizione, in trasparenza: vale su entrambi i
   *  temi, mentre `bg50` è una tinta chiara e va usata solo dove il fondo è
   *  chiaro per costruzione. */
  tint: string;
}

export const COMP_COLORS: CompColor[] = [
  {
    bg700: 'bg-indigo-700', text700: 'text-indigo-700', text400: 'text-indigo-400',
    hover50: 'hover:bg-indigo-50', border600: 'border-indigo-600', border300: 'border-indigo-300',
    bg50: 'bg-indigo-50', text900: 'text-indigo-900', text800: 'text-indigo-800', text500: 'text-indigo-500',
    dot: 'bg-indigo-500', tint: 'bg-indigo-500/12',
  },
  {
    bg700: 'bg-fuchsia-700', text700: 'text-fuchsia-700', text400: 'text-fuchsia-400',
    hover50: 'hover:bg-fuchsia-50', border600: 'border-fuchsia-600', border300: 'border-fuchsia-300',
    bg50: 'bg-fuchsia-50', text900: 'text-fuchsia-900', text800: 'text-fuchsia-800', text500: 'text-fuchsia-500',
    dot: 'bg-fuchsia-500', tint: 'bg-fuchsia-500/12',
  },
  {
    bg700: 'bg-teal-700', text700: 'text-teal-700', text400: 'text-teal-400',
    hover50: 'hover:bg-teal-50', border600: 'border-teal-600', border300: 'border-teal-300',
    bg50: 'bg-teal-50', text900: 'text-teal-900', text800: 'text-teal-800', text500: 'text-teal-500',
    dot: 'bg-teal-500', tint: 'bg-teal-500/12',
  },
  {
    bg700: 'bg-sky-700', text700: 'text-sky-700', text400: 'text-sky-400',
    hover50: 'hover:bg-sky-50', border600: 'border-sky-600', border300: 'border-sky-300',
    bg50: 'bg-sky-50', text900: 'text-sky-900', text800: 'text-sky-800', text500: 'text-sky-500',
    dot: 'bg-sky-500', tint: 'bg-sky-500/12',
  },
  {
    bg700: 'bg-cyan-700', text700: 'text-cyan-700', text400: 'text-cyan-400',
    hover50: 'hover:bg-cyan-50', border600: 'border-cyan-600', border300: 'border-cyan-300',
    bg50: 'bg-cyan-50', text900: 'text-cyan-900', text800: 'text-cyan-800', text500: 'text-cyan-500',
    dot: 'bg-cyan-500', tint: 'bg-cyan-500/12',
  },
  {
    // Il grigio caldo chiude il giro: non è una tinta identitaria forte, ma una
    // sesta competizione è rara e un colore neutro è meglio di uno che finge di
    // dire qualcosa.
    bg700: 'bg-stone-700', text700: 'text-stone-700', text400: 'text-stone-400',
    hover50: 'hover:bg-stone-50', border600: 'border-stone-600', border300: 'border-stone-300',
    bg50: 'bg-stone-50', text900: 'text-stone-900', text800: 'text-stone-800', text500: 'text-stone-500',
    dot: 'bg-stone-500', tint: 'bg-stone-500/12',
  },
];

export function compColor(index: number): CompColor {
  if (index < 0) index = 0;
  return COMP_COLORS[index % COMP_COLORS.length];
}
