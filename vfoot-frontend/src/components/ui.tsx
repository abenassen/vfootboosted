import clsx from 'clsx';
import type { PropsWithChildren } from 'react';

/* I quattro pezzi con cui è costruito quasi tutto il sito. Sono passati ai token
 * del tema (v. styles/index.css): da qui in poi «bianco» e «slate-500» non si
 * scrivono più a mano, e il tema scuro non ha bisogno di una variante `dark:`
 * accanto a ogni colore — cambiano le variabili, e questi seguono. */

export function Card({ children, className, id }: PropsWithChildren<{ className?: string; id?: string }>) {
  // id is optional and exists so a card can be a scroll target: switching a tab
  // that lives far down a long page otherwise changes nothing the user can see.
  return (
    <div id={id} className={clsx('rounded-2xl border border-line bg-surface shadow-card', className)}>
      {children}
    </div>
  );
}

export function SectionTitle({ children, className }: PropsWithChildren<{ className?: string }>) {
  // Condensato: è un titolo, e il condensato è ciò che dà il taglio sportivo —
  // tenuto ai titoli e ai numeri grandi, perché ovunque diventerebbe una
  // locandina.
  return (
    <div className={clsx('font-cond text-sm font-bold uppercase tracking-wide text-ink-faint', className)}>
      {children}
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = 'primary',
  size = 'md',
  disabled,
  type = 'button',
  className,
  title,
}: PropsWithChildren<{
  onClick?: () => void;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md';
  disabled?: boolean;
  type?: 'button' | 'submit' | 'reset';
  className?: string;
  /** Native tooltip — the only way to explain a DISABLED button, which cannot
   *  hold a click handler to say why it is disabled. */
  title?: string;
}>) {
  const base =
    'inline-flex items-center justify-center rounded-xl font-semibold transition active:scale-[0.99] ' +
    'disabled:opacity-50 disabled:active:scale-100 focus-visible:outline focus-visible:outline-2 ' +
    'focus-visible:outline-offset-2 focus-visible:outline-accent';
  const sizes = size === 'sm' ? 'text-xs px-3 py-2' : 'text-sm px-4 py-2.5';
  const variants: Record<string, string> = {
    // La sfumatura verde→azzurro sul pulsante PRINCIPALE, che è uno per
    // schermata: è l'azione che l'app ti sta chiedendo. Su ogni bottone
    // smetterebbe di indicare qualcosa. I pulsanti legati a una competizione
    // non passano di qui: tengono il colore di quella (v. LeagueHome).
    primary: 'bg-gradient-to-r from-brand to-accent text-on-brand hover:brightness-110',
    secondary: 'bg-surface-2 text-ink border border-line hover:bg-line/60',
    ghost: 'bg-transparent text-ink-soft hover:bg-surface-2',
    danger: 'bg-bad text-white hover:opacity-90',
  };
  return (
    <button type={type} onClick={onClick} disabled={disabled} title={title} className={clsx(base, sizes, variants[variant], className)}>
      {children}
    </button>
  );
}

export function Badge({
  children,
  tone = 'slate',
  // Una parola sola su un'etichetta a volte non basta a dire che cosa afferma.
  // Il titolo è il posto giusto per la frase intera: appare a chi si ferma
  // sopra, e non allunga la riga per tutti gli altri.
  title,
}: PropsWithChildren<{ tone?: 'slate' | 'green' | 'red' | 'amber' | 'blue'; title?: string }>) {
  // I nomi dei toni restano quelli di prima — sono usati in una cinquantina di
  // punti — ma ora ognuno punta allo STATO che significa: verde = riuscito,
  // ambra = attenzione, rosso = sbagliato, blu = in corso. Erano tinte, adesso
  // sono affermazioni, e il tema scuro le ricalibra da solo.
  const tones: Record<string, string> = {
    slate: 'bg-surface-2 text-ink-soft border border-line',
    green: 'bg-good-bg text-good',
    red: 'bg-bad-bg text-bad',
    amber: 'bg-warn-bg text-warn',
    blue: 'bg-live-bg text-live',
  };
  return (
    <span title={title} className={clsx('inline-flex items-center rounded-full px-2 py-1 text-[11px] font-semibold', tones[tone])}>
      {children}
    </span>
  );
}
