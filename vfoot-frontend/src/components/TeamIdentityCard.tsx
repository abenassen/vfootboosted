import { useState, type ReactNode } from 'react';
import { updateMyTeam } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import Crest from './Crest';
import CrestBuilder from './CrestBuilder';
import { Button, Card, SectionTitle } from './ui';
import { defaultCrest, parseCrest, serializeCrest, type CrestOptions } from '../utils/crest';

/** Name and crest of the caller's team, edited where they belong: inside the
 *  league. They are NOT profile settings — the avatar identifies the manager and
 *  there is one per account, while these belong to one team in one league, and
 *  the same person fields a different team in every league.
 */
export default function TeamIdentityCard({
  leagueId,
  initialName,
  subtitle,
  action,
}: {
  leagueId: number;
  initialName: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  const { selectedLeague, refreshLeagues } = useLeagueContext();
  const [name, setName] = useState(initialName);
  const [crest, setCrest] = useState<string>(selectedLeague?.team_crest ?? '');

  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState(initialName);
  const [draftCrest, setDraftCrest] = useState<CrestOptions>(
    () => parseCrest(selectedLeague?.team_crest) ?? defaultCrest(initialName),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function open() {
    setDraftName(name);
    setDraftCrest(parseCrest(crest) ?? defaultCrest(name));
    setError(null);
    setEditing(true);
  }

  async function save() {
    const trimmed = draftName.trim();
    if (!trimmed) {
      setError('Il nome della squadra non può essere vuoto.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      // Only what actually changed: sending the name back unchanged would make a
      // clash with another team's name fail a save that changes nothing but the
      // crest.
      const patch: { name?: string; crest?: string } = {};
      if (trimmed !== name) patch.name = trimmed;
      const nextCrest = serializeCrest(draftCrest);
      if (nextCrest !== crest) patch.crest = nextCrest;

      if (Object.keys(patch).length) {
        const saved = await updateMyTeam(leagueId, patch);
        setName(saved.name);
        setCrest(saved.crest);
        // The league list carries the team name and crest into the top bar and
        // the switcher, so it has to be reloaded or the header keeps the old one.
        await refreshLeagues();
      }
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <Crest descriptor={crest} teamName={name} size={56} />
          <div className="min-w-0">
            <SectionTitle>Squadra</SectionTitle>
            <div className="mt-1 text-xl font-black">{name}</div>
            {subtitle ? <div className="text-sm text-slate-500">{subtitle}</div> : null}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {action}
          <Button size="sm" variant="secondary" onClick={() => (editing ? setEditing(false) : open())}>
            {editing ? 'Chiudi' : '✏️ Nome e stemma'}
          </Button>
        </div>
      </div>

      {editing ? (
        <div className="mt-4 border-t pt-4">
          <label className="block">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Nome squadra
            </span>
            <input
              className="mt-1 w-full max-w-sm rounded-xl border px-3 py-2 text-sm"
              value={draftName}
              maxLength={120}
              onChange={(e) => setDraftName(e.target.value)}
              placeholder="Nome squadra"
            />
          </label>

          <div className="mt-4">
            <CrestBuilder value={draftCrest} teamName={draftName || name} onChange={setDraftCrest} />
          </div>

          {error ? <div className="mt-3 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div> : null}

          <div className="mt-4 flex gap-2">
            <Button disabled={saving} onClick={() => void save()}>
              {saving ? 'Salvo…' : 'Salva'}
            </Button>
            <Button variant="secondary" disabled={saving} onClick={() => setEditing(false)}>
              Annulla
            </Button>
          </div>
        </div>
      ) : null}
    </Card>
  );
}
