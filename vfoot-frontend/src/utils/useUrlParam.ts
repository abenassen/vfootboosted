import { useCallback, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';

/** UN PEZZO DI STATO CHE STA NELL'INDIRIZZO invece che dentro il componente.
 *
 *  Serve dove la scelta deve sopravvivere a un'ANDATA E RITORNO. Si sfoglia il
 *  calendario fino alla giornata 2, si apre una partita, si torna indietro — e
 *  con la giornata tenuta in `useState` si ripartiva dalla giornata corrente,
 *  perché tornare indietro rimonta la pagina da zero e lo stato di prima non
 *  esiste più. Chi stava guardando una giornata passata voleva aprirne più di una
 *  partita, e ogni volta doveva ritrovarsi la giornata a mano.
 *
 *  Nell'indirizzo, invece, la scelta torna con la cronologia — sia col tasto del
 *  browser sia col «← Serie A» della pagina, che ci si porta dietro la giornata —
 *  e per giunta il collegamento si può mandare a qualcuno.
 *
 *  SEMPRE `replace`, mai `push`: ogni giornata sfogliata sarebbe una tappa della
 *  cronologia, e «indietro» invece di uscire dal calendario ripercorrerebbe a
 *  ritroso tutte le giornate guardate.
 */
export function useUrlParam(name: string) {
  const [params, setParams] = useSearchParams();
  const set = useCallback(
    (value: string | number | null) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value == null || value === '') next.delete(name);
          else next.set(name, String(value));
          return next;
        },
        { replace: true },
      );
    },
    [name, setParams],
  );
  return [params.get(name), set] as const;
}

/** Esegue `reset` quando `key` CAMBIA, non alla sua prima comparsa.
 *
 *  L'effetto scritto nel modo ovvio — «quando cambia il campionato dimentica la
 *  giornata scelta, che è di un altro calendario» — parte anche al montaggio, e
 *  al montaggio cancellerebbe proprio la giornata appena ripescata
 *  dall'indirizzo: il ritorno dal tabellino tornerebbe a essere quello di prima,
 *  con l'aggravante che il difetto starebbe nella riga scritta per risolverlo.
 *
 *  E `key` nulla vuol dire NON ANCORA SAPUTA, non «nessuna»: la lega e il
 *  campionato guardato arrivano da un contesto che si risolve dopo il primo
 *  render, e leggere quel passaggio come un cambiamento sarebbe lo stesso
 *  azzeramento di prima, solo un giro più tardi. Il primo valore vero fa da
 *  riferimento in silenzio; si azzera dal secondo in poi.
 */
export function useResetOnChange(key: unknown, reset: () => void) {
  const seen = useRef<unknown>(undefined);
  useEffect(() => {
    if (key == null) return;
    if (seen.current === undefined) {
      seen.current = key;
      return;
    }
    if (seen.current === key) return;
    seen.current = key;
    reset();
  }, [key, reset]);
}
