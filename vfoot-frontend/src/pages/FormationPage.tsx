import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import { getTeamLineup, saveTeamLineup } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import type { PlayerRole, TeamLineupContext, TeamLineupPlayer } from '../types/lineup';

const XI = 11; // starters incl. exactly one goalkeeper

const ROLE_LABEL: Record<PlayerRole, string> = { GK: 'POR', DEF: 'DIF', MID: 'CEN', ATT: 'ATT' };
const ROLE_CHIP: Record<PlayerRole, string> = {
  GK: 'bg-amber-500',
  DEF: 'bg-blue-500',
  MID: 'bg-emerald-500',
  ATT: 'bg-orange-500',
};
const ROLE_ORDER: Record<PlayerRole, number> = { GK: 0, DEF: 1, MID: 2, ATT: 3 };

export default function FormationPage() {
  const { selectedLeagueId } = useLeagueContext();
  const [searchParams, setSearchParams] = useSearchParams();
  const competition = searchParams.get('competition') ? Number(searchParams.get('competition')) : null;
  const matchday = searchParams.get('matchday') ? Number(searchParams.get('matchday')) : null;

  const [ctx, setCtx] = useState<TeamLineupContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [starterIds, setStarterIds] = useState<number[]>([]);
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
        if (saved && (saved.gk_player_id || saved.starter_player_ids.length)) {
          const ids = [...(saved.gk_player_id ? [saved.gk_player_id] : []), ...saved.starter_player_ids];
          setStarterIds(ids.slice(0, XI));
        } else {
          setStarterIds(suggest(d.roster));
        }
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

  const toggleStarter = (id: number) => {
    setStarterIds((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= XI ? s : [...s, id]));
  };

  const gkOk = gkStarters.length === 1;
  const canSave = starterIds.length === XI && gkOk;
  const onSave = async () => {
    if (!canSave || !selectedLeagueId || matchday == null) return;
    setSaving(true);
    try {
      const benchIds = ctx.roster.map((p) => p.player_id).filter((id) => !starterIds.includes(id));
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

  const roster = [...ctx.roster].sort((a, b) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role] || b.form - a.form);
  const compName = ctx.competitions.find((c) => c.competition_id === competition)?.name;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <SectionTitle>Formazione · {ctx.team.name}</SectionTitle>
            <div className="mt-1 text-sm text-slate-600">
              {compName ? <>Competizione <b>{compName}</b> · </> : null}
              titolari {starterIds.length}/{XI}
              {gkStarters.length !== 1 ? (
                <span className="ml-2 font-semibold text-rose-600">
                  {gkStarters.length === 0 ? '· manca il portiere' : '· un solo portiere consentito'}
                </span>
              ) : null}
            </div>
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
            Posizione attesa di ogni titolare (dai dati storici). Il portiere ha il bordo ambra. Clicca un giocatore per
            vederne le zone d'influenza.
          </div>
          <PitchLineup
            starterIds={starterIds}
            byId={byId}
            gkId={gkId}
            selectedId={selected}
            onSelect={(id) => setSelected((s) => (s === id ? null : id))}
          />
        </Card>

        <Card className="p-4">
          <SectionTitle>Rosa · titolari e panchina (un solo portiere fra i titolari)</SectionTitle>
          <div className="mt-1 text-[11px] text-slate-400">Clicca il nome per vederne il footprint sulla mappa.</div>
          <div className="mt-2 divide-y">
            {roster.map((p) => (
              <RosterRow
                key={p.player_id}
                p={p}
                isStarter={starterIds.includes(p.player_id)}
                isGk={gkId === p.player_id}
                selected={selected === p.player_id}
                onSelect={() => setSelected((s) => (s === p.player_id ? null : p.player_id))}
                onToggle={() => toggleStarter(p.player_id)}
              />
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function RosterRow({
  p,
  isStarter,
  isGk,
  selected,
  onSelect,
  onToggle,
}: {
  p: TeamLineupPlayer;
  isStarter: boolean;
  isGk: boolean;
  selected: boolean;
  onSelect: () => void;
  onToggle: () => void;
}) {
  return (
    <div className={`flex items-center justify-between gap-2 py-2 ${selected ? 'bg-slate-50' : ''}`}>
      <button onClick={onSelect} className="flex min-w-0 items-center gap-2 text-left">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ${ROLE_CHIP[p.role]}`}>
          {ROLE_LABEL[p.role]}
        </span>
        <span className="min-w-0">
          <span className={`block truncate text-sm font-semibold ${selected ? 'text-slate-900 underline' : 'text-slate-800'}`}>
            {p.name}
            {isStarter && isGk ? <span className="ml-1 text-[10px] font-bold text-amber-600">(portiere)</span> : null}
          </span>
          <span className="text-[11px] text-slate-500">
            {p.avg_minutes}′ medi · rend. atteso{' '}
            <b className={p.form >= 0 ? 'text-emerald-600' : 'text-rose-600'}>{p.form.toFixed(2)}</b>
            {p.minutes_label === 'low' ? <Badge tone="amber"> poco impiegato</Badge> : null}
          </span>
        </span>
      </button>
      <div className="flex shrink-0 overflow-hidden rounded-lg border border-slate-200 text-[11px] font-semibold">
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

const ROLE_RGB: Record<PlayerRole, string> = {
  GK: '251,191,36',
  DEF: '59,130,246',
  MID: '16,185,129',
  ATT: '249,115,22',
};

// The XI placed on a pitch at each player's expected position. Defence on the
// left, attack on the right; goalkeeper ringed in amber.
function PitchLineup({
  starterIds,
  byId,
  gkId,
  selectedId,
  onSelect,
}: {
  starterIds: number[];
  byId: Map<number, TeamLineupPlayer>;
  gkId: number | null;
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  // Lay the XI out as formation lines: depth (x) from each player's expected
  // column, width (y) spread within their role line so dots never pile up
  // (footprint centroids alone bunch everyone in the middle).
  // Base position from the player's REFERENCE zone: depth (x) by role band +
  // expected column, lateral (y) by the expected row (so wide players stay wide,
  // central players stay central — attackers are no longer flung to the flanks).
  const ROLE_X: Record<PlayerRole, number> = { GK: 8, DEF: 30, MID: 53, ATT: 76 };
  const TYPICAL_COL: Record<PlayerRole, number> = { GK: 0, DEF: 1, MID: 2, ATT: 3 };
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
  const selMax = sel ? Math.max(0.0001, ...Object.values(sel.footprint)) : 1;
  const selRgb = sel ? ROLE_RGB[sel.role] : '0,0,0';
  return (
    <div className="relative mt-3 aspect-[7/5] w-full overflow-hidden rounded-xl border border-green-700/40 bg-gradient-to-r from-green-600 to-green-500 shadow-inner">
      {/* pitch markings */}
      <div className="pointer-events-none absolute inset-2 rounded border border-white/40" />
      <div className="pointer-events-none absolute inset-y-2 left-1/2 w-px -translate-x-1/2 bg-white/40" />
      <div className="pointer-events-none absolute left-1/2 top-1/2 h-16 w-16 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/40" />
      <div className="pointer-events-none absolute left-2 top-1/2 h-24 w-12 -translate-y-1/2 border border-white/40" />
      <div className="pointer-events-none absolute right-2 top-1/2 h-24 w-12 -translate-y-1/2 border border-white/40" />
      {/* predicted influence zones of the selected player */}
      {sel
        ? Object.entries(sel.footprint).map(([z, share]) => {
            const m = /^Z_(\d+)_(\d+)$/.exec(z);
            if (!m) return null;
            const c = Number(m[1]);
            const r = Number(m[2]);
            return (
              <div
                key={z}
                className="pointer-events-none absolute"
                style={{
                  left: `${(c / 5) * 100}%`,
                  top: `${(r / 4) * 100}%`,
                  width: '20%',
                  height: '25%',
                  backgroundColor: `rgba(${selRgb},${0.08 + 0.55 * (share / selMax)})`,
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
          title={`${p.name} · rend. atteso ${p.form.toFixed(2)}`}
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
