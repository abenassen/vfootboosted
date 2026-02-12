import { useEffect } from 'react';
import clsx from 'clsx';

export default function Toast({ message, onClose, tone = 'slate' }: { message: string; onClose: () => void; tone?: 'slate' | 'green' | 'red' | 'amber' }) {
  useEffect(() => {
    const t = setTimeout(onClose, 2600);
    return () => clearTimeout(t);
  }, [onClose]);

  const tones: Record<string, string> = {
    slate: 'bg-slate-900 text-white',
    green: 'bg-green-600 text-white',
    red: 'bg-red-600 text-white',
    amber: 'bg-amber-500 text-white'
  };

  return (
    <div className={clsx('fixed left-1/2 bottom-20 z-50 -translate-x-1/2 rounded-2xl px-4 py-3 text-sm font-semibold shadow-lg', tones[tone])}>
      {message}
    </div>
  );
}
