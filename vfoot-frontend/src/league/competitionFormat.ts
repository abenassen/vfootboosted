import type { CompetitionItem } from '../types/league';

/**
 * What a competition is CALLED, everywhere.
 *
 * `competition_type` only knows round-robin from knockout, so a group stage
 * followed by a bracket came out labelled "Coppa" — a different thing from the
 * one the wizard was asked to build. `format` is what the user chose, so that is
 * what gets shown; the type stays the fallback for competitions built before it
 * existed.
 */
export const COMPETITION_FORMAT_LABEL: Record<string, string> = {
  league: 'Campionato',
  cup: 'Coppa',
  groups_knockout: 'Gironi + playoff',
  custom: 'Personalizzata',
};

const TYPE_LABEL: Record<string, string> = { round_robin: 'Campionato', knockout: 'Coppa' };

export function competitionFormatLabel(
  c: Pick<CompetitionItem, 'format' | 'competition_type'>
): string {
  if (c.format && c.format !== 'custom') return COMPETITION_FORMAT_LABEL[c.format] ?? c.format;
  if (c.format === 'custom') return COMPETITION_FORMAT_LABEL.custom;
  return TYPE_LABEL[c.competition_type] ?? c.competition_type;
}
