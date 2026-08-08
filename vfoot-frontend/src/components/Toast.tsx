import { useEffect } from 'react';
import clsx from 'clsx';

export default function Toast({ message, onClose, tone = 'slate' }: { message: string; onClose: () => void; tone?: 'slate' | 'green' | 'red' | 'amber' }) {
  useEffect(() => {
    const t = setTimeout(onClose, 2600);
    return () => clearTimeout(t);
  }, [onClose]);

  const tones: Record<string, string> = {
    slate: 'bg-ink text-paper',
    green: 'bg-good text-white',
    red: 'bg-bad text-white',
    amber: 'bg-warn text-white'
  };

  return (
    <div className={clsx('fixed left-1/2 bottom-20 z-50 -translate-x-1/2 rounded-2xl px-4 py-3 text-sm font-semibold shadow-lg', tones[tone])}>
      {message}
    </div>
  );
}
