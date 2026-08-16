import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getChampionshipPlayers, getLeagueDetail, openRoleDecision } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { useChampionship } from '../league/ChampionshipContext';
import { DECISIONS_CHANGED, useDecisionAlerts } from '../league/useDecisionAlerts';
import ChampionshipPicker from '../components/ChampionshipPicker';
import { foldedMatch } from '../utils/text';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type { ChampionshipPlayer, ChampionshipPlayersResponse } from '../types/realChampionship';

// Listone: the full player pool of a championship, with role / free-agent /
// search filters and value sorting. Value = average voto puro from the latest
// season with data.
//
// Senza lega la pagina resta la stessa meno quello che una lega ha di suo: chi
// possiede chi, i ruoli congelati, l'esportazione per l'asta. È la vetrina di chi
// si è appena iscritto — il valore dei giocatori secondo i nostri voti.
type SortKey = 'name' | 'team' | 'value' | 'appearances' | 'market';

const ROLES = ['POR', 'DIF', 'CEN', 'ATT'] as const;
const ROLE_NAMES: Record<string, string> = {
  POR: 'Portiere',
  DIF: 'Difensore',
  CEN: 'Centrocampista',
  ATT: 'Attaccante',
};
const ROLE_CHIP: Record<string, string> = {
  POR: 'bg-warn',
  DIF: 'bg-blue-500',
  CEN: 'bg-good',
  ATT: 'bg-orange-500',
};

