import { useEffect, useState } from 'react';
import { applyUpdate, onUpdateReady } from '../pwa/registerSW';

/** "New version available." Shown, not applied.
 *
 *  An installed app that is never fully closed would otherwise stay on the old
 *  build indefinitely — but reloading by ourselves, under someone placing a bid,
 *  is worse than being a version behind. So the choice is offered and stays
 *  offered until taken.
 */
export default function UpdateBanner() {
  const [ready, setReady] = useState(false);
  useEffect(() => onUpdateReady(setReady), []);
  if (!ready) return null;
  return (
    <div className="fixed inset-x-0 bottom-16 z-50 mx-auto w-fit max-w-[95vw] md:bottom-4">
      <div className="flex items-center gap-3 rounded-2xl bg-ink px-4 py-2.5 text-paper shadow-card">
        <span className="text-sm font-semibold">È disponibile una nuova versione.</span>
        <button
          type="button"
          onClick={applyUpdate}
          className="rounded-xl bg-surface px-3 py-1 text-sm font-bold text-ink"
        >
          Aggiorna
        </button>
      </div>
    </div>
  );
}
