import { useEffect, useState } from 'react';
import { getProbableLineups } from '../../api';
import type { ProbableLineups as Data, ProbablePlayer } from '../../types/realChampionship';

// LE PROBABILI FORMAZIONI di una partita non ancora giocata.
//
// La scelta di fondo è che la banda conta più del numero. Le fonti sbagliano un
// titolare su sette (fantacalcio.it 85,2% sulla 25-26, la nostra stima da sola
// il 75%), quindi «74%» scritto in grande prometterebbe una precisione che non
// esiste: il colore dice quanto fidarsi, il numero è lì per chi lo vuole.
//
// E dice sempre CHI sta parlando. Una previsione fatta solo dalle nostre
// presenze e una che ha visto le notizie non sono la stessa cosa.

// Il colore misura quanto è probabile che giochi, e lo misura sempre nello stesso
// verso: più è alto più è acceso. Niente picco giallo a metà scala — la prima
// versione codificava l'incertezza e finiva per gridare su un 40% più che su un
// 26%, che nella stessa lista è una contraddizione. Il rosso resta un fatto:
// indisponibile, non "improbabile".
function band(p: ProbablePlayer): { cls: string; label: string } {
  if (p.status === 'out') return { cls: 'bg-bad text-white', label: 'Indisponibile' };
  if (p.probability === 100) return { cls: 'bg-good/25 text-good', label: 'In campo' };
  if (p.probability >= 85) return { cls: 'bg-good/20 text-good', label: 'Titolare' };
  if (p.probability >= 60) return { cls: 'bg-good/10 text-good', label: 'Favorito' };
  if (p.probability >= 40) return { cls: 'bg-surface-2 text-ink-soft', label: 'Ballottaggio' };
  return { cls: 'bg-surface-2 text-ink-faint', label: 'Panchina' };
}

// L'ORDINE DI LETTURA di una formazione: portiere, difesa, centrocampo, attacco.
// Ordinare per percentuale decrescente metteva insieme gente che non c'entra —
// il portiere al 99% accanto al centravanti, il terzino di riserva in mezzo ai
// centrocampisti — e obbligava a rileggere la lista per capire chi gioca dove.
// È anche l'ordine con cui la stessa partita si legge a fine giornata nella
// pagella, che sta due schede più in là.
//
// Il backend manda già le righe così; qui si riordina lo stesso, perché le
// sezioni si ritagliano per probabilità (v. `Side`) e il taglio scompagina.
const ROLE_ORDER: Record<string, number> = { POR: 0, DIF: 1, CEN: 2, ATT: 3 };
const ROLE_SHORT: Record<string, string> = { POR: 'P', DIF: 'D', CEN: 'C', ATT: 'A' };

function byRole(a: ProbablePlayer, b: ProbablePlayer): number {
  return (
    (ROLE_ORDER[a.role] ?? 9) - (ROLE_ORDER[b.role] ?? 9) ||
    b.probability - a.probability ||
    a.name.localeCompare(b.name)
  );
}

function Row({ p }: { p: ProbablePlayer }) {
  const b = band(p);
  // Solo un movimento vero merita una freccia: sotto i cinque punti è rumore
  // della ricalibrazione, non una notizia.
  const delta = p.previous == null ? 0 : p.probability - p.previous;
  const arrow = Math.abs(delta) >= 5 ? (delta > 0 ? '↑' : '↓') : null;
  return (
    <li className="flex items-center gap-2 py-1">
      <span className={`w-11 shrink-0 rounded px-1 py-0.5 text-center font-mono text-[11px] font-bold ${b.cls}`}>
        {p.status === 'out' ? '—' : `${p.probability}%`}
      </span>
      {/* La lettera del ruolo: non è un'abbreviazione da indovinare, è la conferma
          di un raggruppamento che si vede già dall'ordine. Resta muta quando il
          ruolo non lo sappiamo, invece di inventare una C. */}
      <span className="w-2.5 shrink-0 text-center font-mono text-[10px] text-ink-faint">
        {ROLE_SHORT[p.role] ?? ''}
      </span>
      <span className={p.status === 'out' ? 'text-ink-faint line-through' : 'text-ink-soft'}>
        {p.name}
      </span>
      {arrow ? (
        <span className={`text-[11px] font-bold ${delta > 0 ? 'text-good' : 'text-bad'}`}>
          {arrow}
          {Math.abs(delta)}
        </span>
      ) : null}
      {p.reason ? <span className="text-[11px] text-ink-faint">· {p.reason}</span> : null}
    </li>
  );
}

