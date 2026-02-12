import clsx from 'clsx';
import type { PropsWithChildren } from 'react';

export function Card({ children, className }: PropsWithChildren<{ className?: string }>) {
  return <div className={clsx('rounded-2xl bg-white shadow-card', className)}>{children}</div>;
}

export function SectionTitle({ children, className }: PropsWithChildren<{ className?: string }>) {
  return <div className={clsx('text-xs font-semibold uppercase tracking-wide text-slate-500', className)}>{children}</div>;
}

export function Button({
  children,
  onClick,
  variant = 'primary',
  size = 'md',
  disabled
}: PropsWithChildren<{
  onClick?: () => void;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md';
  disabled?: boolean;
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
    <button onClick={onClick} disabled={disabled} className={clsx(base, sizes, variants[variant])}>
      {children}
    </button>
  );
}

export function Badge({ children, tone = 'slate' }: PropsWithChildren<{ tone?: 'slate' | 'green' | 'red' | 'amber' }>) {
  const tones: Record<string, string> = {
    slate: 'bg-slate-100 text-slate-700',
    green: 'bg-green-100 text-green-800',
    red: 'bg-red-100 text-red-800',
    amber: 'bg-amber-100 text-amber-800'
  };
  return <span className={clsx('inline-flex items-center rounded-full px-2 py-1 text-[11px] font-semibold', tones[tone])}>{children}</span>;
}
