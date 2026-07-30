import clsx from 'clsx';
import type { PropsWithChildren } from 'react';

export function Card({ children, className, id }: PropsWithChildren<{ className?: string; id?: string }>) {
  // id is optional and exists so a card can be a scroll target: switching a tab
  // that lives far down a long page otherwise changes nothing the user can see.
  return <div id={id} className={clsx('rounded-2xl bg-white shadow-card', className)}>{children}</div>;
}

export function SectionTitle({ children, className }: PropsWithChildren<{ className?: string }>) {
  return <div className={clsx('text-xs font-semibold uppercase tracking-wide text-slate-500', className)}>{children}</div>;
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
    'inline-flex items-center justify-center rounded-xl font-semibold transition active:scale-[0.99] disabled:opacity-50 disabled:active:scale-100';
  const sizes = size === 'sm' ? 'text-xs px-3 py-2' : 'text-sm px-4 py-2.5';
  const variants: Record<string, string> = {
    primary: 'bg-slate-900 text-white hover:bg-slate-800',
    secondary: 'bg-slate-200 text-slate-900 hover:bg-slate-300',
    ghost: 'bg-transparent text-slate-700 hover:bg-slate-100',
    danger: 'bg-red-600 text-white hover:bg-red-500'
  };
  return (
    <button type={type} onClick={onClick} disabled={disabled} title={title} className={clsx(base, sizes, variants[variant], className)}>
      {children}
    </button>
  );
}

export function Badge({ children, tone = 'slate' }: PropsWithChildren<{ tone?: 'slate' | 'green' | 'red' | 'amber' | 'blue' }>) {
  const tones: Record<string, string> = {
    slate: 'bg-slate-100 text-slate-700',
    green: 'bg-green-100 text-green-800',
    red: 'bg-red-100 text-red-800',
    amber: 'bg-amber-100 text-amber-800',
    blue: 'bg-blue-100 text-blue-800'
  };
  return <span className={clsx('inline-flex items-center rounded-full px-2 py-1 text-[11px] font-semibold', tones[tone])}>{children}</span>;
}
