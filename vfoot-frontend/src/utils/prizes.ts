import type { PrizeStat } from '../types/league';

/** I primati che una lega può mettere in palio, detti come li direbbe lei.
 *
 *  The backend stores a measure and a direction; an admin thinks in whole
 *  phrases ("miglior difesa"), and the two do not map one-to-one — the same
 *  measure read from the other end is a different prize with a different name.
 *  So the vocabulary lives here, once, and both the wizard and the edit page
 *  offer exactly the same list.
 *
 *  Order is deliberate: the honours anyone would actually award first, the joke
 *  ones (which are just as popular, and are the reason the direction exists at
 *  all) at the bottom.
 */
export type PrizeRecord = {
  value: string;
  label: string;
  stat: PrizeStat;
  direction: 'top' | 'bottom';
};

export const PRIZE_RECORDS: PrizeRecord[] = [
  { value: 'avg_score_top', label: 'Media punteggio più alta', stat: 'avg_score', direction: 'top' },
  { value: 'goals_for_top', label: 'Miglior attacco', stat: 'goals_for', direction: 'top' },
  { value: 'goals_against_bottom', label: 'Miglior difesa', stat: 'goals_against', direction: 'bottom' },
  { value: 'best_round_top', label: 'Miglior punteggio in una giornata', stat: 'best_round', direction: 'top' },
  { value: 'wins_top', label: 'Più vittorie', stat: 'wins', direction: 'top' },
  { value: 'avg_score_bottom', label: 'Media punteggio più bassa', stat: 'avg_score', direction: 'bottom' },
  { value: 'goals_for_bottom', label: 'Peggior attacco', stat: 'goals_for', direction: 'bottom' },
  { value: 'goals_against_top', label: 'Peggior difesa', stat: 'goals_against', direction: 'top' },
];

export const DEFAULT_RECORD = PRIZE_RECORDS[0];

export function recordByValue(value: string | undefined): PrizeRecord {
  return PRIZE_RECORDS.find((r) => r.value === value) ?? DEFAULT_RECORD;
}
