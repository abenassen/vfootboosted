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
 *  Silent when empty for anyone but the owner — telling a visitor "questo
 *  fantallenatore non ha mai vinto niente" is a taunt, not information. On your
 *  own page the empty state is the point: it says where the trophies will go.
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

  if (awards === null) return null;
  if (!awards.length && !own) return null;

  return (
    <Card className="p-4">
      <div className="flex items-baseline justify-between gap-3">
        <SectionTitle>Albo d'oro</SectionTitle>
        {awards.length ? (
          <span className="text-xs text-slate-400">
            {awards.length} {awards.length === 1 ? 'trofeo' : 'trofei'}
          </span>
        ) : null}
      </div>

      {awards.length ? (
        <ul className="mt-3 space-y-2">
          {awards.map((a) => (
            <li
              key={`${a.prize_id}-${a.team_id}`}
              className="flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50/60 px-3 py-2"
            >
              <span className="text-2xl leading-none" aria-hidden>
                {a.icon}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate font-semibold text-amber-900">
                  {a.name}
                  {/* `shared_with` is a COUNT of the OTHER teams that tied, so it
                      needs "altri" or the line reads as a team number: a record
                      shared with one rival printed "(a pari merito con 1)". */}
                  {a.shared_with ? (
                    <span className="ml-1 text-xs font-normal text-amber-700">
                      {a.shared_with === 1
                        ? '(a pari merito con un’altra squadra)'
                        : `(a pari merito con altre ${a.shared_with} squadre)`}
                    </span>
                  ) : null}
                </div>
                <div className="truncate text-xs text-amber-800">
                  {a.competition_name} · {a.condition_label}
                </div>
                <div className="truncate text-xs text-slate-500">
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
        <div className="mt-2 text-sm text-slate-500">
          {name ? `${name} non ha` : 'Non hai'} ancora vinto niente: i premi delle competizioni concluse finiscono qui.
        </div>
      )}
    </Card>
  );
}
