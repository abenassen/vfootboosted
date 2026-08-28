import { useCallback, useEffect, useState } from 'react';
import { getNews, markNewsSeen } from '../api';
import type { NewsItem } from '../types/news';

/** COSA È CAMBIATO NELL'APPLICAZIONE, in due righe e una volta sola.
 *
 *  Non è la bacheca (quella racconta cosa è successo in una lega, e la scrive il
 *  gioco) e non è `UpdateBanner` (che dice che c'è una versione da caricare, un
 *  fatto tecnico che si risolve premendo un bottone). Qui si dice cosa quella
 *  versione ha portato, che è l'unica parte che interessa a chi gioca.
 *
 *  Sta IN CIMA AL CONTENUTO e non fissa in fondo allo schermo: `UpdateBanner` è
 *  già lì e due strisce sovrapposte sono una striscia sola illeggibile. E in cima
 *  si legge scendendo, mentre una striscia fissa la si chiude per toglierla di
 *  mezzo — che è il contrario di leggerla.
 *
 *  Si chiude e non torna: il segnalibro è sul server (`news_seen_at`), quindi
 *  vale su ogni dispositivo, e chi la chiude sul telefono non se la ritrova sul
 *  portatile. È l'unica ragione per cui questo stato non sta in `localStorage`. */
export default function NewsBanner() {
  const [items, setItems] = useState<NewsItem[]>([]);

  useEffect(() => {
    let alive = true;
    void getNews()
      .then((r) => alive && setItems(r.items))
      // Un annuncio che non arriva non è un errore da mostrare: si tace.
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  const dismiss = useCallback(() => {
    // Il segnalibro va sulla più recente FRA QUELLE MOSTRATE (la lista arriva
    // dalla più nuova alla più vecchia), non su «adesso»: nei secondi fra
    // l'apertura e il click può uscirne un'altra, e seppellirla senza che
    // nessuno l'abbia vista è esattamente il fallimento che questo canale deve
    // evitare.
    const newest = items[0];
    setItems([]);
    if (newest) void markNewsSeen(newest.id).catch(() => undefined);
  }, [items]);

  if (items.length === 0) return null;

  return (
    <div className="mb-4 rounded-2xl border border-line bg-surface-2 p-3">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 shrink-0 rounded-lg bg-ink px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-paper">
          Novità
        </span>
        <div className="min-w-0 flex-1 space-y-2">
          {items.map((n) => (
            <div key={n.id}>
              <div className="text-sm font-bold text-ink">{n.title}</div>
              {n.body ? (
                <div className="text-[13px] leading-snug text-ink-soft">{n.body}</div>
              ) : null}
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={dismiss}
          className="shrink-0 rounded-lg px-2 py-1 text-xs font-semibold text-ink-soft hover:bg-surface"
          aria-label="Ho letto le novità"
        >
          Ho capito
        </button>
      </div>
    </div>
  );
}
