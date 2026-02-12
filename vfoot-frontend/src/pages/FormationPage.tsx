import { useMemo, useState } from 'react';
import PitchZoneMap from '../components/PitchZoneMap';
import Toast from '../components/Toast';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import { getLineupContext, saveLineup } from '../api';
import type { LineupContextResponse, RosterPlayer, SaveLineupRequest } from '../types/contracts';
import { useAsync } from '../utils/useAsync';

type Tab = 'titolari' | 'rosa' | 'panchina';
type View = 'coverage' | 'quality' | 'player';

export default function FormationPage() {
  const { data, loading, error } = useAsync(getLineupContext, []);

  const [tab, setTab] = useState<Tab>('titolari');
  const [view, setView] = useState<View>('quality');
  const [hoverPlayerId, setHoverPlayerId] = useState<string | null>(null);
  const [selectedStarterId, setSelectedStarterId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; tone?: 'slate' | 'green' | 'red' | 'amber' } | null>(null);
  const [saving, setSaving] = useState(false);

  if (loading) return <div className="text-sm text-slate-500">Caricamento formazione…</div>;
  if (error || !data) return <div className="text-sm text-red-600">Errore: {error?.message ?? '...'}...</div>;

  return <FormationInner
    ctx={data}
    tab={tab}
    setTab={setTab}
    view={view}
    setView={setView}
    hoverPlayerId={hoverPlayerId}
    setHoverPlayerId={setHoverPlayerId}
    selectedStarterId={selectedStarterId}
    setSelectedStarterId={setSelectedStarterId}
    toast={toast}
    setToast={setToast}
    saving={saving}
    setSaving={setSaving}
  />;
}

