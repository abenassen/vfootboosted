import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

/** Chiaro, scuro, o quello che dice il sistema.
 *
 *  Tre scelte e non due, perché "come il sistema" è una risposta diversa da
 *  entrambe: chi tiene il telefono in scuro dalle sette di sera vuole che l'app
 *  lo segua, e chi ha scelto chiaro vuole il chiaro anche a sistema scuro. Con
 *  due sole opzioni una delle due persone non è servita.
 */
export type ThemeChoice = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'vfoot_theme';
const SYSTEM_DARK = '(prefers-color-scheme: dark)';

type ThemeValue = {
  /** Quello che l'utente ha scelto. */
  choice: ThemeChoice;
  /** Quello che si vede adesso — con 'system' dipende dall'ora del telefono. */
  resolved: 'light' | 'dark';
  setChoice: (c: ThemeChoice) => void;
};

const ThemeContext = createContext<ThemeValue | undefined>(undefined);

function readChoice(): ThemeChoice {
  if (typeof window === 'undefined') return 'light';
  const saved = window.localStorage.getItem(STORAGE_KEY);
  return saved === 'dark' || saved === 'light' || saved === 'system' ? saved : 'light';
}

function systemIsDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia(SYSTEM_DARK).matches;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(readChoice);
  const [systemDark, setSystemDark] = useState(systemIsDark);

  // Il sistema può cambiare mentre l'app è aperta (il tramonto, o un
  // interruttore in un'altra finestra): con 'system' la pagina deve seguirlo
  // senza essere ricaricata.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia(SYSTEM_DARK);
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  const resolved: 'light' | 'dark' =
    choice === 'system' ? (systemDark ? 'dark' : 'light') : choice;

  // L'attributo sulla RADICE, che è ciò che i token leggono (styles/index.css)
  // e su cui Tailwind aggancia la variante scura.
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', resolved);
  }, [resolved]);

  const setChoice = useCallback((c: ThemeChoice) => {
    setChoiceState(c);
    if (typeof window !== 'undefined') window.localStorage.setItem(STORAGE_KEY, c);
  }, []);

  const value = useMemo(() => ({ choice, resolved, setChoice }), [choice, resolved, setChoice]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}
