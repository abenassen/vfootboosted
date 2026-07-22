import { useEffect, useMemo, useState } from 'react';
import { getChampionshipPlayers } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Card, SectionTitle } from '../components/ui';
import type { ChampionshipPlayer, ChampionshipPlayersResponse } from '../types/realChampionship';

// Listone: the full player pool of the league's reference championship, with
// role / free-agent / search filters and value sorting. Value = average voto
// puro from the latest season with data.
type SortKey = 'name' | 'team' | 'value' | 'appearances' | 'market';

const ROLES = ['POR', 'DIF', 'CEN', 'ATT'] as const;
const ROLE_CHIP: Record<string, string> = {
  POR: 'bg-amber-500',
  DIF: 'bg-blue-500',
  CEN: 'bg-emerald-500',
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
    const q = search.trim().toLowerCase();
    if (q) ps = ps.filter((p) => p.name.toLowerCase().includes(q) || (p.team ?? '').toLowerCase().includes(q));

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

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega.</div>;
  if (loading) return <div className="text-sm text-slate-500">Caricamento listone…</div>;
  if (error) return <div className="text-sm text-red-600">Errore: {error}</div>;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <SectionTitle>Listone</SectionTitle>
          <Badge tone="blue">
            {data.value_season
              ? `valore = media voto ${data.value_season} → forma corrente`
              : data.current_season
                ? `valore = media voto ${data.current_season}`
                : 'valore = media voto'}
          </Badge>
          {data.value_fit ? (
            <Badge tone="slate">~ = stimato dal mercato (r={data.value_fit.r.toFixed(2)})</Badge>
          ) : null}
        </div>
        <div className="mt-1 text-sm text-slate-600">
          {shown.length} di {data.count} giocatori
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
                    ? 'rounded-lg bg-slate-900 px-2.5 py-1 text-xs font-semibold text-white'
                    : 'rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-200'
                }
              >
                {r === 'ALL' ? 'Tutti' : r}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">
            <input type="checkbox" checked={freeOnly} onChange={(e) => setFreeOnly(e.target.checked)} />
            Solo svincolati
          </label>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Cerca giocatore o squadra…"
            className="min-w-[10rem] flex-1 rounded-lg border border-slate-200 px-2.5 py-1 text-sm"
          />
          <label className="flex items-center gap-1.5 rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">
            <input type="checkbox" checked={ratedOnly} onChange={(e) => setRatedOnly(e.target.checked)} />
            Solo con voto reale
          </label>
        </div>
      </Card>

      <Card className="p-2 sm:p-4">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-slate-400">
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
            <div className="px-2 py-6 text-center text-sm text-slate-500">Nessun giocatore con questi filtri.</div>
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
        className={`inline-flex items-center gap-0.5 uppercase tracking-wide hover:text-slate-700 ${
          active ? 'font-bold text-slate-700' : ''
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
    <tr className="border-t border-slate-100">
      <td className="px-2 py-1.5">
        <span className="inline-flex items-center gap-1.5">
          {p.role ? (
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ${ROLE_CHIP[p.role] ?? 'bg-slate-400'}`}>
              {p.role}
            </span>
          ) : null}
          <span className="font-medium text-slate-800">{p.name}</span>
        </span>
      </td>
      <td className="px-2 py-1.5 text-slate-600">{p.team ?? '—'}</td>
      <td className="px-2 py-1.5 text-right">
        <button
          onClick={onToggle}
          title="Come è stato ottenuto questo valore"
          className={`font-mono underline decoration-dotted underline-offset-2 hover:text-slate-900 ${
            p.value_basis === 'stimato' ? 'italic text-slate-500' : 'font-semibold text-slate-800'
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
      <td className="px-2 py-1.5 text-right text-slate-400">{p.appearances || '—'}</td>
      <td className="px-2 py-1.5 text-right font-mono text-slate-600">{fmtMarket(p.market_value)}</td>
      <td className="px-2 py-1.5">
        {p.owned ? (
          <span className="text-xs text-slate-500">
            di <span className="font-medium text-slate-700">{p.owner}</span>
          </span>
        ) : p.role_undecided ? (
          /* Shown rather than hidden: planning an auction around someone you
             cannot actually buy is worse than seeing why he is unavailable. */
          <span
            title="Il suo ruolo attende una decisione dell'amministratore: non è acquistabile finché non viene presa."
            className="rounded border border-dashed border-amber-400 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700"
          >
            Ruolo da decidere
          </span>
        ) : (
          <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">Svincolato</span>
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
    <tr className="bg-slate-50">
      <td colSpan={6} className="px-4 py-2 text-xs text-slate-600">
        <div className="font-semibold text-slate-700">
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
              <li className="text-slate-500">
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