function FormationInner({
  ctx,
  tab,
  setTab,
  view,
  setView,
  hoverPlayerId,
  setHoverPlayerId,
  selectedStarterId,
  setSelectedStarterId,
  toast,
  setToast,
  saving,
  setSaving
}: {
  ctx: LineupContextResponse;
  tab: Tab;
  setTab: (t: Tab) => void;
  view: View;
  setView: (v: View) => void;
  hoverPlayerId: string | null;
  setHoverPlayerId: (id: string | null) => void;
  selectedStarterId: string | null;
  setSelectedStarterId: (id: string | null) => void;
  toast: { msg: string; tone?: 'slate' | 'green' | 'red' | 'amber' } | null;
  setToast: (t: { msg: string; tone?: 'slate' | 'green' | 'red' | 'amber' } | null) => void;
  saving: boolean;
  setSaving: (b: boolean) => void;
}) {
  const [lineup, setLineup] = useState(() => structuredClone(ctx.saved_lineup));

  const startersCount = ctx.rules.starters_count;
  const benchCount = ctx.rules.bench_count;

  const startersSet = useMemo(() => new Set(lineup.starter_player_ids), [lineup.starter_player_ids]);
  const benchSet = useMemo(() => new Set(lineup.bench_player_ids), [lineup.bench_player_ids]);

  const hoverPlayer = useMemo(() => ctx.roster.find((p) => p.player_id === hoverPlayerId) ?? null, [ctx.roster, hoverPlayerId]);

  const coverageCells = useMemo(() => {
    const src = view === 'coverage' ? ctx.coverage_preview.team_zone_coverage.values : ctx.coverage_preview.team_zone_quality.values;
    return ctx.zone_grid.zone_ids.map((zid, idx) => ({ zone_id: zid, value: src[idx], tone: 'none' as const }));
  }, [ctx.coverage_preview, ctx.zone_grid, view]);

  const hoverCells = useMemo(() => {
    if (!hoverPlayer) return null;
    const vals = hoverPlayer.estimated_influence.quality_map?.values ?? hoverPlayer.estimated_influence.zone_map.values;
    const max = Math.max(...vals, 0.0001);
    const norm = vals.map((v) => v / max);
    return ctx.zone_grid.zone_ids.map((zid, idx) => ({ zone_id: zid, value: norm[idx], tone: 'away' as const }));
  }, [ctx.zone_grid, hoverPlayer]);

  const starterPlayers = useMemo(() => ctx.roster.filter((p) => startersSet.has(p.player_id)), [ctx.roster, startersSet]);
  const benchPlayers = useMemo(() => ctx.roster.filter((p) => benchSet.has(p.player_id)), [ctx.roster, benchSet]);

  const selectedStarter = useMemo(() => ctx.roster.find((p) => p.player_id === selectedStarterId) ?? null, [ctx.roster, selectedStarterId]);
  const backupsForSelected = useMemo(() => {
    if (!selectedStarterId) return [];
    return lineup.starter_backups.find((x) => x.starter_player_id === selectedStarterId)?.backup_player_ids ?? [];
  }, [lineup.starter_backups, selectedStarterId]);

  function toggleStarter(p: RosterPlayer) {
    setLineup((prev) => {
      const next = structuredClone(prev);
      const inStarters = next.starter_player_ids.includes(p.player_id);
      if (inStarters) {
        next.starter_player_ids = next.starter_player_ids.filter((id) => id !== p.player_id);
        if (next.gk_player_id === p.player_id) next.gk_player_id = null;
        // remove related backup mapping
        next.starter_backups = next.starter_backups.filter((x) => x.starter_player_id !== p.player_id);
      } else {
        if (next.starter_player_ids.length >= startersCount) {
          setToast({ msg: `Hai già ${startersCount} titolari. Rimuovine uno prima.`, tone: 'amber' });
          return prev;
        }
        next.starter_player_ids = [...next.starter_player_ids, p.player_id];
      }
      // cannot be bench if starter
      next.bench_player_ids = next.bench_player_ids.filter((id) => id !== p.player_id);
      return next;
    });
  }

  function setAsGk(p: RosterPlayer) {
    setLineup((prev) => {
      const next = structuredClone(prev);
      if (!next.starter_player_ids.includes(p.player_id)) {
        // ensure in starters
        if (next.starter_player_ids.length >= startersCount) {
          setToast({ msg: `Hai già ${startersCount} titolari. Rimuovine uno prima.`, tone: 'amber' });
          return prev;
        }
        next.starter_player_ids = [...next.starter_player_ids, p.player_id];
        next.bench_player_ids = next.bench_player_ids.filter((id) => id !== p.player_id);
      }
      next.gk_player_id = p.player_id;
      return next;
    });
    setToast({ msg: `${p.name} impostato come portiere`, tone: 'green' });
  }

  function toggleBench(p: RosterPlayer) {
    setLineup((prev) => {
      const next = structuredClone(prev);
      if (next.starter_player_ids.includes(p.player_id)) {
        setToast({ msg: `È un titolare: rimuovilo dai titolari prima.`, tone: 'amber' });
        return prev;
      }
      const inBench = next.bench_player_ids.includes(p.player_id);
      if (inBench) {
        next.bench_player_ids = next.bench_player_ids.filter((id) => id !== p.player_id);
        // also remove as backup everywhere
        next.starter_backups = next.starter_backups.map((x) => ({
          ...x,
          backup_player_ids: x.backup_player_ids.filter((id) => id !== p.player_id)
        }));
      } else {
        if (next.bench_player_ids.length >= benchCount) {
          setToast({ msg: `Hai già ${benchCount} panchinari.`, tone: 'amber' });
          return prev;
        }
        next.bench_player_ids = [...next.bench_player_ids, p.player_id];
      }
      return next;
    });
  }

  function toggleBackupForSelected(backupId: string) {
    if (!selectedStarterId) return;
    setLineup((prev) => {
      const next = structuredClone(prev);
      const entry = next.starter_backups.find((x) => x.starter_player_id === selectedStarterId);
      if (!entry) {
        next.starter_backups.push({ starter_player_id: selectedStarterId, backup_player_ids: [backupId] });
      } else {
        const has = entry.backup_player_ids.includes(backupId);
        entry.backup_player_ids = has ? entry.backup_player_ids.filter((id) => id !== backupId) : [...entry.backup_player_ids, backupId];
      }
      return next;
    });
  }

  const canSave = lineup.starter_player_ids.length === startersCount && (!ctx.rules.gk_separate_slot || !!lineup.gk_player_id);

  async function onSave() {
    if (!canSave) {
      setToast({ msg: 'Completa 11 titolari (e seleziona il portiere) prima di salvare.', tone: 'amber' });
      return;
    }
    setSaving(true);
    try {
      const req: SaveLineupRequest = {
        league_id: ctx.league.id,
        matchday_id: ctx.matchday.id,
        gk_player_id: lineup.gk_player_id ?? null,
        starter_player_ids: lineup.starter_player_ids,
        bench_player_ids: lineup.bench_player_ids,
        starter_backups: lineup.starter_backups
      };
      const res = await saveLineup(req);
      setToast({ msg: `Formazione salvata (${new Date(res.saved_at).toLocaleTimeString()})`, tone: 'green' });
    } catch (e) {
      setToast({ msg: `Errore salvataggio: ${e instanceof Error ? e.message : String(e)}`, tone: 'red' });
    } finally {
      setSaving(false);
    }
  }

  const tabs = (
    <div className="md:hidden grid grid-cols-3 rounded-2xl bg-slate-200 p-1 text-sm font-semibold">
      <button onClick={() => setTab('titolari')} className={tab === 'titolari' ? 'rounded-xl bg-white py-2' : 'py-2 text-slate-600'}>Titolari</button>
      <button onClick={() => setTab('rosa')} className={tab === 'rosa' ? 'rounded-xl bg-white py-2' : 'py-2 text-slate-600'}>Rosa</button>
      <button onClick={() => setTab('panchina')} className={tab === 'panchina' ? 'rounded-xl bg-white py-2' : 'py-2 text-slate-600'}>Panchina</button>
    </div>
  );

  const topActions = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2">
        <SectionTitle>Copertura</SectionTitle>
        <div className="flex gap-1 rounded-xl bg-slate-200 p-1 text-xs font-semibold">
          <button onClick={() => setView('quality')} className={view === 'quality' ? 'rounded-lg bg-white px-2 py-1' : 'px-2 py-1 text-slate-600'}>Qualità</button>
          <button onClick={() => setView('coverage')} className={view === 'coverage' ? 'rounded-lg bg-white px-2 py-1' : 'px-2 py-1 text-slate-600'}>Densità</button>
          <button onClick={() => setView('player')} className={view === 'player' ? 'rounded-lg bg-white px-2 py-1' : 'px-2 py-1 text-slate-600'}>Preview</button>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Badge tone={canSave ? 'green' : 'amber'}>{lineup.starter_player_ids.length}/{startersCount} titolari</Badge>
        {ctx.rules.gk_separate_slot ? <Badge tone={lineup.gk_player_id ? 'green' : 'amber'}>GK</Badge> : null}
        <Button onClick={onSave} disabled={saving}>
          {saving ? 'Salvataggio…' : 'Salva'}
        </Button>
      </div>
    </div>
  );

  const pitch = (
    <div className="space-y-3">
      {topActions}

      <PitchZoneMap
        grid={ctx.zone_grid}
        title="Campo (stima)"
        legend={
          <div className="text-xs text-slate-500">
            {view === 'player' ? (hoverPlayer ? `Preview: ${hoverPlayer.name}` : 'Hover/tap su un giocatore per vedere la sua heatmap') : 'Zone colorate = copertura della tua formazione'}
          </div>
        }
        cells={view === 'player' && hoverCells ? hoverCells : coverageCells}
      />

      <Card className="p-4">
        <SectionTitle>Indicatori sintetici</SectionTitle>
        <div className="mt-2 grid grid-cols-3 gap-2 text-sm">
          <MiniBar label="Dif" value={ctx.coverage_preview.summary.def_mid_att.def} />
          <MiniBar label="Cen" value={ctx.coverage_preview.summary.def_mid_att.mid} />
          <MiniBar label="Att" value={ctx.coverage_preview.summary.def_mid_att.att} />
        </div>
        <div className="mt-3 text-xs text-slate-500">
          Buchi critici: {ctx.coverage_preview.summary.critical_holes.length ? ctx.coverage_preview.summary.critical_holes.join(', ') : 'nessuno'}
        </div>
      </Card>
    </div>
  );

  const rosterList = (
    <Card className="p-4">
      <SectionTitle>Rosa (tap/hover per preview)</SectionTitle>
      <div className="mt-3 space-y-2">
        {ctx.roster.map((p) => {
          const isStarter = startersSet.has(p.player_id);
          const isBench = benchSet.has(p.player_id);
          const isGk = lineup.gk_player_id === p.player_id;
          const risk = p.status.minutes_expectation.label === 'low';

          return (
            <div
              key={p.player_id}
              className="flex items-center justify-between gap-2 rounded-xl border border-slate-100 bg-white p-3 hover:bg-slate-50"
              onMouseEnter={() => setHoverPlayerId(p.player_id)}
              onMouseLeave={() => setHoverPlayerId(null)}
              onClick={() => {
                // on mobile: tap toggles preview mode
                setHoverPlayerId(p.player_id);
                setView('player');
              }}
            >
              <div>
                <div className="font-semibold">{p.name}</div>
                <div className="text-xs text-slate-500">{p.real_team} · €{p.price}</div>
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2">
                {risk ? <Badge tone="amber">minuti bassi</Badge> : null}
                {isGk ? <Badge tone="green">GK</Badge> : null}
                {isStarter ? <Badge tone="green">titolare</Badge> : isBench ? <Badge tone="slate">panchina</Badge> : <Badge tone="slate">rosa</Badge>}
                <div className="flex gap-1">
                  <Button size="sm" variant={isStarter ? 'secondary' : 'primary'} onClick={() => toggleStarter(p)}>
                    {isStarter ? 'Togli' : 'Titolare'}
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => toggleBench(p)}>
                    {isBench ? 'No p.' : 'Panch.'}
                  </Button>
                  {ctx.rules.gk_separate_slot ? (
                    <Button size="sm" variant="ghost" onClick={() => setAsGk(p)}>
                      GK
                    </Button>
                  ) : null}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );

  const startersPanel = (
    <Card className="p-4">
      <SectionTitle>Titolari ({lineup.starter_player_ids.length}/{startersCount})</SectionTitle>
      <div className="mt-3 space-y-2">
        {starterPlayers.length ? (
          starterPlayers.map((p) => {
            const isSelected = selectedStarterId === p.player_id;
            const backups = lineup.starter_backups.find((x) => x.starter_player_id === p.player_id)?.backup_player_ids ?? [];
            return (
              <button
                key={p.player_id}
                onClick={() => setSelectedStarterId(p.player_id)}
                onMouseEnter={() => setHoverPlayerId(p.player_id)}
                onMouseLeave={() => setHoverPlayerId(null)}
                className={
                  "w-full text-left rounded-xl border p-3 " +
                  (isSelected ? 'border-slate-900 bg-slate-50' : 'border-slate-100 bg-white hover:bg-slate-50')
                }
              >
                <div className="flex items-center justify-between">
                  <div className="font-semibold">{p.name}</div>
                  <div className="flex items-center gap-2">
                    {lineup.gk_player_id === p.player_id ? <Badge tone="green">GK</Badge> : null}
                    <Badge tone="slate">riserve: {backups.length}</Badge>
                  </div>
                </div>
                <div className="text-xs text-slate-500">{p.real_team} · €{p.price}</div>
              </button>
            );
          })
        ) : (
          <div className="text-sm text-slate-500">Seleziona i titolari dalla rosa.</div>
        )}
      </div>

      <div className="mt-4">
        <SectionTitle>Riserve per titolare selezionato</SectionTitle>
        {!selectedStarter ? (
          <div className="mt-2 text-sm text-slate-500">Tocca un titolare per assegnare riserve specifiche.</div>
        ) : (
          <div className="mt-2">
            <div className="text-sm font-semibold">{selectedStarter.name}</div>
            <div className="text-xs text-slate-500">Scegli dalla panchina i sostituti preferiti per questo titolare.</div>
            <div className="mt-3 space-y-2">
              {benchPlayers.length ? (
                benchPlayers.map((b) => {
                  const checked = backupsForSelected.includes(b.player_id);
                  return (
                    <label
                      key={b.player_id}
                      className="flex items-center justify-between gap-2 rounded-xl border border-slate-100 bg-white p-3"
                    >
                      <div>
                        <div className="font-semibold">{b.name}</div>
                        <div className="text-xs text-slate-500">{b.real_team} · €{b.price}</div>
                      </div>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleBackupForSelected(b.player_id)}
                        className="h-5 w-5"
                      />
                    </label>
                  );
                })
              ) : (
                <div className="text-sm text-slate-500">Seleziona prima i panchinari.</div>
              )}
            </div>
            {benchPlayers.length ? (
              <div className="mt-2 text-xs text-slate-500">Riserve selezionate: {backupsForSelected.length}</div>
            ) : null}
          </div>
        )}
      </div>
    </Card>
  );

  const benchPanel = (
    <Card className="p-4">
      <SectionTitle>Panchina ({lineup.bench_player_ids.length}/{benchCount})</SectionTitle>
      <div className="mt-3 space-y-2">
        {benchPlayers.length ? (
          benchPlayers.map((p) => (
            <div key={p.player_id} className="flex items-center justify-between gap-2 rounded-xl border border-slate-100 bg-white p-3">
              <div>
                <div className="font-semibold">{p.name}</div>
                <div className="text-xs text-slate-500">{p.real_team} · €{p.price}</div>
              </div>
              <Button size="sm" variant="secondary" onClick={() => toggleBench(p)}>
                Rimuovi
              </Button>
            </div>
          ))
        ) : (
          <div className="text-sm text-slate-500">Nessun panchinaro selezionato.</div>
        )}
      </div>

      <div className="mt-4 text-xs text-slate-500">
        Suggerimento: imposta riserve specifiche per i titolari a rischio minutaggio.
      </div>
    </Card>
  );

  return (
    <div className="space-y-4">
      {tabs}

      {/* Desktop: 3 colonne */}
      <div className="hidden md:grid md:grid-cols-[1fr_360px_360px] md:gap-4">
        <div className="space-y-4">
          {pitch}
          {rosterList}
        </div>
        <div className="space-y-4">{startersPanel}</div>
        <div className="space-y-4">{benchPanel}</div>
      </div>

      {/* Mobile: tab-based */}
      <div className="md:hidden space-y-4">
        {pitch}
        {tab === 'titolari' ? startersPanel : null}
        {tab === 'rosa' ? rosterList : null}
        {tab === 'panchina' ? benchPanel : null}
      </div>

      {toast ? <Toast message={toast.msg} tone={toast.tone} onClose={() => setToast(null)} /> : null}
    </div>
  );
}

function MiniBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl bg-slate-100 p-3">
      <div className="text-xs font-semibold text-slate-500">{label}</div>
      <div className="mt-2 h-2 rounded-full bg-slate-200">
        <div className="h-2 rounded-full bg-slate-900" style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <div className="mt-1 text-xs font-semibold text-slate-700">{Math.round(value * 100)}%</div>
    </div>
  );
}
