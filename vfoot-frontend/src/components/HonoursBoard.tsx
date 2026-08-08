import { useEffect, useState } from 'react';
import { Card, SectionTitle } from './ui';
import Crest from './Crest';
import { getManagerHonours } from '../api';
import type { HonourItem } from '../types/league';

/** L'albo d'oro di un fantallenatore: quello che ha vinto, dove e quando.
 *
 *  Reads the MANAGER's board and not the team's, deliberately: a team lasts one
 *  league and the person does not, so a cup won two seasons ago belongs on this
 *  card even though the team that won it no longer exists. That is also why it
 *  lives on his profile page and no longer on a roster: a roster is the property
 *  of one team in one league and ends with it. The backend decides which leagues
 *  the viewer may see (the ones he shares); a 404 means none, and the card simply
 *  does not appear rather than announcing a refusal.
 *
 *  Nome e stemma di ogni riga sono quelli CONGELATI all'assegnazione (vedi
 *  services/honours): ribattezzare la propria squadra non riscrive il passato.
 *
 *  C'È SEMPRE, anche vuoto, e anche sulla scheda di un altro. Prima spariva per
 *  chi non aveva ancora vinto niente, per non dire a un visitatore "questo
 *  fantallenatore non ha mai vinto niente" — che è uno sfottò, non
 *  un'informazione. Ma l'effetto era peggiore della cosa che evitava: sulla
 *  propria scheda l'albo d'oro c'era e sulle altre no, quindi la stessa pagina
 *  aveva due forme diverse e sembrava un pezzo mancante invece di una bacheca
 *  vuota. E prima che una competizione finisca sono vuote TUTTE, cioè la sezione
 *  non esisteva per nessuno proprio quando la si stava cercando.
 *
 *  Il tono risolve la cosa meglio della sparizione: di un avversario si dice che
 *  la bacheca è vuota, non che non ha mai vinto niente.
 */
export default function HonoursBoard({
  userId,
  name,
  own = false,
}: {
  userId: number;
  name?: string;
  own?: boolean;
}) {
  const [awards, setAwards] = useState<HonourItem[] | null>(null);

  useEffect(() => {
    let alive = true;
    setAwards(null);
    void getManagerHonours(userId)
      .then((r) => alive && setAwards(r.awards))
      .catch(() => alive && setAwards([]));
    return () => {
      alive = false;
    };
  }, [userId]);

  // Solo mentre si carica: un attimo di niente, non una sezione che non c'è.
  if (awards === null) return null;

  return (
    <Card className="p-4">
      <div className="flex items-baseline justify-between gap-3">
        <SectionTitle>Albo d'oro</SectionTitle>
        {awards.length ? (
          <span className="text-xs text-ink-faint">
            {awards.length} {awards.length === 1 ? 'trofeo' : 'trofei'}
          </span>
        ) : null}
      </div>

      {awards.length ? (
        <ul className="mt-3 space-y-2">
          {awards.map((a) => (
            <li
              key={`${a.prize_id}-${a.team_id}`}
              className="flex items-center gap-3 rounded-xl border border-warn/40 bg-warn-bg/60 px-3 py-2"
            >
              <span className="text-2xl leading-none" aria-hidden>
                {a.icon}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate font-semibold text-warn">
                  {a.name}
                  {/* `shared_with` is a COUNT of the OTHER teams that tied, so it
                      needs "altri" or the line reads as a team number: a record
                      shared with one rival printed "(a pari merito con 1)". */}
                  {a.shared_with ? (
                    <span className="ml-1 text-xs font-normal text-warn">
                      {a.shared_with === 1
                        ? '(a pari merito con un’altra squadra)'
                        : `(a pari merito con altre ${a.shared_with} squadre)`}
                    </span>
                  ) : null}
                </div>
                <div className="truncate text-xs text-warn">
                  {a.competition_name} · {a.condition_label}
                </div>
                <div className="truncate text-xs text-ink-faint">
                  {a.league_name}
                  {a.at ? ` · ${new Date(a.at).toLocaleDateString('it-IT')}` : ''}
                </div>
              </div>
              {a.team_id ? (
                <span className="shrink-0 text-right">
                  <Crest descriptor={a.crest} teamName={a.team_name ?? ''} size={26} />
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-2 text-sm text-ink-faint">
          {own
            ? 'Bacheca vuota: i premi delle competizioni concluse finiscono qui.'
            : `Bacheca vuota${name ? ` di ${name}` : ''}: i premi delle competizioni concluse finiscono qui.`}
        </div>
      )}
    </Card>
  );
}
