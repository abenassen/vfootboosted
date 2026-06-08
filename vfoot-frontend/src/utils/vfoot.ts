// Shared, data-source-neutral helpers used by both the simulation views and
// (in a later phase) the real DB-backed league views.

// StatsBomb event-feature keys -> short human labels. The real-league vector
// contract uses the same feature keys, so this map is reused as-is.
const FEATURE_LABELS: Record<string, string> = {
  xg_shots: 'xG',
  shots: 'Tiri',
  touches_in_box: 'Tocchi in area',
  key_passes: 'Passaggi chiave',
  passes_into_box: 'Passaggi in area',
  progressive_passes_completed: 'Passaggi progressivi',
  progressive_carries: 'Conduzioni progressive',
  ball_recoveries: 'Recuperi',
  interceptions: 'Intercetti',
  pressures: 'Pressioni',
  clearances: 'Spazzate',
  errors_bad_passes: 'Errori passaggio',
  errors_dispossessed: 'Palle perse',
  errors_fouls_committed: 'Falli',
  errors_miscontrols: 'Stop sbagliati',
};

export function featureLabel(key: string): string {
  return FEATURE_LABELS[key] ?? key.replace(/_/g, ' ');
}

// Seconds -> compact minute label, e.g. 5400 -> "90'".
export function toMinutes(seconds: number | undefined | null): string {
  if (seconds == null || Number.isNaN(seconds)) return "0'";
  return `${Math.round(seconds / 60)}'`;
}

// "Z_<col>_<row>" -> { col, row }. Returns null when the key is not a zone key.
export function parseZoneKey(zoneKey: string): { col: number; row: number } | null {
  const m = /^Z_(\d+)_(\d+)$/.exec(zoneKey);
  if (!m) return null;
  return { col: Number(m[1]), row: Number(m[2]) };
}
