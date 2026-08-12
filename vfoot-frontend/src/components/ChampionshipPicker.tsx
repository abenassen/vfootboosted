import { Badge } from './ui';
import { useChampionship } from '../league/ChampionshipContext';

/** IL CAMPIONATO CHE SI STA GUARDANDO, per chi non è in nessuna lega.
 *
 *  Un selettore solo se c'è davvero qualcosa da scegliere: con un campionato
 *  solo — che è il caso di oggi, la Serie A — una tendina a una voce chiede una
 *  decisione già presa. Allora sparisce, tranne dove il nome del campionato non
 *  sarebbe scritto da nessun'altra parte (`showWhenSingle`, la home): lì resta
 *  come etichetta. Dentro una lega non si vede mai: là il campionato lo ha
 *  scelto la lega alla nascita e non si cambia più.
 */
export default function ChampionshipPicker({ showWhenSingle = false }: { showWhenSingle?: boolean }) {
  const { browsing, seasons, season, setSeasonId } = useChampionship();
  if (!browsing || !season) return null;
  if (seasons.length < 2)
    return showWhenSingle ? <Badge tone="blue">{season.name}</Badge> : null;
  return (
    <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-ink-soft">
      Campionato
      <select
        value={season.id}
        onChange={(e) => setSeasonId(Number(e.target.value))}
        className="rounded-lg border border-line bg-surface px-2 py-1 text-xs font-semibold text-ink"
      >
        {seasons.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
    </label>
  );
}
