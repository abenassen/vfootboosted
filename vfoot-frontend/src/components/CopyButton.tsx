import { useState } from 'react';
import clsx from 'clsx';

// Small "copy to clipboard" button used for the league invite code. Shows a brief
// "Copiato!" confirmation, then reverts. Falls back to a legacy execCommand path
// when the async Clipboard API is unavailable (older mobile browsers / non-HTTPS
// LAN testing, where navigator.clipboard is often undefined).
export default function CopyButton({
  value,
  label = 'Copia',
  className,
}: {
  value: string;
  label?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        const ta = document.createElement('textarea');
        ta.value = value;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — leave the code visible for manual copy */
    }
  }

  return (
    <button
      type="button"
      onClick={() => void copy()}
      className={clsx(
        'inline-flex items-center gap-1 rounded-lg border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-100',
        copied && 'border-emerald-300 bg-emerald-50 text-emerald-700',
        className,
      )}
      aria-label={`Copia: ${value}`}
    >
      <span>{copied ? '✓' : '📋'}</span>
      {copied ? 'Copiato!' : label}
    </button>
  );
}
