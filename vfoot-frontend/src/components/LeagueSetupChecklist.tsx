import clsx from 'clsx';
import type { CompetitionItem, LeagueDetail } from '../types/league';

/** What is still missing before a freshly created league can actually be played.
 *
 *  A league lands here the moment it is created, into a settings page that looks
 *  exactly like the one an established league uses — nothing said "you are still
 *  building this", and the order of the remaining steps was something the admin
 *  had to guess. Derived from data we already load rather than from a "created
 *  just now" flag, so it keeps being right if the admin walks away and comes back
 *  a week later, and disappears on its own once the league is ready.
 */
export default function LeagueSetupChecklist({
  league,
  competitions,
  onGoToInvite,
  onGoToCompetitions,
}: {
  league: LeagueDetail;
  competitions: CompetitionItem[];
  onGoToInvite?: () => void;
  onGoToCompetitions?: () => void;
}) {
  type Step = {
    done: boolean;
    label: string;
    hint: string;
    /** A step that cannot be started yet. Shown locked WITH the reason rather
     *  than hidden: a button that silently isn't there reads as a missing
     *  feature, and the admin is left guessing what unlocks it. */
    blocked?: boolean;
    blockedReason?: string;
    action?: () => void;
    actionLabel?: string;
  };

  const steps: Step[] = [
    {
      done: true,
      label: 'Lega creata',
      hint: `${league.name} · campionato di riferimento ${league.reference_season?.name ?? '—'}`,
    },
    {
      done: league.teams.length > 1,
      label: 'Invita i partecipanti',
      hint:
        league.teams.length > 1
          ? `${league.teams.length} squadre iscritte`
          : `Sei l'unica squadra. Passa il codice ${league.invite_code} a chi deve entrare.`,
      action: onGoToInvite,
      actionLabel: 'Codice invito',
    },
    {
      done: competitions.length > 0,
      // Not a convention, a real dependency: the calendar is generated from the
      // teams present AT GENERATION TIME (circle method in
      // services/competition_stages.py). Run it alone and the round robin pairs
      // your only team with a BYE, so the competition comes out with zero
      // fixtures — and you would have to know to rebuild it after people join.
      blocked: league.teams.length <= 1,
      blockedReason:
        'Prima invita i partecipanti: il calendario si genera dalle squadre presenti in quel momento, quindi creandola adesso resterebbe senza partite.',
      label: 'Crea la competizione',
      hint:
        competitions.length > 0
          ? competitions.map((c) => c.name).join(', ')
          : 'Campionato, coppa o entrambi: è qui che nasce il calendario.',
      action: onGoToCompetitions,
      actionLabel: 'Vai',
    },
  ];

  const remaining = steps.filter((s) => !s.done).length;
  // The first thing that can actually be done now — a locked step is not it.
  const next = steps.find((s) => !s.done && !s.blocked);
  // Nothing left to do => the league is up and running, and a checklist of ticks
  // would just be noise on a page used for everyday administration.
  if (!remaining) return null;

  return (
    <div className="mt-3 rounded-2xl border-l-4 border-sky-500 bg-sky-50 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-sm font-bold text-sky-900">🚧 Lega in costruzione</div>
        <div className="text-xs font-semibold text-sky-700">
          {steps.length - remaining} di {steps.length} completati
        </div>
      </div>
      <p className="mt-1 text-xs text-sky-800">
        Le impostazioni qui sotto sono già attive, ma la lega non è ancora giocabile.
        {next ? <> Il prossimo passo è <b>{next.label.toLowerCase()}</b>.</> : null}
      </p>

      <ol className="mt-3 space-y-2">
        {steps.map((s) => {
          const locked = !s.done && !!s.blocked;
          return (
            <li key={s.label} className="flex items-start gap-2">
              <span
                className={clsx(
                  'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold',
                  s.done
                    ? 'bg-emerald-500 text-white'
                    : locked
                      ? 'border-2 border-slate-200 bg-white text-slate-400'
                      : 'border-2 border-sky-300 bg-white text-sky-400',
                )}
                aria-hidden
              >
                {s.done ? '✓' : locked ? '🔒' : ''}
              </span>
              <div className="min-w-0 flex-1">
                <div
                  className={clsx(
                    'text-sm font-semibold',
                    s.done
                      ? 'text-slate-500 line-through decoration-slate-300'
                      : locked
                        ? 'text-slate-400'
                        : 'text-sky-900',
                  )}
                >
                  {s.label}
                </div>
                <div className={clsx('text-xs', locked ? 'text-slate-400' : 'text-slate-600')}>
                  {locked ? s.blockedReason : s.hint}
                </div>
              </div>
              {!s.done && !locked && s.action ? (
                <button
                  type="button"
                  onClick={s.action}
                  className="shrink-0 rounded-lg bg-sky-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-sky-500"
                >
                  {s.actionLabel}
                </button>
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