function Side({ team, formation, players }: { team: string; formation: string; players: ProbablePlayer[] }) {
  const xi = players.filter((p) => p.status === 'starter').sort(byRole);
  // Chi entra nella lista corta lo decide la probabilità — sono i primi rincalzi,
  // non i primi difensori — ma una volta scelti si leggono per ruolo come gli altri.
  const rest = players
    .filter((p) => p.status !== 'starter' && p.probability > 0)
    .sort((a, b) => b.probability - a.probability)
    .slice(0, 6)
    .sort(byRole);
  const out = players.filter((p) => p.status === 'out').sort(byRole);
  return (
    <div className="min-w-0 flex-1">
      <div className="flex items-baseline gap-2">
        <span className="font-semibold text-ink">{team}</span>
        {formation ? <span className="font-mono text-xs text-ink-faint">{formation}</span> : null}
      </div>
      <ul className="mt-1 text-sm">
        {xi.map((p) => (
          <Row key={p.player_id} p={p} />
        ))}
      </ul>
      {rest.length ? (
        <>
          <div className="mt-2 text-[10px] uppercase tracking-wide text-ink-faint">In dubbio / panchina</div>
          <ul className="text-sm">
            {rest.map((p) => (
              <Row key={p.player_id} p={p} />
            ))}
          </ul>
        </>
      ) : null}
      {out.length ? (
        <>
          <div className="mt-2 text-[10px] uppercase tracking-wide text-ink-faint">Indisponibili</div>
          <ul className="text-sm">
            {out.map((p) => (
              <Row key={p.player_id} p={p} />
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

const SOURCE_LABEL: Record<string, string> = {
  vfoot: 'nostra stima',
  sofascore: 'SofaScore',
};

export default function ProbableLineups({ matchId }: { matchId: number }) {
  const [data, setData] = useState<Data | null>(null);
  const [state, setState] = useState<'loading' | 'empty' | 'ready' | 'error'>('loading');

  useEffect(() => {
    let alive = true;
    void getProbableLineups(matchId)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setState(d ? 'ready' : 'empty');
      })
      .catch(() => alive && setState('error'));
    return () => {
      alive = false;
    };
  }, [matchId]);

  if (state === 'loading') return <div className="py-2 text-xs text-ink-faint">Caricamento…</div>;
  if (state === 'error') return <div className="py-2 text-xs text-bad">Probabili non disponibili.</div>;
  if (state === 'empty' || !data)
    return (
      <div className="py-2 text-xs text-ink-faint">
        Nessuna probabile formazione: troppo presto perché le fonti abbiano scritto.
      </div>
    );

  const when = new Date(data.refreshed_at).toLocaleString('it-IT', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
  const sources = data.sources.map((s) => SOURCE_LABEL[s] ?? s).join(' + ');

  return (
    <div className="pt-2">
      <div className="flex flex-wrap items-center gap-x-2 text-[11px] text-ink-faint">
        {/* «Probabili» e «ufficiali» non sono la stessa cosa, e il passaggio
            dall'una all'altra — circa un'ora prima del calcio d'inizio — è il
            momento che chi deve ancora schierare sta aspettando. */}
        {data.official ? (
          <span className="font-bold uppercase tracking-wide text-good">
            Formazioni ufficiali
          </span>
        ) : (
          <span className="font-semibold uppercase tracking-wide">Probabili</span>
        )}
        <span>· {sources}</span>
        <span>· letta {when}</span>
      </div>
      {/* Detto una volta e senza mezzi termini: se parla solo il nostro motore,
          chi legge sta guardando una statistica sulle ultime giornate, non una
          notizia. Sono due cose diverse e la differenza si vede in campo. */}
      {!data.official && data.sources.length === 1 && data.sources[0] === 'vfoot' ? (
        <div className="mt-1 text-[11px] text-warn">
          Solo dalla nostra stima sulle ultime giornate: non tiene conto delle notizie.
        </div>
      ) : null}
      <div className="mt-2 flex flex-col gap-4 sm:flex-row sm:gap-6">
        <Side team={data.home_team} formation={data.home.formation} players={data.home.players} />
        <Side team={data.away_team} formation={data.away.formation} players={data.away.players} />
      </div>
    </div>
  );
}
