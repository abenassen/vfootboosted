import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import { getTeamLineup, saveTeamLineup } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import type {
  ClassicConstraints,
  PlayerRole,
  TeamLineupContext,
  TeamLineupPlayer,
} from '../types/lineup';

const XI = 11; // starters incl. exactly one goalkeeper

const ROLE_LABEL: Record<PlayerRole, string> = { GK: 'POR', DEF: 'DIF', MID: 'CEN', ATT: 'ATT' };
const ROLE_CHIP: Record<PlayerRole, string> = {
  GK: 'bg-amber-500',
  DEF: 'bg-blue-500',
  MID: 'bg-emerald-500',
  ATT: 'bg-orange-500',
};
const ROLE_ORDER: Record<PlayerRole, number> = { GK: 0, DEF: 1, MID: 2, ATT: 3 }; // P, D, C, A

// Mirror of vfoot/services/formation_rules.validate_classic_lineup — the server
// validates identically; this is the live UI guide. Returns Italian violations.
function validateClassic(roles: PlayerRole[], c: ClassicConstraints): string[] {
  const errs: string[] = [];
  if (roles.length !== c.starters) errs.push(`Servono esattamente ${c.starters} titolari (ne hai ${roles.length}).`);
  const cnt: Record<PlayerRole, number> = { GK: 0, DEF: 0, MID: 0, ATT: 0 };
  roles.forEach((r) => (cnt[r] += 1));
  if (cnt.GK !== 1) errs.push(cnt.GK === 0 ? 'Manca il portiere.' : 'Un solo portiere fra i titolari.');
  if (cnt.DEF < c.per_role.DEF.min) errs.push(`Almeno ${c.per_role.DEF.min} difensori (ne hai ${cnt.DEF}).`);
  if (cnt.ATT < c.per_role.ATT.min) errs.push(`Almeno ${c.per_role.ATT.min} attaccante (ne hai ${cnt.ATT}).`);
  if (cnt.ATT > c.per_role.ATT.max) errs.push(`Al massimo ${c.per_role.ATT.max} attaccanti (ne hai ${cnt.ATT}).`);
  (['DEF', 'MID'] as PlayerRole[]).forEach((role) => {
    if (cnt[role] > c.per_role[role].max)
      errs.push(`Meno di 6 ${ROLE_LABEL[role]} (${c.per_role[role].max} max, ne hai ${cnt[role]}).`);
  });
  return errs;
}

// Bench player_ids in priority order: honour `seed` first (saved/explicit order),
// then append any remaining non-starter roster player (role order P/D/C/A, best form
// first) so nobody is ever dropped from the payload.
function orderBench(roster: TeamLineupPlayer[], starterIds: number[], seed: number[]): number[] {
  const starterSet = new Set(starterIds);
  const cand = new Map(roster.filter((p) => !starterSet.has(p.player_id)).map((p) => [p.player_id, p]));
  const out: number[] = [];
  for (const id of seed) {
    if (cand.has(id) && !out.includes(id)) out.push(id);
  }
  const rest = [...cand.values()]
    .filter((p) => !out.includes(p.player_id))
    .sort((a, b) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role] || b.form - a.form);
  return [...out, ...rest.map((p) => p.player_id)];
}

