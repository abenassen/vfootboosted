/** I token del tema, come classi.
 *
 *  I valori veri stanno in src/styles/index.css come variabili CSS; qui si
 *  dichiarano soltanto i NOMI con cui si scrivono nelle pagine — `bg-surface`,
 *  `text-ink-soft`, `border-line`. Il giro serve a una cosa sola: il tema scuro
 *  cambia le variabili e nient'altro, quindi nessuna pagina ha bisogno di una
 *  variante `dark:` accanto a ogni colore.
 *
 *  Il canale alfa resta disponibile (`<alpha-value>`), così `bg-brand/10` per
 *  una sfumatura leggera continua a funzionare.
 *
 *  @type {import('tailwindcss').Config} */
const rgb = (v) => `rgb(var(${v}) / <alpha-value>)`;

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  // Il tema segue un attributo sull'elemento radice e non la preferenza del
  // sistema: la scelta è dell'utente e sta nel suo profilo, quindi deve poter
  // dire "chiaro" anche a sistema scuro. "Come il sistema" è una terza opzione
  // che scrive lo stesso attributo.
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: rgb('--vf-brand'), strong: rgb('--vf-brand-strong') },
        accent: { DEFAULT: rgb('--vf-accent'), strong: rgb('--vf-accent-strong') },
        paper: rgb('--vf-paper'),
        surface: { DEFAULT: rgb('--vf-surface'), 2: rgb('--vf-surface-2') },
        ink: { DEFAULT: rgb('--vf-ink'), soft: rgb('--vf-ink-soft'), faint: rgb('--vf-ink-faint') },
        line: rgb('--vf-line'),
        // Gli stati, con lo sfondo tenue accanto al colore pieno: le due tinte
        // di una pastiglia sono una cosa sola e vanno scelte insieme.
        warn: { DEFAULT: rgb('--vf-warn'), bg: rgb('--vf-warn-bg') },
        live: { DEFAULT: rgb('--vf-live'), bg: rgb('--vf-live-bg') },
        good: { DEFAULT: rgb('--vf-good'), bg: rgb('--vf-good-bg') },
        bad: { DEFAULT: rgb('--vf-bad'), bg: rgb('--vf-bad-bg') },
        'on-brand': rgb('--vf-on-brand'),
      },
      fontFamily: {
        sans: ['Barlow', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
        // Il condensato è per i titoli e per i numeri grandi — risultati,
        // punteggi, il numero della giornata. È il taglio delle grafiche
        // sportive, e proprio per questo va tenuto per pochi elementi.
        cond: ['Barlow Condensed', 'Barlow', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        card: '0 1px 2px rgb(0 0 0 / .06), 0 8px 20px -16px rgb(0 0 0 / .35)',
        lift: '0 2px 6px rgb(0 0 0 / .08), 0 16px 32px -20px rgb(0 0 0 / .45)',
      },
      borderRadius: { xl2: '0.875rem' },
    },
  },
  plugins: [],
};