export default function ListonePage() {
  const { selectedLeagueId } = useLeagueContext();
  const { scope, browsing, loading: scopeLoading } = useChampionship();
  const { isAdmin } = useDecisionAlerts(selectedLeagueId);
  const [data, setData] = useState<ChampionshipPlayersResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [role, setRole] = useState<string>('ALL');
  const [freeOnly, setFreeOnly] = useState(false);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortKey>('value');
  const [desc, setDesc] = useState(true);
  const [ratedOnly, setRatedOnly] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);

  // Quanto della tabella si VEDE. La riga aperta sotto un giocatore ha colSpan su
  // tutte le colonne, quindi è larga quanto la TABELLA — che su uno schermo stretto
  // è più larga della finestra e scorre. Misurato su un telefono: tabella 504px in
  // 325px visibili, cioè 179px di spiegazione scritti fuori dallo schermo, tagliati
  // a metà parola. Il numero non si può scrivere in CSS (la cella non sa nulla del
  // contenitore che scorre), quindi si misura, e si rimisura quando la finestra
  // cambia — una rotazione del telefono lo sposta.
  // Un ref-CALLBACK e non un useEffect su un ref normale: questa pagina esce
  // presto («Caricamento listone…») e la tabella entra nel DOM solo dopo che i
  // dati sono arrivati. Un effetto con dipendenze vuote gira su quel primo render,
  // trova il ref ancora nullo e non riprova mai — la misura resta null e la
  // larghezza non viene applicata, che è esattamente come questa correzione ha
  // fallito la prima volta. Il callback invece scatta quando il nodo si attacca.
  const [visibleWidth, setVisibleWidth] = useState<number | null>(null);
  const observerRef = useRef<ResizeObserver | null>(null);
  const setScrollEl = useCallback((el: HTMLDivElement | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!el) return;
    setVisibleWidth(el.clientWidth);
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setVisibleWidth(el.clientWidth));
    ro.observe(el);
    observerRef.current = ro;
  }, []);

  async function exportXlsx() {
    if (!selectedLeagueId || !data) return;
    setExporting(true);
    try {
      // Team names for the per-player dropdown come from the league detail; the
      // ExcelJS module is heavy, so both are loaded only on demand.
      const [detail, mod] = await Promise.all([
        getLeagueDetail(selectedLeagueId),
        import('../utils/listoneXlsx'),
      ]);
      const teamNames = detail.teams.map((t) => t.name);
      await mod.downloadListoneXlsx(data, teamNames, detail.name);
    } finally {
      setExporting(false);
    }
  }

  // Click a column to sort by it; click again to flip. Numeric columns start
  // descending (best first), text columns ascending.
  function toggleSort(key: SortKey) {
    if (key === sort) setDesc(!desc);
    else {
      setSort(key);
      setDesc(key !== 'name' && key !== 'team');
    }
  }

  // Il ruolo si può rimettere in discussione solo DENTRO la lega che si
  // amministra: fuori non c'è un listone congelato su cui aprire una domanda, e
  // la stessa pagina serve anche a chi sta solo guardando un altro campionato.
  const canQuestionRoles = isAdmin && !browsing && selectedLeagueId != null;

  const questionRole = useCallback(
    async (playerId: number) => {
      if (selectedLeagueId == null) return;
      await openRoleDecision(selectedLeagueId, playerId);
      // La riga si aggiorna qui invece di ricaricare tutto il listone: la
      // risposta dice già com'è finita, e una tabella da 632 righe che sfarfalla
      // per un pulsante è un prezzo che non serve pagare.
      setData((d) =>
        d
          ? {
              ...d,
              players: d.players.map((p) =>
                p.player_id === playerId ? { ...p, role_undecided: true } : p,
              ),
            }
          : d,
      );
      // ...e il badge nella barra laterale, che conta le domande aperte.
      window.dispatchEvent(
        new CustomEvent(DECISIONS_CHANGED, { detail: { leagueId: selectedLeagueId } }),
      );
    },
    [selectedLeagueId],
  );

  // `scope` come dipendenza: il contesto lo memoizza, quindi cambia identità solo
  // quando cambia davvero la lega o la stagione che si sta guardando.
  useEffect(() => {
    if (!scope) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    void getChampionshipPlayers(scope)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [scope]);

  const shown = useMemo(() => {
    let ps = data?.players ?? [];
    if (role !== 'ALL') ps = ps.filter((p) => p.role === role);
    if (freeOnly) ps = ps.filter((p) => !p.owned);
    if (ratedOnly) ps = ps.filter((p) => typeof p.value === 'number');
    // Every field on the row, not just the abbreviated name — the list shows
    // "L. Martínez", so "Lautaro" used to find nothing, and neither did the role
    // or the owning team. Accents are folded too: nobody types "Leão".
    if (search.trim()) {
      ps = ps.filter((p) =>
        foldedMatch(search, [p.name, p.full_name, p.team, p.role, p.owner, p.value_basis]),
      );
    }

    const num = (p: ChampionshipPlayer): number | null => {
      if (sort === 'value') return p.estimated_value ?? p.value ?? null;
      if (sort === 'market') return p.market_value ?? null;
      if (sort === 'appearances') return p.appearances ?? 0;
      return null;
    };
    const text = (p: ChampionshipPlayer) => (sort === 'team' ? (p.team ?? '') : p.name);

    const sorted = [...ps].sort((a, b) => {
      if (sort === 'name' || sort === 'team') {
        const c = text(a).localeCompare(text(b));
        return desc ? -c : c;
      }
      const av = num(a);
      const bv = num(b);
      // players without the value always sink, whatever the direction
      if (av == null || bv == null) return Number(av == null) - Number(bv == null);
      const c = bv - av;
      return desc ? c : -c;
    });
    return sorted;
  }, [data, role, freeOnly, ratedOnly, search, sort, desc]);

  if (loading || scopeLoading) return <div className="text-sm text-ink-faint">Caricamento listone…</div>;
  if (error) return <div className="text-sm text-bad">Errore: {error}</div>;
  if (!scope)
    return <div className="text-sm text-ink-faint">Nessun campionato in corso da mostrare.</div>;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <SectionTitle>Listone</SectionTitle>
          <ChampionshipPicker />
          {/* L'esportazione prepara il foglio dell'asta, con una tendina per
              assegnare ogni giocatore a una squadra: fuori da una lega non ci
              sono squadre a cui assegnarlo. */}
          {browsing ? null : (
            <Button
              size="sm"
              variant="secondary"
              className="ml-auto"
              disabled={exporting || !data.players.length}
              onClick={() => void exportXlsx()}
            >
              {exporting ? 'Preparo…' : '⬇ Scarica listone (xlsx)'}
            </Button>
          )}
        </div>
        {/* Le due etichette dicevano la formula («media voto puro 2025-2026 →
            forma corrente», «r=0.38»): giusto per noi, illeggibile per chi
            gioca. Fuori resta la frase, il dettaglio esatto — stagioni, qualità
            della stima — sta nel titolo, per chi si ferma sopra. */}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Badge
            tone="blue"
            title={
              data.value_season
                ? `Media dei nostri voti in ${data.value_season}, che lascia sempre più spazio a quelli di ${data.current_season} man mano che il campionato va avanti.`
                : data.current_season
                  ? `Media dei nostri voti in ${data.current_season}.`
                  : undefined
            }
          >
            {data.value_season
              ? 'Valore = i nostri voti, dall’anno scorso alla forma di oggi'
              : 'Valore = la media dei nostri voti di quest’anno'}
          </Badge>
          {data.value_fit ? (
            <Badge
              tone="slate"
              title={`Chi non ha ancora giocato una partita con voto prende un valore dedotto dal prezzo di mercato, con una regola ricavata dai ${data.value_fit.n} giocatori che hanno tutti e due i dati. È un'indicazione di massima: il legame tra prezzo e rendimento è debole (r=${data.value_fit.r.toFixed(2)}).`}
            >
              ~ = valore stimato, il giocatore non ha ancora voti
            </Badge>
          ) : null}
        </div>
        <div className="mt-1 text-sm text-ink-soft">
          {shown.length} di {data.count} giocatori
        </div>
        <div className="mt-1 text-[11px] text-ink-faint">
          Il <b>Valore</b> è il voto che diamo noi in pagella, senza bonus e malus: è il{' '}
          <b>voto puro</b>, non il fantavoto. La colonna <b>Mercato</b> dice quanto vale il
          cartellino nel calcio vero (fonte Transfermarkt): serve solo a farsi un'idea.
        </div>

        {/* filters */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="flex gap-1">
            {(['ALL', ...ROLES] as const).map((r) => (
              <button
                key={r}
                onClick={() => setRole(r)}
                className={
                  r === role
                    ? 'rounded-lg bg-ink px-2.5 py-1 text-xs font-semibold text-paper'
                    : 'rounded-lg bg-surface-2 px-2.5 py-1 text-xs font-semibold text-ink-soft hover:bg-surface-2'
                }
              >
                {r === 'ALL' ? 'Tutti' : r}
              </button>
            ))}
          </div>
          {browsing ? null : (
            <label className="flex items-center gap-1.5 rounded-lg bg-surface-2 px-2.5 py-1 text-xs font-semibold text-ink-soft">
              <input type="checkbox" checked={freeOnly} onChange={(e) => setFreeOnly(e.target.checked)} />
              Solo svincolati
            </label>
          )}
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Cerca giocatore o squadra…"
            className="min-w-[10rem] flex-1 rounded-lg border border-line px-2.5 py-1 text-sm"
          />
          {/* «Solo con voto reale» chiedeva di sapere che esiste anche un voto
              finto. La casella fa una cosa sola: toglie dalla lista chi ha il
              valore stimato, cioè le righe con la tilde. */}
          <label
            title="Nasconde chi ha il valore stimato (~), cioè chi non ha ancora una partita con voto."
            className="flex items-center gap-1.5 rounded-lg bg-surface-2 px-2.5 py-1 text-xs font-semibold text-ink-soft"
          >
            <input type="checkbox" checked={ratedOnly} onChange={(e) => setRatedOnly(e.target.checked)} />
            Solo chi ha già giocato
          </label>
        </div>
      </Card>

      <Card className="p-2 sm:p-4">
        <div className="overflow-x-auto" ref={setScrollEl}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-ink-faint">
                <Th k="name" label="Giocatore" sort={sort} desc={desc} onSort={toggleSort} />
                <Th k="team" label="Squadra" sort={sort} desc={desc} onSort={toggleSort} />
                <Th k="value" label="Valore" sort={sort} desc={desc} onSort={toggleSort} right />
                <Th k="appearances" label="Pres." sort={sort} desc={desc} onSort={toggleSort} right />
                <Th k="market" label="Mercato" sort={sort} desc={desc} onSort={toggleSort} right />
                {/* Svincolato / di chi / ruolo da decidere: tutte e tre sono
                    domande che esistono solo dentro una lega. */}
                {browsing ? null : <th className="px-2 py-1.5">Stato</th>}
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => (
                <PlayerRow
                  key={p.player_id}
                  p={p}
                  open={openId === p.player_id}
                  onToggle={() => setOpenId(openId === p.player_id ? null : p.player_id)}
                  seasons={{ current: data.current_season, previous: data.value_season }}
                  visibleWidth={visibleWidth}
                  showStatus={!browsing}
                  onQuestionRole={canQuestionRoles ? questionRole : null}
                />
              ))}
            </tbody>
          </table>
          {!shown.length ? (
            <div className="px-2 py-6 text-center text-sm text-ink-faint">Nessun giocatore con questi filtri.</div>
          ) : null}
        </div>
      </Card>
    </div>
  );
}