// Kick-off of the real fixture; the provider ships a placeholder time until the
// slot is actually assigned, so we say so rather than showing a made-up hour.
function fmtKickoff(nm: { kickoff: string | null; kickoff_provisional: boolean }): string {
  if (!nm.kickoff || nm.kickoff_provisional) return 'orario da definire';
  return new Date(nm.kickoff).toLocaleString('it-IT', {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// "Inter - Monza": the real fixture in home-away order, so the player's own club is
// visible too, not just the opponent.
function fixtureLabel(nm: { team: string; opponent: string; home: boolean }): string {
  return nm.home ? `${nm.team} - ${nm.opponent}` : `${nm.opponent} - ${nm.team}`;
}

function PlayerDetails({ p }: { p: TeamLineupPlayer }) {
  const nm = p.next_match;
  return (
    <span className="mt-1 block rounded-lg bg-slate-50 px-2 py-1 text-[11px] text-slate-600">
      {nm ? (
        <span className="block">
          {nm.home ? (
            <>
              <b className="text-slate-800">{nm.team}</b> - {nm.opponent}
            </>
          ) : (
            <>
              {nm.opponent} - <b className="text-slate-800">{nm.team}</b>
            </>
          )}
          <span className="text-slate-400"> · {fmtKickoff(nm)}</span>
        </span>
      ) : null}
      {p.minutes_label === 'unknown' ? (
        <span className="block text-slate-400">nessuno storico di impiego</span>
      ) : (
        <span className="block">
          {p.appearances} pres · {p.avg_minutes}′ medi
          {p.minutes_label === 'low' ? <Badge tone="amber"> poco impiegato</Badge> : null}
          {p.minutes_label === 'high' ? <Badge tone="green"> titolare abituale</Badge> : null}
        </span>
      )}
      {p.stats_season ? <span className="block text-slate-400">dati: {p.stats_season}</span> : null}
    </span>
  );
}

export default function FormationPage() {
  const { selectedLeagueId } = useLeagueContext();
  const [searchParams, setSearchParams] = useSearchParams();
  const competition = searchParams.get('competition') ? Number(searchParams.get('competition')) : null;
  const matchday = searchParams.get('matchday') ? Number(searchParams.get('matchday')) : null;

  const [ctx, setCtx] = useState<TeamLineupContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [starterIds, setStarterIds] = useState<number[]>([]);
  // Explicit, ordered bench = substitution priority. Always stored (even in Aura,
  // where the substitute is the best available and order only breaks ties).
  const [benchOrder, setBenchOrder] = useState<number[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [allComps, setAllComps] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const setParams = (next: { competition?: number; matchday?: number }) => {
    const p = new URLSearchParams(searchParams);
    if (next.competition != null) p.set('competition', String(next.competition));
    if (next.matchday != null) p.set('matchday', String(next.matchday));
    setSearchParams(p, { replace: true });
  };

  // Suggestion / default: a balanced 4-4-2 by inferred role, each slot the best
  // available by recent form (falls back across roles if a line is short).
  const suggest = (roster: TeamLineupPlayer[]): number[] => {
    const byForm = (a: TeamLineupPlayer, b: TeamLineupPlayer) => b.form - a.form;
    const gk = [...roster].filter((p) => p.role === 'GK').sort(byForm)[0];
    const chosen = new Set<number>();
    if (gk) chosen.add(gk.player_id);
    const targets: [PlayerRole, number][] = [['DEF', 4], ['MID', 4], ['ATT', 2]];
    const out: number[] = [];
    for (const [role, n] of targets) {
      roster
        .filter((p) => p.role === role && !chosen.has(p.player_id))
        .sort(byForm)
        .slice(0, n)
        .forEach((p) => {
          chosen.add(p.player_id);
          out.push(p.player_id);
        });
    }
    // top up to 10 outfielders from whoever is left, by form
    roster
      .filter((p) => p.role !== 'GK' && !chosen.has(p.player_id))
      .sort(byForm)
      .forEach((p) => {
        if (out.length < XI - 1) {
          chosen.add(p.player_id);
          out.push(p.player_id);
        }
      });
    return gk ? [gk.player_id, ...out] : out;
  };

  useEffect(() => {
    if (!selectedLeagueId) return;
    setLoading(true);
    setError(null);
    void getTeamLineup(selectedLeagueId, matchday, competition)
      .then((d) => {
        setCtx(d);
        // First visit: pick the competition + a mid-season matchday, which
        // re-fetches as-of (no-leakage) profiles for that competition.
        if (competition == null || matchday == null) {
          setParams({
            competition: competition ?? d.competition ?? undefined,
            matchday: matchday ?? d.matchdays[Math.floor(d.matchdays.length / 2)] ?? d.matchday,
          });
          return;
        }
        const saved = d.saved_lineup;
        let starters: number[];
        if (saved && (saved.gk_player_id || saved.starter_player_ids.length)) {
          starters = [...(saved.gk_player_id ? [saved.gk_player_id] : []), ...saved.starter_player_ids].slice(0, XI);
        } else {
          starters = suggest(d.roster);
        }
        setStarterIds(starters);
        setBenchOrder(orderBench(d.roster, starters, saved?.bench_player_ids ?? []));
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [selectedLeagueId, competition, matchday]);

  const byId = useMemo(() => new Map((ctx?.roster ?? []).map((p) => [p.player_id, p])), [ctx]);
  const gkStarters = useMemo(
    () => starterIds.filter((id) => byId.get(id)?.role === 'GK'),
    [starterIds, byId],
  );
  const gkId = gkStarters[0] ?? null;

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega per impostare la formazione.</div>;
  if (loading && !ctx) return <div className="text-sm text-slate-500">Caricamento formazione…</div>;
  if (error || !ctx) return <div className="text-sm text-red-600">Errore: {error ?? '…'}</div>;

  const isClassic = ctx.mode === 'classic';
  const constraints = ctx.rules.classic_constraints;

  // Toggling a player keeps the ordered bench in sync: a demoted starter joins the
  // bench at the LOWEST priority (end); a promoted bench player leaves it.
  const toggleStarter = (id: number) => {
    if (starterIds.includes(id)) {
      setStarterIds((s) => s.filter((x) => x !== id));
      setBenchOrder((b) => (b.includes(id) ? b : [...b, id]));
    } else {
      if (starterIds.length >= XI) return;
      setStarterIds((s) => [...s, id]);
      setBenchOrder((b) => b.filter((x) => x !== id));
    }
  };

  const moveBench = (id: number, dir: -1 | 1) => {
    setBenchOrder((b) => {
      const i = b.indexOf(id);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= b.length) return b;
      const next = [...b];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };

  const starterRoles = starterIds.map((id) => byId.get(id)?.role).filter((r): r is PlayerRole => !!r);
  const classicErrors = isClassic && constraints ? validateClassic(starterRoles, constraints) : [];
  const gkOk = gkStarters.length === 1;
  const canSave = starterIds.length === XI && gkOk && classicErrors.length === 0;

  const onSave = async () => {
    if (!canSave || !selectedLeagueId || matchday == null) return;
    setSaving(true);
    try {
      // Send the bench in PRIORITY order (substitution order); append any roster
      // player not yet placed so nobody is dropped from the payload.
      const benchIds = orderBench(ctx.roster, starterIds, benchOrder);
      const res = await saveTeamLineup(selectedLeagueId, {
        matchday,
        competition: allComps ? null : competition,
        all_competitions: allComps,
        gk_player_id: gkId,
        starter_player_ids: starterIds.filter((id) => id !== gkId),
        bench_player_ids: benchIds,
      });
      setToast(allComps ? `Formazione salvata su ${res.saved_competitions} competizioni ✓` : 'Formazione salvata ✓');
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Errore nel salvataggio');
    } finally {
      setSaving(false);
      setTimeout(() => setToast(null), 2800);
    }
  };

  const byRole = (a: TeamLineupPlayer, b: TeamLineupPlayer) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role] || b.form - a.form;
  const starters = ctx.roster.filter((p) => starterIds.includes(p.player_id)).sort(byRole);
  const benchIds = orderBench(ctx.roster, starterIds, benchOrder);
  const bench = benchIds.map((id) => byId.get(id)).filter((p): p is TeamLineupPlayer => !!p);
  const compName = ctx.competitions.find((c) => c.competition_id === competition)?.name;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <SectionTitle>Formazione · {ctx.team.name}</SectionTitle>
              <Badge tone={isClassic ? 'blue' : 'green'}>{isClassic ? 'Classic' : 'Aura'}</Badge>
            </div>
            <div className="mt-1 text-sm text-slate-600">
              {compName ? <>Competizione <b>{compName}</b> · </> : null}
              titolari {starterIds.length}/{XI}
              {!isClassic && gkStarters.length !== 1 ? (
                <span className="ml-2 font-semibold text-rose-600">
                  {gkStarters.length === 0 ? '· manca il portiere' : '· un solo portiere consentito'}
                </span>
              ) : null}
            </div>
            {isClassic ? (
              <div className="mt-1 text-[11px] text-slate-500">
                Vincoli: 1 portiere · almeno 3 difensori · 1–3 attaccanti · meno di 6 per reparto · 11 totali.
              </div>
            ) : null}
            {isClassic && classicErrors.length ? (
              <ul className="mt-1 list-disc pl-4 text-[11px] font-semibold text-rose-600">
                {classicErrors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            ) : null}
            {ctx.as_of_matchday != null ? (
              <div className="mt-1 text-[11px] text-amber-600">
                Giornata {ctx.as_of_matchday} · dati aggiornati alla giornata {ctx.as_of_matchday - 1} (
                {ctx.prior_matches} partite) — nessuna informazione futura.
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {ctx.competitions.length > 1 ? (
              <select
                value={competition ?? ''}
                onChange={(e) => setParams({ competition: Number(e.target.value) })}
                className="rounded-lg border border-slate-200 px-2 py-1 text-sm"
              >
                {ctx.competitions.map((c) => (
                  <option key={c.competition_id} value={c.competition_id}>
                    {c.name}
                  </option>
                ))}
              </select>
            ) : null}
            <label className="text-xs text-slate-500">Giornata</label>
            <select
              value={matchday ?? ''}
              onChange={(e) => setParams({ matchday: Number(e.target.value) })}
              className="rounded-lg border border-slate-200 px-2 py-1 text-sm"
            >
              {ctx.matchdays.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <Button variant="secondary" onClick={() => setStarterIds(suggest(ctx.roster))}>
              Suggerisci XI
            </Button>
            <Button onClick={onSave} disabled={!canSave || saving}>
              {saving ? 'Salvataggio…' : 'Salva'}
            </Button>
          </div>
        </div>
        <label className="mt-2 flex items-center gap-2 text-xs text-slate-600">
          <input type="checkbox" checked={allComps} onChange={(e) => setAllComps(e.target.checked)} />
          Invia questa formazione a tutte le competizioni della lega (stessa giornata)
        </label>
        {toast ? <div className="mt-2 text-sm font-semibold text-green-700">{toast}</div> : null}
      </Card>

      <div className="grid items-start gap-4 lg:grid-cols-[1fr_360px]">
        <Card className="self-start p-4 lg:sticky lg:top-4">
          <SectionTitle>La squadra in campo</SectionTitle>
          <div className="mt-1 text-[11px] text-slate-400">
            {isClassic ? 'Schieramento per ruolo.' : 'Posizione attesa di ogni titolare (dai dati storici).'} Il portiere ha il bordo ambra. Clicca un giocatore per
            vederne le zone d'influenza (in giallo).
          </div>
          <PitchLineup
            starterIds={starterIds}
            byId={byId}
            gkId={gkId}
            selectedId={selected}
            onSelect={(id) => setSelected((s) => (s === id ? null : id))}
            regular={isClassic}
          />
        </Card>

        <Card className="p-4">
          <SectionTitle>Rosa · titolari e panchina (un solo portiere fra i titolari)</SectionTitle>
          <div className="mt-1 text-[11px] text-slate-400">Clicca il nome per vederne le zone sulla mappa.</div>

          <div className="mt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Titolari {starterIds.length}/{XI}
          </div>
          <div className="divide-y">
            {starters.map((p) => (
              <RosterRow
                key={p.player_id}
                p={p}
                isStarter
                selected={selected === p.player_id}
                onSelect={() => setSelected((s) => (s === p.player_id ? null : p.player_id))}
                onToggle={() => toggleStarter(p.player_id)}
              />
            ))}
            {starters.length === 0 ? <div className="py-2 text-sm text-slate-400">Nessun titolare selezionato.</div> : null}
          </div>

          <div className="mt-4 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Panchina · ordine = priorità sostituzioni
          </div>
          <div className="mt-0.5 text-[11px] text-slate-400">
            {isClassic
              ? 'Entra il primo panchinaro in lista che ha un voto e mantiene la formazione valida.'
              : 'In Aura il sostituto è il migliore disponibile; l’ordine conta solo a parità.'}
          </div>
          <div className="divide-y">
            {bench.map((p, i) => (
              <RosterRow
                key={p.player_id}
                p={p}
                isStarter={false}
                selected={selected === p.player_id}
                onSelect={() => setSelected((s) => (s === p.player_id ? null : p.player_id))}
                onToggle={() => toggleStarter(p.player_id)}
                order={i + 1}
                canUp={i > 0}
                canDown={i < bench.length - 1}
                onMoveUp={() => moveBench(p.player_id, -1)}
                onMoveDown={() => moveBench(p.player_id, 1)}
              />
            ))}
            {bench.length === 0 ? <div className="py-2 text-sm text-slate-400">Panchina vuota.</div> : null}
          </div>
        </Card>
      </div>
    </div>
  );
}

function RosterRow({
  p,
  isStarter,
  selected,
  onSelect,
  onToggle,
  order,
  canUp,
  canDown,
  onMoveUp,
  onMoveDown,
}: {
  p: TeamLineupPlayer;
  isStarter: boolean;
  selected: boolean;
  onSelect: () => void;
  onToggle: () => void;
  order?: number;
  canUp?: boolean;
  canDown?: boolean;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
}) {
  return (
    <div className={`flex items-center justify-between gap-2 py-2 ${selected ? 'bg-slate-50' : ''}`}>
      <button onClick={onSelect} className="flex min-w-0 items-center gap-2 text-left">
        {order != null ? (
          <span className="w-4 shrink-0 text-right text-[11px] font-semibold tabular-nums text-slate-400">{order}</span>
        ) : null}
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ${ROLE_CHIP[p.role]}`}>
          {ROLE_LABEL[p.role]}
        </span>
        <span className="min-w-0">
          <span className={`block truncate text-sm font-semibold ${selected ? 'text-slate-900 underline' : 'text-slate-800'}`}>
            {p.name}
          </span>
          <span className="block text-[11px] text-slate-500">
            {typeof p.value === 'number' ? (
              <>
                media voto <b className="text-slate-700">{p.value.toFixed(2)}</b>
                {p.value_basis === 'stimato' ? <span className="text-slate-400"> (stimata)</span> : null}
              </>
            ) : (
              <span className="text-slate-400">nessuno storico</span>
            )}
            {p.next_match ? <span className="text-slate-400"> · {fixtureLabel(p.next_match)}</span> : null}
          </span>
          {selected ? <PlayerDetails p={p} /> : null}
        </span>
      </button>
      <div className="flex shrink-0 items-center gap-1">
        {order != null ? (
          <div className="flex flex-col overflow-hidden rounded border border-slate-200 text-slate-500">
            <button
              onClick={onMoveUp}
              disabled={!canUp}
              className="px-1.5 text-[9px] leading-tight hover:bg-slate-100 disabled:opacity-30"
              title="Alza priorità"
            >
              ▲
            </button>
            <button
              onClick={onMoveDown}
              disabled={!canDown}
              className="px-1.5 text-[9px] leading-tight hover:bg-slate-100 disabled:opacity-30"
              title="Abbassa priorità"
            >
              ▼
            </button>
          </div>
        ) : null}
        <div className="flex overflow-hidden rounded-lg border border-slate-200 text-[11px] font-semibold">
          <button
            onClick={onToggle}
            className={isStarter ? 'bg-slate-900 px-3 py-1 text-white' : 'bg-white px-3 py-1 text-slate-600 hover:bg-slate-100'}
          >
            Titolare
          </button>
          <button
            onClick={onToggle}
            className={!isStarter ? 'bg-slate-500 px-3 py-1 text-white' : 'bg-white px-3 py-1 text-slate-600 hover:bg-slate-100'}
          >
            Panca
          </button>
        </div>
      </div>
    </div>
  );
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// Expected position of a player = footprint centroid in (col,row) space.
function expectedPos(footprint: Record<string, number>): { col: number; row: number } {
  let scol = 0;
  let srow = 0;
  let tot = 0;
  for (const [z, s] of Object.entries(footprint)) {
    const m = /^Z_(\d+)_(\d+)$/.exec(z);
    if (m) {
      scol += Number(m[1]) * s;
      srow += Number(m[2]) * s;
      tot += s;
    }
  }
  return tot > 0 ? { col: scol / tot, row: srow / tot } : { col: 2, row: 1.5 };
}

const DOT_COLOR: Record<PlayerRole, string> = {
  GK: 'bg-amber-400',
  DEF: 'bg-blue-500',
  MID: 'bg-emerald-500',
  ATT: 'bg-orange-500',
};

// The XI placed on a pitch at each player's expected position. Defence on the
// left, attack on the right; goalkeeper ringed in amber.
function PitchLineup({
  starterIds,
  byId,
  gkId,
  selectedId,
  onSelect,
  regular = false,
}: {
  starterIds: number[];
  byId: Map<number, TeamLineupPlayer>;
  gkId: number | null;
  selectedId: number | null;
  onSelect: (id: number) => void;
  regular?: boolean;
}) {
  // Lay the XI out as formation lines: depth (x) from each player's expected
  // column, width (y) spread within their role line so dots never pile up
  // (footprint centroids alone bunch everyone in the middle).
  // Base position from the player's REFERENCE zone: depth (x) by role band +
  // expected column, lateral (y) by the expected row (so wide players stay wide,
  // central players stay central — attackers are no longer flung to the flanks).
  const ROLE_X: Record<PlayerRole, number> = { GK: 8, DEF: 30, MID: 53, ATT: 76 };
  const TYPICAL_COL: Record<PlayerRole, number> = { GK: 0, DEF: 1, MID: 2, ATT: 3 };
  // CLASSIC: only the coarse role matters, so lay the XI out as a tidy formation —
  // one line per role, players spread evenly across it. The real spatial position is
  // an aura concern and only adds noise here.
  if (regular) {
    const lines: PlayerRole[] = ['GK', 'DEF', 'MID', 'ATT'];
    const byRole = new Map<PlayerRole, TeamLineupPlayer[]>(lines.map((r) => [r, []]));
    starterIds
      .map((id) => byId.get(id))
      .filter((p): p is TeamLineupPlayer => !!p)
      .forEach((p) => byRole.get(p.role)?.push(p));
    const regularDots = lines.flatMap((role) => {
      const group = byRole.get(role) ?? [];
      return group.map((p, i) => ({
        p,
        left: ROLE_X[role],
        top: 50 + (i - (group.length - 1) / 2) * Math.min(26, 76 / Math.max(group.length, 1)),
        isGk: p.player_id === gkId,
      }));
    });
    const selRegular = selectedId != null ? byId.get(selectedId) : null;
    return (
      <PitchCanvas
        dots={regularDots}
        selectedId={selectedId}
        onSelect={onSelect}
        footprint={selRegular?.footprint ?? null}
      />
    );
  }

  const dots = starterIds
    .map((id) => byId.get(id))
    .filter((p): p is TeamLineupPlayer => !!p)
    .map((p) => {
      const { col, row } = expectedPos(p.footprint);
      const nudge = Math.max(-8, Math.min(9, (col - TYPICAL_COL[p.role]) * 6));
      return {
        p,
        left: Math.max(6, Math.min(94, ROLE_X[p.role] + nudge)),
        top: Math.max(12, Math.min(88, 12 + (row / 3) * 76)),
        isGk: p.player_id === gkId,
      };
    });
  // Aesthetic de-overlap: gently push apart dots that are too close, keeping each
  // near its real zone. The user still decides the balance of the lineup.
  const MIN = 14;
  for (let iter = 0; iter < 60; iter++) {
    for (let i = 0; i < dots.length; i++) {
      for (let j = i + 1; j < dots.length; j++) {
        let dx = dots[i].left - dots[j].left;
        let dy = dots[i].top - dots[j].top;
        let d = Math.hypot(dx, dy);
        if (d < MIN) {
          if (d < 0.001) {
            dx = 0;
            dy = i % 2 === 0 ? 1 : -1;
            d = 1;
          }
          const push = (MIN - d) / 2;
          const ux = dx / d;
          const uy = dy / d;
          dots[i].left = Math.max(6, Math.min(94, dots[i].left + ux * push));
          dots[i].top = Math.max(12, Math.min(88, dots[i].top + uy * push));
          dots[j].left = Math.max(6, Math.min(94, dots[j].left - ux * push));
          dots[j].top = Math.max(12, Math.min(88, dots[j].top - uy * push));
        }
      }
    }
  }

  const sel = selectedId != null ? byId.get(selectedId) : null;
  return (
    <PitchCanvas
      dots={dots}
      selectedId={selectedId}
      onSelect={onSelect}
      footprint={sel?.footprint ?? null}
    />
  );
}

// The pitch itself: markings, the selected player's influence zones, and the dots.
// Shared by the spatial (aura) and the regular-formation (classic) layouts.
function PitchCanvas({
  dots,
  selectedId,
  onSelect,
  footprint,
}: {
  dots: { p: TeamLineupPlayer; left: number; top: number; isGk: boolean }[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  footprint: Record<string, number> | null;
}) {
  const selMax = footprint ? Math.max(0.0001, ...Object.values(footprint)) : 1;
  return (
    <div className="relative mt-3 aspect-[7/5] w-full overflow-hidden rounded-xl border border-green-700/40 bg-gradient-to-r from-green-600 to-green-500 shadow-inner">
      {/* pitch markings */}
      <div className="pointer-events-none absolute inset-2 rounded border border-white/40" />
      <div className="pointer-events-none absolute inset-y-2 left-1/2 w-px -translate-x-1/2 bg-white/40" />
      <div className="pointer-events-none absolute left-1/2 top-1/2 h-16 w-16 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/40" />
      <div className="pointer-events-none absolute left-2 top-1/2 h-24 w-12 -translate-y-1/2 border border-white/40" />
      <div className="pointer-events-none absolute right-2 top-1/2 h-24 w-12 -translate-y-1/2 border border-white/40" />
      {/* predicted influence zones of the selected player */}
      {footprint
        ? Object.entries(footprint).map(([z, share]) => {
            const m = /^Z_(\d+)_(\d+)$/.exec(z);
            if (!m) return null;
            const c = Number(m[1]);
            const r = Number(m[2]);
            const intensity = share / selMax;
            return (
              <div
                key={z}
                className="pointer-events-none absolute border border-yellow-100/30"
                style={{
                  left: `${(c / 5) * 100}%`,
                  top: `${(r / 4) * 100}%`,
                  width: '20%',
                  height: '25%',
                  // high-contrast yellow on the green pitch (role colours like the
                  // midfielders' green would vanish into the turf)
                  backgroundColor: `rgba(250,204,21,${(0.25 + 0.6 * intensity).toFixed(3)})`,
                }}
              />
            );
          })
        : null}
      {dots.map(({ p, left, top, isGk }) => (
        <button
          key={p.player_id}
          onClick={() => onSelect(p.player_id)}
          className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center"
          style={{ left: `${left}%`, top: `${top}%` }}
          title={p.name}
        >
          <span
            className={`flex h-7 w-7 items-center justify-center rounded-full text-[9px] font-bold text-white shadow-md ${DOT_COLOR[p.role]} ${
              isGk ? 'ring-2 ring-amber-200' : ''
            } ${selectedId === p.player_id ? 'ring-2 ring-slate-900 ring-offset-1' : ''}`}
          >
            {initials(p.name)}
          </span>
          <span className="mt-0.5 max-w-[64px] truncate rounded bg-black/40 px-1 text-[8px] font-semibold leading-tight text-white">
            {p.name.split(/\s+/).pop()}
          </span>
        </button>
      ))}
    </div>
  );
}
