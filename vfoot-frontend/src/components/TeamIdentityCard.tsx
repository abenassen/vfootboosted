import { useCallback, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
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

  // Il ritaglio scelto ma non ancora caricato. Il ref serve a eseguirlo dentro
  // save(); il booleano serve a farlo contare fra le cose «da salvare», perché
  // una foto inquadrata e non ancora spedita è a tutti gli effetti una modifica
  // in sospeso. Il callback è stabile (deps vuote) o l'effetto che lo registra
  // dall'altra parte si rincorrerebbe da solo.
  const pendingCropRef = useRef<(() => Promise<string>) | null>(null);
  const [hasPendingCrop, setHasPendingCrop] = useState(false);
  const onPendingChange = useCallback((commit: (() => Promise<string>) | null) => {
    pendingCropRef.current = commit;
    setHasPendingCrop(commit !== null);
  }, []);

  function open() {
    setDraftName(name);
    setDraftCrest(parseCrest(crest) ?? defaultCrest(name));
    setError(null);
    setEditing(true);
  }

  // Confronto fra forme NORMALIZZATE, non fra la stringa salvata e quella del
  // draft: un descrittore vecchio non ha le chiavi aggiunte dopo, e `parseCrest`
  // gliele riempie — quindi il confronto grezzo direbbe «da salvare» appena si
  // apre l'editor, senza che nessuno abbia toccato niente.
  const cambiate = [
    draftName.trim() !== name ? 'nome' : null,
    hasPendingCrop ||
    serializeCrest(draftCrest) !== serializeCrest(parseCrest(crest) ?? defaultCrest(name))
      ? 'stemma'
      : null,
  ].filter(Boolean) as string[];
  const dirty = cambiate.length > 0;

  async function save() {
    const trimmed = draftName.trim();
    if (!trimmed) {
      setError('Il nome della squadra non può essere vuoto.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      // Il ritaglio in sospeso PRIMA di tutto: è l'unico pezzo che ha bisogno di
      // un giro di rete suo, e se fallisce non deve lasciare la squadra
      // rinominata a metà. Se va storto usciamo dal catch qui sotto con
      // l'editor ancora aperto e il ritaglio ancora al suo posto.
      let opzioni = draftCrest;
      if (pendingCropRef.current) {
        const hash = await pendingCropRef.current();
        opzioni = { ...draftCrest, img: hash };
        setDraftCrest(opzioni);
      }

      // Only what actually changed: sending the name back unchanged would make a
      // clash with another team's name fail a save that changes nothing but the
      // crest.
      const patch: { name?: string; crest?: string } = {};
      if (trimmed !== name) patch.name = trimmed;
      const nextCrest = serializeCrest(opzioni);
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
            {subtitle ? <div className="text-sm text-ink-faint">{subtitle}</div> : null}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {/* The other teams' roster page has a way back; one's own did not, and
              it is reached the same way. */}
          <Link to="/home">
            <Button size="sm" variant="ghost">
              ← Home lega
            </Button>
          </Link>
          {action}
          <Button size="sm" variant="secondary" onClick={() => (editing ? setEditing(false) : open())}>
            {editing ? 'Chiudi' : '✏️ Nome e stemma'}
          </Button>
        </div>
      </div>

      {editing ? (
        <div className="mt-4 border-t pt-4">
          <label className="block">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
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
            <CrestBuilder
              value={draftCrest}
              teamName={draftName || name}
              onChange={setDraftCrest}
              onPendingChange={onPendingChange}
            />
          </div>

          {error ? <div className="mt-3 rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">{error}</div> : null}

          {/* Stesso segnale delle opzioni partita in gestione lega: finché c'è
              qualcosa di non salvato lo si dice, invece di lasciarlo indovinare
              dal fatto che un pulsante esiste. Conta anche il ritaglio scelto e
              non ancora spedito, che è la modifica più facile da credere già
              conclusa: la foto è lì, si vede, sembra fatta. */}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button disabled={saving} onClick={() => void save()}>
              {saving ? 'Salvo…' : 'Salva'}
            </Button>
            <Button variant="secondary" disabled={saving} onClick={() => setEditing(false)}>
              Annulla
            </Button>
            {dirty ? (
              <span className="rounded-full bg-warn px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
                {cambiate.length === 1
                  ? `${cambiate[0]} da salvare`
                  : 'nome e stemma da salvare'}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
    </Card>
  );
}
