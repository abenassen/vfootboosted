import { useEffect, useMemo, useState } from 'react';
import { getChampionshipPlayers, getLeagueDetail } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { foldedMatch } from '../utils/text';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type { ChampionshipPlayer, ChampionshipPlayersResponse } from '../types/realChampionship';

// Listone: the full player pool of the league's reference championship, with
// role / free-agent / search filters and value sorting. Value = average voto
// puro from the latest season with data.
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

  useEffect(() => {
    if (!selectedLeagueId) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    void getChampionshipPlayers(selectedLeagueId)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [selectedLeagueId]);

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

  if (!selectedLeagueId) return <div className="text-sm text-ink-faint">Seleziona una lega.</div>;
  if (loading) return <div className="text-sm text-ink-faint">Caricamento listone…</div>;
  if (error) return <div className="text-sm text-bad">Errore: {error}</div>;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <SectionTitle>Listone</SectionTitle>
          <Button
            size="sm"
            variant="secondary"
            className="ml-auto"
            disabled={exporting || !data.players.length}
            onClick={() => void exportXlsx()}
          >
            {exporting ? 'Preparo…' : '⬇ Scarica listone (xlsx)'}
          </Button>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Badge tone="blue">
            {data.value_season
              ? `valore = media voto puro ${data.value_season} → forma corrente`
              : data.current_season
                ? `valore = media voto puro ${data.current_season}`
                : 'valore = media voto puro'}
          </Badge>
          {data.value_fit ? (
            <Badge tone="slate">~ = stimato dal mercato (r={data.value_fit.r.toFixed(2)})</Badge>
          ) : null}
        </div>
        <div className="mt-1 text-sm text-ink-soft">
          {shown.length} di {data.count} giocatori
        </div>
        <div className="mt-1 text-[11px] text-ink-faint">
          Il <b>Valore</b> è la media del <b>voto puro</b> (la nostra pagella), senza bonus/malus: non è
          il fantavoto. La colonna <b>Mercato</b> è il valore Transfermarkt, a solo titolo indicativo.
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
          <label className="flex items-center gap-1.5 rounded-lg bg-surface-2 px-2.5 py-1 text-xs font-semibold text-ink-soft">
            <input type="checkbox" checked={freeOnly} onChange={(e) => setFreeOnly(e.target.checked)} />
            Solo svincolati
          </label>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Cerca giocatore o squadra…"
            className="min-w-[10rem] flex-1 rounded-lg border border-line px-2.5 py-1 text-sm"
          />
          <label className="flex items-center gap-1.5 rounded-lg bg-surface-2 px-2.5 py-1 text-xs font-semibold text-ink-soft">
            <input type="checkbox" checked={ratedOnly} onChange={(e) => setRatedOnly(e.target.checked)} />
            Solo con voto reale
          </label>
        </div>
      </Card>

      <Card className="p-2 sm:p-4">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-ink-faint">
                <Th k="name" label="Giocatore" sort={sort} desc={desc} onSort={toggleSort} />
                <Th k="team" label="Squadra" sort={sort} desc={desc} onSort={toggleSort} />
                <Th k="value" label="Valore" sort={sort} desc={desc} onSort={toggleSort} right />
                <Th k="appearances" label="Pres." sort={sort} desc={desc} onSort={toggleSort} right />
                <Th k="market" label="Mercato" sort={sort} desc={desc} onSort={toggleSort} right />
                <th className="px-2 py-1.5">Stato</th>
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
}: {
  p: ChampionshipPlayer;
  open: boolean;
  onToggle: () => void;
  seasons: { current: string; previous: string | null };
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
      <td className="px-2 py-1.5">
        {p.owned ? (
          <span className="text-xs text-ink-faint">
            di <span className="font-medium text-ink-soft">{p.owner}</span>
          </span>
        ) : p.role_undecided ? (
          /* Shown rather than hidden: planning an auction around someone you
             cannot actually buy is worse than seeing why he is unavailable. */
          <span
            title="Il suo ruolo attende una decisione dell'amministratore: non è acquistabile finché non viene presa."
            className="rounded border border-dashed border-warn px-1.5 py-0.5 text-[10px] font-semibold text-warn"
          >
            Ruolo da decidere
          </span>
        ) : (
          <span className="rounded bg-good-bg px-1.5 py-0.5 text-[10px] font-semibold text-good">Svincolato</span>
        )}
      </td>
    </tr>
    {open ? <ValueDetail p={p} seasons={seasons} /> : null}
    </>
  );
}

// How this player's value was obtained — the breakdown behind the number.
function ValueDetail({
  p,
  seasons,
}: {
  p: ChampionshipPlayer;
  seasons: { current: string; previous: string | null };
}) {
  const estimated = p.value_basis === 'stimato';
  return (
    <tr className="bg-surface-2">
      <td colSpan={6} className="px-4 py-2 text-xs text-ink-soft">
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
          ) : null}
        </div>
        <div className="font-semibold text-ink-soft">
          {p.estimated_value === null
            ? 'Nessun dato disponibile'
            : estimated
              ? 'Valore stimato'
              : 'Valore calcolato dalle prestazioni'}
        </div>
        <ul className="mt-1 space-y-0.5">
          {estimated ? (
            <li>
              Nessuna presenza a voto: stimato dal valore di mercato
              {p.market_value ? ` (${fmtMarket(p.market_value)})` : ''}, tramite la relazione
              calibrata sui giocatori che hanno entrambi i dati.
            </li>
          ) : (
            <>
              <li>
                Base: <b>{p.value_basis}</b>
                {p.value_basis === 'misto'
                  ? ' — media della stagione precedente che lascia progressivamente spazio alla forma corrente'
                  : p.value_basis === 'precedente'
                    ? ' — la stagione corrente non ha ancora dati'
                    : ' — calcolato sulla stagione in corso'}
              </li>
              <li>
                Presenze a voto: <b>{p.appearances}</b> in {seasons.current}
                {seasons.previous ? (
                  <>
                    {' '}· <b>{p.prev_appearances}</b> in {seasons.previous}
                  </>
                ) : null}
              </li>
              <li className="text-ink-faint">
                Le medie basate su poche presenze sono avvicinate al 6, per evitare che una
                singola grande prestazione domini la classifica.
              </li>
            </>
          )}
        </ul>
      </td>
    </tr>
  );
}
