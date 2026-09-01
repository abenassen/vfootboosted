import { useEffect, useState } from 'react';

/** LE CIFRE DEL VOTO, IN UN POSTO SOLO.
 *
 *  Le stesse misure compaiono in due pagine — quella lunga dentro l'app
 *  (VotoPuroPage) e quella breve per chi non è iscritto (VotoPubblicoPage) — e
 *  due copie a mano sono due copie che divergono: basta ritarare il modello e
 *  aggiornarne una. Da qui le legge chi le mostra.
 *
 *  DA DOVE VENGONO. Non sono dati vivi: sono affermazioni sul modello, misurate
 *  sull'ultima stagione conclusa con ``manage.py build_voto_benchmark`` (cartella
 *  voto_benchmark/) più ``voto_puro_discrepancies`` per il confronto col rating
 *  di SofaScore. QUANDO SI RITARA IL MODELLO SI RIFANNO I DUE COMANDI E SI
 *  RISCRIVE QUESTO FILE — e `STAGIONE` dice al lettore a quando risale la
 *  verifica, che è l'unico modo che ha di sapere se sta leggendo il modello di
 *  oggi.
 *
 *  Ultima rimisura: 01/09/2026, con la ritaratura della creazione (xA sola,
 *  passaggi chiave a zero), il taglio delle conclusioni, i duelli asimmetrici in
 *  difesa e il gol subito pesato per il suo impatto. Tutte le cifre qui sotto
 *  sono rifatte insieme, sulla stessa passata: si sono mosse tutte, e nella
 *  stessa direzione — ci avviciniamo ai tre giudici su ogni ruolo.
 *
 *  Una cifra ha cambiato SEGNO oltre che valore, e vale la pena saperlo: le
 *  divergenze grosse erano 375 verso l'alto contro 244 verso il basso (eravamo
 *  sbilanciati a dare voti alti), adesso sono 289 contro 300. Il taglio delle
 *  conclusioni e della creazione ha tolto soprattutto dalla coda alta.
 */
export const VOTO = {
  /** La stagione su cui è misurato tutto quello che segue. */
  stagione: '2025-26',
  /** Presenze appaiate con entrambe le colonne di fantacalcio.it. */
  pagelle: '10.583',
  /** Quota dei nostri voti entro mezzo punto dalla pagella. */
  entroMezzo: '89,9%',
  /** …ed entro un punto. */
  entroUno: '98,9%',
  /** Scarto medio, in punti di voto. */
  scartoMedio: '0,33',
  /** I casi fuori da ENTRAMBE le letture di fantacalcio.it di almeno un punto. */
  divergenze: { casi: '589', quota: '5,6%', alto: '289', basso: '300' },
  /** Quanto il nostro voto e le due colonne di fantacalcio.it somigliano al
   *  rating di SofaScore, che non entra mai nel nostro calcolo (1 = identico).
   *  Misurato sui giocatori che non hanno segnato: il gol mette tutti d'accordo
   *  e coprirebbe il resto. */
  correlazione: [
    { ruolo: 'Portieri', noi: '0,79', redazione: '0,62', statistico: '0,66' },
    { ruolo: 'Difensori', noi: '0,76', redazione: '0,58', statistico: '0,64' },
    { ruolo: 'Centrocampisti', noi: '0,72', redazione: '0,50', statistico: '0,57' },
    { ruolo: 'Attaccanti', noi: '0,65', redazione: '0,48', statistico: '0,51' },
  ],
  /** Quanti voti sono esattamente 6, da noi e nelle pagelle: la nostra prudenza,
   *  in una cifra. */
  quotaSei: { noi: '41%', pagelle: '36%' },
} as const;

/** IL BENCHMARK, SE C'È ANCORA.
 *
 *  Le 38 pagine con tutti i nostri voti a fianco di quelli di fantacalcio.it le
 *  serve nginx accanto all'app, non l'app: sono materiale di verifica, e un
 *  giorno se ne andranno. Perciò il link non si scrive, si CHIEDE — se la
 *  cartella non c'è più, nginx risponde 404 e il link sparisce da sé invece di
 *  restare a puntare al nulla.
 *
 *  In sviluppo Vite risponde 200 a qualunque indirizzo (rimanda tutto all'app),
 *  quindi lì il link si vede sempre e porta al 404 dell'applicazione. È il falso
 *  positivo che ci si può permettere: in sviluppo quella cartella non c'è mai.
 */
export const BENCHMARK_URL = '/benchmark-voto/';

export function useBenchmarkAvailable(): boolean {
  const [there, setThere] = useState(false);
  useEffect(() => {
    let alive = true;
    void fetch(BENCHMARK_URL, { method: 'HEAD', cache: 'no-store' })
      .then((r) => {
        if (alive) setThere(r.ok);
      })
      .catch(() => {
        if (alive) setThere(false);
      });
    return () => {
      alive = false;
    };
  }, []);
  return there;
}
