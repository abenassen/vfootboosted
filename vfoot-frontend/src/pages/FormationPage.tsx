import { useEffect, useMemo, useState } from 'react';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import { getTeamLineup, saveTeamLineup } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { zoneName, zoneShortName } from '../utils/zoneNames';
import type { PlayerRole, TeamLineupContext, TeamLineupPlayer } from '../types/lineup';

const STARTERS = 10; // outfield; the GK is a separate slot

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
  const [matchday, setMatchday] = useState<number | null>(null);
  const [ctx, setCtx] = useState<TeamLineupContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [gkId, setGkId] = useState<number | null>(null);
  const [starterIds, setStarterIds] = useState<number[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  // Predictive default/suggestion: best GK by form + the top 10 outfielders by
  // expected contribution (recent form), all as-of the chosen matchday.
  const applySuggestion = (roster: TeamLineupPlayer[]) => {
    const gk = roster.filter((p) => p.role === 'GK').sort((a, b) => b.form - a.form)[0];
    const outfield = roster
      .filter((p) => p.role !== 'GK')
      .sort((a, b) => b.form - a.form)
      .slice(0, STARTERS)
      .map((p) => p.player_id);
    setGkId(gk ? gk.player_id : null);
    setStarterIds(outfield);
  };

  useEffect(() => {
    if (!selectedLeagueId) return;
    setLoading(true);
    setError(null);
    void getTeamLineup(selectedLeagueId, matchday ?? undefined)
      .then((d) => {
        setCtx(d);
        // First load (no matchday yet): jump to a mid-season matchday so we work
        // as if the lineup is being set partway through the season. The refetch
        // then loads as-of (no-leakage) profiles.
        if (matchday == null) {
          setMatchday(d.matchdays[Math.floor(d.matchdays.length / 2)] ?? d.matchday);
          return;
        }
        const saved = d.saved_lineup;
        if (saved && (saved.gk_player_id || saved.starter_player_ids.length)) {
          setGkId(saved.gk_player_id);
          setStarterIds(saved.starter_player_ids.slice(0, STARTERS));
        } else {
          applySuggestion(d.roster);
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [selectedLeagueId, matchday]);

  const byId = useMemo(() => new Map((ctx?.roster ?? []).map((p) => [p.player_id, p])), [ctx]);
  const onPitch = useMemo(() => [gkId, ...starterIds].filter((x): x is number => x != null), [gkId, starterIds]);

  // Live team coverage: summed footprints of the 11 on the pitch (or the
  // selected player's own footprint when one is selected).
  const coverage = useMemo(() => {
    const acc: Record<string, number> = {};
    const source = selected != null ? [selected] : onPitch;
    for (const id of source) {
      const fp = byId.get(id)?.footprint ?? {};
      for (const [z, v] of Object.entries(fp)) acc[z] = (acc[z] ?? 0) + v;
    }
    const max = Math.max(0.0001, ...Object.values(acc));
    return { values: acc, max };
  }, [onPitch, selected, byId]);

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega per impostare la formazione.</div>;
  if (loading && !ctx) return <div className="text-sm text-slate-500">Caricamento formazione…</div>;
  if (error || !ctx) return <div className="text-sm text-red-600">Errore: {error ?? '…'}</div>;

  const setGk = (id: number) => {
    setGkId(id);
    setStarterIds((s) => s.filter((x) => x !== id));
  };
  const addStarter = (id: number) => {
    setGkId((g) => (g === id ? null : g));
    setStarterIds((s) => (s.includes(id) || s.length >= STARTERS ? s : [...s, id]));
  };
  const benchify = (id: number) => {
    setGkId((g) => (g === id ? null : g));
    setStarterIds((s) => s.filter((x) => x !== id));
  };

  const canSave = gkId != null && starterIds.length === STARTERS;
  const onSave = async () => {
    if (!canSave || !selectedLeagueId || matchday == null) return;
    setSaving(true);
    try {
      const benchIds = ctx.roster.map((p) => p.player_id).filter((id) => id !== gkId && !starterIds.includes(id));
      await saveTeamLineup(selectedLeagueId, {
        matchday,
        gk_player_id: gkId,
        starter_player_ids: starterIds,
        bench_player_ids: benchIds,
      });
      setToast('Formazione salvata ✓');
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Errore nel salvataggio');
    } finally {
      setSaving(false);
      setTimeout(() => setToast(null), 2500);
    }
  };

  const roster = [...ctx.roster].sort((a, b) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role] || b.avg_minutes - a.avg_minutes);

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <SectionTitle>Formazione · {ctx.team.name}</SectionTitle>
            <div className="mt-1 text-sm text-slate-600">
              Portiere {gkId != null ? '✓' : '—'} · titolari di movimento {starterIds.length}/{STARTERS}
            </div>
            {ctx.as_of_matchday != null ? (
              <div className="mt-1 text-[11px] text-amber-600">
                Formazione per la giornata {ctx.as_of_matchday} · dati aggiornati alla giornata{' '}
                {ctx.as_of_matchday - 1} ({ctx.prior_matches} partite) — nessuna informazione futura.
              </div>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500">Giornata</label>
            <select
              value={matchday ?? ''}
              onChange={(e) => setMatchday(Number(e.target.value))}
              className="rounded-lg border border-slate-200 px-2 py-1 text-sm"
            >
              {ctx.matchdays.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <Button variant="secondary" onClick={() => applySuggestion(ctx.roster)}>
              Suggerisci XI
            </Button>
            <Button onClick={onSave} disabled={!canSave || saving}>
              {saving ? 'Salvataggio…' : 'Salva'}
            </Button>
          </div>
        </div>
        {toast ? <div className="mt-2 text-sm font-semibold text-green-700">{toast}</div> : null}
      </Card>

      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <SectionTitle>Copertura del campo</SectionTitle>
            {selected != null ? (
              <button onClick={() => setSelected(null)} className="text-[11px] font-semibold text-slate-500 hover:text-slate-700">
                ✕ {byId.get(selected)?.name}
              </button>
            ) : null}
          </div>
          <div className="mt-1 text-[11px] text-slate-400">
            {selected != null ? 'Footprint del giocatore selezionato.' : 'Presenza attesa dei titolari (più verde = più presidiata).'}
          </div>
          <CoverageGrid zoneKeys={ctx.zone_grid.zone_keys} values={coverage.values} max={coverage.max} />
        </Card>

        <Card className="p-4">
          <SectionTitle>Rosa · scegli portiere, titolari e panchina</SectionTitle>
          <div className="mt-1 text-[11px] text-slate-400">Clicca il nome per vederne il footprint sulla mappa.</div>
          <div className="mt-2 divide-y">
            {roster.map((p) => (
              <RosterRow
                key={p.player_id}
                p={p}
                isGk={gkId === p.player_id}
                isStarter={starterIds.includes(p.player_id)}
                selected={selected === p.player_id}
                onSelect={() => setSelected((s) => (s === p.player_id ? null : p.player_id))}
                onGk={() => setGk(p.player_id)}
                onStart={() => addStarter(p.player_id)}
                onBench={() => benchify(p.player_id)}
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
  isGk,
  isStarter,
  selected,
  onSelect,
  onGk,
  onStart,
  onBench,
}: {
  p: TeamLineupPlayer;
  isGk: boolean;
  isStarter: boolean;
  selected: boolean;
  onSelect: () => void;
  onGk: () => void;
  onStart: () => void;
  onBench: () => void;
}) {
  const state: 'gk' | 'xi' | 'bench' = isGk ? 'gk' : isStarter ? 'xi' : 'bench';
  return (
    <div className={`flex items-center justify-between gap-2 py-2 ${selected ? 'bg-slate-50' : ''}`}>
      <button onClick={onSelect} className="flex min-w-0 items-center gap-2 text-left">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ${ROLE_CHIP[p.role]}`}>
          {ROLE_LABEL[p.role]}
        </span>
        <span className="min-w-0">
          <span className={`block truncate text-sm font-semibold ${selected ? 'text-slate-900 underline' : 'text-slate-800'}`}>
            {p.name}
          </span>
          <span className="text-[11px] text-slate-500">
            {p.avg_minutes}′ medi · rend. atteso{' '}
            <b className={p.form >= 0 ? 'text-emerald-600' : 'text-rose-600'}>{p.form.toFixed(2)}</b>
            {p.minutes_label === 'low' ? <Badge tone="amber"> poco impiegato</Badge> : null}
          </span>
        </span>
      </button>
      <div className="flex shrink-0 overflow-hidden rounded-lg border border-slate-200 text-[11px] font-semibold">
        <Seg active={state === 'gk'} onClick={onGk} label="POR" activeClass="bg-amber-500 text-white" />
        <Seg active={state === 'xi'} onClick={onStart} label="XI" activeClass="bg-slate-900 text-white" />
        <Seg active={state === 'bench'} onClick={onBench} label="Panca" activeClass="bg-slate-500 text-white" />
      </div>
    </div>
  );
}

function Seg({ active, onClick, label, activeClass }: { active: boolean; onClick: () => void; label: string; activeClass: string }) {
  return (
    <button
      onClick={onClick}
      className={`px-2 py-1 ${active ? activeClass : 'bg-white text-slate-600 hover:bg-slate-100'}`}
    >
      {label}
    </button>
  );
}

// 5×4 pitch (col 0 = own goal → col 4 = attack), green intensity = presence.
function CoverageGrid({ zoneKeys, values, max }: { zoneKeys: string[]; values: Record<string, number>; max: number }) {
  const cols = 5;
  const rows = 4;
  return (
    <div className="mt-3 rounded-lg bg-gradient-to-r from-slate-100 to-green-50 p-2">
      <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0,1fr))` }}>
        {Array.from({ length: rows }).flatMap((_, r) =>
          Array.from({ length: cols }).map((__, c) => {
            const key = `Z_${c}_${r}`;
            const v = values[key] ?? 0;
            const intensity = v / max;
            return (
              <div
                key={key}
                title={`${zoneName(key)} · ${(v * 100).toFixed(0)}%`}
                className="flex h-9 items-center justify-center rounded text-[9px] font-semibold text-slate-700"
                style={{ backgroundColor: `rgba(34,197,94,${0.12 + 0.8 * intensity})` }}
              >
                {zoneKeys.includes(key) ? zoneShortName(key) : ''}
              </div>
            );
          }),
        )}
      </div>
      <div className="mt-1 flex justify-between text-[9px] uppercase tracking-wide text-slate-400">
        <span>← difesa</span>
        <span>attacco →</span>
      </div>
    </div>
  );
}