function Th({
  k,
  label,
  sort,
  desc,
  onSort,
  right = false,
}: {
  k: SortKey;
  label: string;
  sort: SortKey;
  desc: boolean;
  onSort: (k: SortKey) => void;
  right?: boolean;
}) {
  const active = k === sort;
  return (
    <th className={`px-2 py-1.5 ${right ? 'text-right' : ''}`}>
      <button
        onClick={() => onSort(k)}
        className={`inline-flex items-center gap-0.5 uppercase tracking-wide hover:text-ink-soft ${
          active ? 'font-bold text-ink-soft' : ''
        }`}
        title={`Ordina per ${label}`}
      >
        {label}
        <span className="text-[9px]">{active ? (desc ? '▼' : '▲') : '⇅'}</span>
      </button>
    </th>
  );
}

function fmtMarket(v: number | null | undefined): string {
  if (typeof v !== 'number') return '—';
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(v >= 10_000_000 ? 0 : 1)}M`;
  if (v >= 1_000) return `${Math.round(v / 1_000)}k`;
  return String(v);
}

function PlayerRow({
  p,
  open,
  onToggle,
  seasons,
  visibleWidth,
  showStatus,
  onQuestionRole,
}: {
  p: ChampionshipPlayer;
  open: boolean;
  onToggle: () => void;
  seasons: { current: string; previous: string | null };
  visibleWidth: number | null;
  showStatus: boolean;
  onQuestionRole: ((playerId: number) => Promise<void>) | null;
}) {
  return (
    <>
    <tr className="border-t border-line">
      <td className="px-2 py-1.5">
        {/* The name opens the detail too. Only the value column did, which is not
            where anyone clicks to ask "who is this". */}
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          title="Chi è, e come è stato ottenuto il suo valore"
          className="inline-flex items-center gap-1.5 text-left"
        >
          {p.role ? (
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ${ROLE_CHIP[p.role] ?? 'bg-ink-faint'}`}>
              {p.role}
            </span>
          ) : null}
          <span className="font-medium text-ink underline decoration-ink-faint decoration-dotted underline-offset-2 hover:decoration-ink">
            {p.name}
          </span>
        </button>
      </td>
      <td className="px-2 py-1.5 text-ink-soft">{p.team ?? '—'}</td>
      <td className="px-2 py-1.5 text-right">
        <button
          onClick={onToggle}
          title="Come è stato ottenuto questo valore"
          className={`font-mono underline decoration-dotted underline-offset-2 hover:text-ink ${
            p.value_basis === 'stimato' ? 'italic text-ink-faint' : 'font-semibold text-ink'
          }`}
        >
          {p.value_basis === 'stimato' ? '~' : ''}
          {typeof p.estimated_value === 'number'
            ? p.estimated_value.toFixed(2)
            : typeof p.value === 'number'
              ? p.value.toFixed(2)
              : '—'}
        </button>
      </td>
      <td className="px-2 py-1.5 text-right text-ink-faint">{p.appearances || '—'}</td>
      <td className="px-2 py-1.5 text-right font-mono text-ink-soft">{fmtMarket(p.market_value)}</td>
      {showStatus ? (
        <td className="px-2 py-1.5">
          {p.owned ? (
            <span className="text-xs text-ink-faint">
              di <span className="font-medium text-ink-soft">{p.owner}</span>
            </span>
          ) : p.role_undecided ? (
            /* Shown rather than hidden: planning an auction around someone you
               cannot actually buy is worse than seeing why he is unavailable. */
            <span
              title="Non è ancora deciso in che ruolo schierarlo: lo stabilisce l'amministratore della lega, e fino ad allora non si può comprare."
              className="rounded border border-dashed border-warn px-1.5 py-0.5 text-[10px] font-semibold text-warn"
            >
              Ruolo da decidere
            </span>
          ) : (
            <span className="rounded bg-good-bg px-1.5 py-0.5 text-[10px] font-semibold text-good">Svincolato</span>
          )}
        </td>
      ) : null}
    </tr>
    {open ? (
      <ValueDetail
        p={p}
        seasons={seasons}
        visibleWidth={visibleWidth}
        colSpan={showStatus ? 6 : 5}
        onQuestionRole={onQuestionRole}
      />
    ) : null}
    </>
  );
}

