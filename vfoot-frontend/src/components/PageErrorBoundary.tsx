import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Card, Button } from './ui';

/** Keeps one broken page from taking the whole app down.
 *
 *  Written after a missing field in one player row out of fifty rendered a blank
 *  document: React unmounts the entire tree when nothing catches, so the cost of a
 *  bad row was the page, the navigation and every explanation of what went wrong.
 *  A white screen is also the hardest failure to report — there is nothing on it to
 *  describe.
 *
 *  It wraps the OUTLET and not the app: the shell (league switcher, navigation) is
 *  what lets you leave a broken page, so it must survive it. And it is keyed on the
 *  route, because an error boundary that has caught stays caught — without a key,
 *  navigating away from the broken page would keep showing this card over pages
 *  that are perfectly fine.
 *
 *  It is a net, not a fix: what it catches is still a bug, and the console still
 *  carries the stack that names it.
 */
export class PageErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // React logs this in development; in production this is the only trace left,
    // and the component stack is the part that says WHICH row blew up.
    console.error('[vfoot] pagina interrotta da un errore', error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <Card className="p-6 text-center">
        <div className="text-3xl">⚠️</div>
        <div className="mt-2 font-bold">Questa pagina si è interrotta</div>
        <p className="mx-auto mt-1 max-w-md text-sm text-slate-600">
          Il resto dell&apos;applicazione funziona: puoi cambiare pagina dal menu. Se
          succede di nuovo sulla stessa pagina, è un difetto da segnalare — il
          dettaglio tecnico è qui sotto.
        </p>
        <p className="mx-auto mt-3 max-w-md break-words rounded bg-slate-100 px-3 py-2 text-left font-mono text-[11px] text-slate-600">
          {error.message || String(error)}
        </p>
        <Button className="mt-4" size="sm" onClick={() => window.location.reload()}>
          Ricarica la pagina
        </Button>
      </Card>
    );
  }
}
