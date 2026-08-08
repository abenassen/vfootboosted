import clsx from 'clsx';
import { Moon, Sun, SunMoon } from 'lucide-react';
import { Card, SectionTitle } from './ui';
import { useTheme, type ThemeChoice } from '../theme/ThemeContext';

/** Chiaro, scuro, o come il sistema.
 *
 *  Tre bottoni e non un interruttore a due stati: «come il sistema» è una terza
 *  risposta, non una via di mezzo. E si applica SUBITO, senza un «salva» — è
 *  l'unica impostazione il cui risultato si vede mentre la si sceglie, e
 *  chiedere una conferma per una cosa che si giudica a occhio sarebbe un passo
 *  in più per niente.
 */
const OPZIONI: { key: ThemeChoice; label: string; icon: typeof Sun; hint: string }[] = [
  { key: 'light', label: 'Chiaro', icon: Sun, hint: 'Fondo chiaro, sempre.' },
  { key: 'dark', label: 'Scuro', icon: Moon, hint: 'Fondo scuro, sempre.' },
  { key: 'system', label: 'Come il sistema', icon: SunMoon, hint: 'Segue il telefono o il computer.' },
];

export default function ThemeCard() {
  const { choice, resolved, setChoice } = useTheme();
  const attivo = OPZIONI.find((o) => o.key === choice);

  return (
    <Card className="p-4">
      <SectionTitle>Aspetto</SectionTitle>
      <div className="mt-2 flex flex-wrap gap-2">
        {OPZIONI.map(({ key, label, icon: Icona }) => {
          const on = key === choice;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setChoice(key)}
              aria-pressed={on}
              className={clsx(
                'inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm font-semibold transition',
                'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
                on
                  ? 'border-brand bg-brand text-on-brand'
                  : 'border-line bg-surface text-ink-soft hover:bg-surface-2',
              )}
            >
              <Icona size={16} aria-hidden />
              {label}
            </button>
          );
        })}
      </div>
      <div className="mt-2 text-xs text-ink-faint">
        {attivo?.hint}
        {/* Con «come il sistema» il risultato dipende da fuori, quindi si dice
            qual è adesso: altrimenti l'unica opzione delle tre che non si spiega
            da sola resta un'incognita. */}
        {choice === 'system' ? ` In questo momento: ${resolved === 'dark' ? 'scuro' : 'chiaro'}.` : ''}
      </div>
    </Card>
  );
}
