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
 *
 *  LO LEGGONO IN DUE, e non vogliono dire la stessa cosa. Per l'amministratore è
 *  una lista di cose da fare, coi bottoni per farle. Per chiunque altro è il
 *  motivo per cui la lega è ancora vuota, e i bottoni erano un imbroglio: si
 *  vedevano, sembravano premibili, e portavano a una pagina che rispondeva «serve
 *  il ruolo admin». Da lì in poi la lista dice CHI se ne occupa e non offre
 *  niente da premere.
 */
export default function LeagueSetupChecklist({
  league,
  competitions,
  /** Chi guarda può agire, cioè è amministratore di questa lega. */
  canAct = true,
  onGoToInvite,
  onGoToCompetitions,
  onGoToRoster,
}: {
  league: LeagueDetail;
  competitions: CompetitionItem[];
  canAct?: boolean;
  onGoToInvite?: () => void;
  onGoToCompetitions?: () => void;
  onGoToRoster?: () => void;
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

  const enoughTeams = league.teams.length > 1;
  // Una rosa fatta è una rosa con dei giocatori dentro. Non si pretende che siano
  // tutte piene — un'asta finisce spesso con qualche casella libera, e il mercato
  // serve a quello — ma una lega in cui NESSUNO ha un giocatore non ha ancora
  // fatto l'asta, ed è la sola cosa che qui si vuole distinguere.
  const withRoster = league.teams.filter((t) => (t.roster_count ?? 0) > 0).length;
  const rosterDone = league.teams.length > 0 && withRoster === league.teams.length;

  const steps: Step[] = [
    {
      done: true,
      label: 'Lega creata',
      hint: `${league.name} · campionato di riferimento ${league.reference_season?.name ?? '—'}`,
    },
    {
      done: enoughTeams,
      label: 'Invita i partecipanti',
      hint: enoughTeams
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
      blocked: !enoughTeams,
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
    {
      // LE ROSE, che mancavano da questa lista pur essendo la ragione più comune
      // per cui una lega appena creata non si può giocare: c'è il calendario,
      // c'è la classifica a zero, e alla prima giornata non si schiera nessuno
      // perché nessuno ha giocatori. Chi guarda dà per fatto tutto quello che la
      // lista non nomina, e questo non era nominato da nessuna parte.
      done: rosterDone,
      blocked: !enoughTeams,
      blockedReason:
        "Prima invita i partecipanti: all'asta si presentano le squadre iscritte in quel momento.",
      label: 'Fai le rose',
      hint: rosterDone
        ? `${league.teams.length} rose formate`
        : withRoster > 0
          ? `${withRoster} rose su ${league.teams.length}: ne mancano ${league.teams.length - withRoster}.`
          : league.mode === 'classic'
            ? "Nessuna squadra ha giocatori. Si riempiono con l'asta — oppure caricando le rose da un foglio."
            : 'Nessuna squadra ha giocatori: senza, alla prima giornata non si schiera nessuno.',
      action: onGoToRoster,
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
    <div className="mt-3 rounded-2xl border-l-4 border-accent bg-accent/10 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-sm font-bold text-accent">🚧 Lega in costruzione</div>
        <div className="text-xs font-semibold text-accent">
          {steps.length - remaining} di {steps.length} completati
        </div>
      </div>
      <p className="mt-1 text-xs text-accent">
        Le impostazioni qui sotto sono già attive, ma la lega non è ancora giocabile.
        {canAct ? (
          next ? (
            <>
              {' '}
              Il prossimo passo è <b>{next.label.toLowerCase()}</b>.
            </>
          ) : null
        ) : (
          // Non «cosa devi fare» ma «cosa si sta aspettando»: chi legge questa
          // versione non può muovere niente, e sapere di chi è il turno è
          // l'unica informazione che gli serve davvero.
          <> Se ne occupa l’amministratore della lega: qui sotto cosa manca ancora.</>
        )}
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
                    ? 'bg-good text-white'
                    : locked
                      ? 'border-2 border-line bg-surface text-ink-faint'
                      : 'border-2 border-accent/40 bg-surface text-accent',
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
                      ? 'text-ink-faint line-through decoration-ink-faint'
                      : locked
                        ? 'text-ink-faint'
                        : 'text-accent',
                  )}
                >
                  {s.label}
                </div>
                <div className={clsx('text-xs', locked ? 'text-ink-faint' : 'text-ink-soft')}>
                  {locked ? s.blockedReason : s.hint}
                </div>
              </div>
              {canAct && !s.done && !locked && s.action ? (
                <button
                  type="button"
                  onClick={s.action}
                  className="shrink-0 rounded-lg bg-accent px-2.5 py-1 text-xs font-semibold text-white hover:bg-accent"
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
