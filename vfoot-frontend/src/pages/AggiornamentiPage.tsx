import { useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Card, SectionTitle } from '../components/ui';
import { ETICHETTE, RILASCI, type TipoVoce, type Voce } from '../content/noteDiRilascio';

/** AGGIORNAMENTI — l'archivio delle patch.
 *
 *  Il testo sta in `content/noteDiRilascio.ts`; qui c'è solo come si legge. La
 *  separazione non è cerimonia: la nota di una modifica va scritta insieme alla
 *  modifica, e chi la scrive deve poterlo fare senza aprire un componente React.
 *
 *  La forma è quella delle patch di un gioco perché è la forma giusta per il
 *  problema: un elenco di voci corte, ognuna marchiata con che TIPO di
 *  cambiamento è, e sotto — quando c'è — il caso concreto che l'ha provocata.
 *  Chi legge non vuole un racconto, vuole sapere se qualcosa che lo riguarda si
 *  è mosso, e in quale verso.
 *
 *  IL «BILANCIAMENTO» È LA CATEGORIA CHE CONTA. Le altre tre le ha qualunque
 *  applicazione. Questa dice che il voto è cambiato — cioè che lo stesso
 *  giocatore, con la stessa partita, oggi prenderebbe un numero diverso — ed è
 *  l'unica cosa che un fantallenatore ha il diritto di vedere scritta invece di
 *  doverla dedurre. Per questo ha il colore acceso, e l'intestazione della pagina
 *  spiega che cosa vuol dire quell'etichetta prima ancora del primo rilascio.
 *
 *  Nessuna chiamata al backend: è un file di testo, e un endpoint per servirlo
 *  sarebbe un giro di rete per ripetere quello che il bundle ha già.
 */

/* L'ORDINE È QUELLO SCRITTO NEL FILE, e non un riordino per categoria. Ci ho
 * provato — bilanciamento in cima, correzioni in fondo, la regola che sembra
 * ovvia — e la prima patch a cui l'ho applicata ha sepolto in fondo alla lista
 * il modificatore difesa, cioè la voce che dà il titolo al rilascio e l'unica
 * che avesse cambiato una classifica. Una regola meccanica non sa qual è la
 * notizia; chi scrive la nota sì, e la scrive per prima. Le etichette colorate
 * fanno già il lavoro che il raggruppamento avrebbe fatto: si trova a colpo
 * d'occhio quello che si cerca senza togliere all'autore il primo posto. */

const TONI: Record<TipoVoce, string> = {
  bilanciamento: 'bg-warn-bg text-warn',
  nuovo: 'bg-good-bg text-good',
  migliorato: 'bg-live-bg text-live',
  corretto: 'bg-surface-2 text-ink-soft border border-line',
};

export default function AggiornamentiPage() {
  const { hash } = useLocation();
  // Arrivare con un'ancora (#v-1-8, dall'annuncio o da un link condiviso) deve
  // portare a quella versione e non in cima: l'archivio cresce, e fra sei mesi
  // la versione citata sarà a metà pagina.
  useEffect(() => {
    if (!hash) return;
    const el = document.getElementById(hash.slice(1));
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [hash]);

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 pb-16">
      <header className="space-y-2">
        <h1 className="font-cond text-2xl font-bold text-ink">Aggiornamenti</h1>
        <p className="text-sm text-ink-soft">
          Che cosa è cambiato sul sito, versione per versione. Le voci segnate{' '}
          <Tag tipo="bilanciamento" /> toccano il <b className="text-ink">voto puro</b>: vuol dire
          che lo stesso giocatore, nella stessa partita, oggi prenderebbe un numero diverso da
          prima. Dove il cambiamento nasce da una partita precisa, la partita è scritta.
        </p>
      </header>

      {/* L'indice delle versioni: la pagina è lunga per costruzione e cresce di
          una sezione a settimana. */}
      <Card className="p-4">
        <SectionTitle>Le versioni</SectionTitle>
        <nav className="mt-2 flex flex-wrap gap-1.5">
          {RILASCI.map((r) => (
            <a
              key={r.id}
              href={`#${r.id}`}
              className="rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-xs font-semibold text-ink-soft hover:bg-line/50"
            >
              {r.versione} · {r.data.replace(/ \d{4}$/, '')}
            </a>
          ))}
        </nav>
      </Card>

      {RILASCI.map((r, i) => (
        <Card key={r.id} id={r.id} className="scroll-mt-20 p-4">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="font-cond text-xl font-bold text-ink">{r.versione}</span>
            {/* L'ultima uscita si marca, perché è la domanda con cui quasi
                tutti aprono questa pagina. */}
            {i === 0 ? (
              <span className="rounded-full bg-brand/15 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-brand-strong">
                l’ultima
              </span>
            ) : null}
            <span className="text-xs text-ink-faint">{r.data}</span>
          </div>
          <h2 className="mt-1 font-cond text-lg font-bold text-ink">{r.titolo}</h2>
          {r.sommario ? <p className="mt-1 text-sm text-ink-soft">{r.sommario}</p> : null}

          <ul className="mt-3 space-y-2.5">
            {r.voci.map((v, j) => (
              <VoceRiga key={j} voce={v} />
            ))}
          </ul>
        </Card>
      ))}

      <Card className="p-4">
        <p className="text-sm text-ink-soft">
          Come si arriva al numero — la media del ruolo, che cosa alza e che cosa abbassa, dove ci
          allontaniamo dalle pagelle e perché — sta nella pagina{' '}
          <Link
            to="/voto-puro"
            className="font-semibold text-accent underline decoration-dotted"
          >
            Come nasce il voto puro
          </Link>
          . Questa dice solo che cosa si è mosso, e quando.
        </p>
      </Card>
    </div>
  );
}

function VoceRiga({ voce }: { voce: Voce }) {
  return (
    <li className="flex flex-col gap-1 border-t border-line pt-2.5 first:border-0 first:pt-0 sm:flex-row sm:gap-3">
      <Tag tipo={voce.tipo} />
      <div className="min-w-0 flex-1">
        <div className="text-sm text-ink">{voce.testo}</div>
        {voce.caso ? (
          // Il caso in corsivo e più piccolo: è la prova, non l'affermazione, e
          // chi si fida della riga sopra non ha bisogno di leggerlo.
          <div className="mt-1 text-xs italic leading-snug text-ink-faint">{voce.caso}</div>
        ) : null}
      </div>
    </li>
  );
}

function Tag({ tipo }: { tipo: TipoVoce }) {
  return (
    <span
      className={`inline-flex h-fit w-fit shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide sm:w-28 sm:justify-center ${TONI[tipo]}`}
    >
      {ETICHETTE[tipo]}
    </span>
  );
}