// How this player's value was obtained — the breakdown behind the number.
function ValueDetail({
  p,
  seasons,
  visibleWidth,
  colSpan,
  onQuestionRole,
}: {
  p: ChampionshipPlayer;
  seasons: { current: string; previous: string | null };
  visibleWidth: number | null;
  colSpan: number;
  onQuestionRole: ((playerId: number) => Promise<void>) | null;
}) {
  const estimated = p.value_basis === 'stimato';
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  return (
    <tr className="bg-surface-2">
      {/* Il padding passa alla div interna: la cella resta larga quanto la tabella
          (non si può fare altrimenti, è una cella), ma il contenuto si ancora al
          bordo sinistro di ciò che si vede e prende quella larghezza. `sticky` e
          non `fixed` perché deve restare dentro il flusso della riga e seguire lo
          scorrimento verticale come tutto il resto. */}
      <td colSpan={6} className="p-0">
        <div
          className="sticky left-0 px-4 py-2 text-xs text-ink-soft"
          style={visibleWidth ? { width: visibleWidth } : undefined}
        >
        {/* Who the player IS, before why he is worth what he is worth: the list
            can only show an abbreviated name and a role chip, so opening a row
            was the one place left to say the rest. */}
        <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 border-b pb-2">
          <span className="text-sm font-bold text-ink">{p.full_name || p.name}</span>
          {p.role ? <Badge tone="slate">{ROLE_NAMES[p.role] ?? p.role}</Badge> : null}
          {p.team ? <span>Squadra reale: <b className="text-ink-soft">{p.team}</b></span> : null}
          <span>
            {p.owned ? (
              <>In rosa a <b className="text-ink-soft">{p.owner ?? '—'}</b></>
            ) : (
              <b className="text-good">Svincolato</b>
            )}
          </span>
          {p.market_value ? <span>Valore di mercato: <b className="text-ink-soft">{fmtMarket(p.market_value)}</b></span> : null}
          {p.role_undecided ? (
            <Badge tone="amber">Ruolo da decidere</Badge>
          ) : onQuestionRole && !p.owned ? (
            /* La coda automatica chiede solo dove il dubbio è NOSTRO, ed è una
               soglia stretta apposta. Questo è il modo per l'admin di dire che il
               dubbio è suo: stesso meccanismo, stessa consultazione. Non compare
               su chi è già in rosa — un ruolo pagato non torna una domanda, e il
               server rifiuterebbe comunque.
               Tinto del giallo della decisione che produce, e non di grigio: la
               prima versione aveva un tratteggio tenue in mezzo a etichette
               altrettanto tenui, e si leggeva come una scritta spenta invece che
               come l'unica cosa cliccabile della riga. */
            <Button
              size="sm"
              variant="secondary"
              disabled={asking}
              onClick={() => {
                setAsking(true);
                setAskError(null);
                onQuestionRole(p.player_id)
                  .catch((e) => setAskError(e instanceof Error ? e.message : String(e)))
                  .finally(() => setAsking(false));
              }}
              className="gap-1.5 border-warn/50 bg-warn-bg text-warn hover:brightness-95"
              title="Apre una domanda sul suo ruolo: finché non è decisa non è acquistabile, e puoi metterla ai voti."
            >
              {/* La stessa urna della notifica «nuovi ruoli da decidere»: l'azione
                  e la coda in cui finisce si riconoscono a colpo d'occhio. */}
              <span aria-hidden="true">🗳️</span>
              {asking ? 'Apro…' : 'Metti in discussione il ruolo'}
            </Button>
          ) : null}
        </div>
        {askError ? <div className="mb-2 text-xs text-bad">{askError}</div> : null}
        <div className="font-semibold text-ink-soft">
          {p.estimated_value === null
            ? 'Su questo giocatore non abbiamo dati'
            : estimated
              ? 'Valore stimato'
              : 'Valore calcolato sulle sue partite'}
        </div>
        {/* Qui si spiega da dove viene il numero, e va spiegato con le parole di
            chi gioca: «Base: misto» era il nome interno del calcolo, non una
            frase. La parola tecnica resta cercabile nella riga, non a schermo. */}
        <ul className="mt-1 space-y-0.5">
          {estimated ? (
            <li>
              Non ha ancora una partita con voto: il valore è dedotto dal prezzo del suo
              cartellino{p.market_value ? ` (${fmtMarket(p.market_value)})` : ''}, guardando
              quanto rendono di solito i giocatori che costano come lui. È un'indicazione di
              massima, non una nostra pagella.
            </li>
          ) : (
            <>
              <li>
                {p.value_basis === 'misto'
                  ? 'Parte dai voti dell’anno scorso, e più partite gioca quest’anno più contano quelli nuovi.'
                  : p.value_basis === 'precedente'
                    ? 'Calcolato sui voti dell’anno scorso: quest’anno non è ancora sceso in campo.'
                    : 'Conta solo quello che ha fatto quest’anno.'}
              </li>
              <li>
                Partite con voto: <b>{p.appearances}</b> in {seasons.current}
                {seasons.previous ? (
                  <>
                    {' '}· <b>{p.prev_appearances}</b> in {seasons.previous}
                  </>
                ) : null}
              </li>
              <li className="text-ink-faint">
                Chi ha giocato poche partite viene avvicinato al 6: così una sola grande
                prestazione non lo manda in cima alla lista.
              </li>
            </>
          )}
          </ul>
        </div>
      </td>
    </tr>
  );
}
