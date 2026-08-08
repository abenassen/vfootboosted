import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCompetitionPrizes, getCompetitionStructure } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { useCompetitionContext, useCompetitionFromQuery } from '../league/CompetitionContext';
import { Badge, Card, SectionTitle } from '../components/ui';
import { StandingsTable, type StandingRowVM } from '../components/league/StandingsTable';
import type {
  CompetitionPrizeItem,
  CompetitionSection,
  CompetitionStructure,
  LeagueFixtureItem,
  LeagueStandingRow,
} from '../types/league';

const VIEW_TITLE: Record<string, string> = { classifica: 'Classifica', tabellone: 'Tabellone', risultati: 'Risultati' };

/** Perché è passato, quando il risultato da solo non lo spiega.
 *
 *  UN GRADINO PER VOLTA, e solo quello che ha deciso QUESTA sfida. La catena
 *  completa è gol → punteggi → rigori → squadra di casa (services/knockout), ma
 *  scriverla tutta sopra il tabellone raccontava tre regole inapplicate per ogni
 *  regola applicata: chi passa ai punteggi non ha battuto rigori, e sentirseli
 *  nominare fa sospettare che siano stati saltati. Ogni frase dice quindi cosa
 *  era pari (il gradino sopra, quello che NON ha deciso) e cosa ha deciso.
 *
 *  Chi ha semplicemente segnato di più non compare affatto: quello si legge dal
 *  risultato, che è stampato lì sopra. */
const ADVANCED_REASON: Record<string, string> = {
  punteggio: 'gol pari: passa il punteggio più alto',
  rigori: 'gol e punteggi pari: passa ai rigori',
  'fattore campo': 'gol, punteggi e rigori pari: passa la squadra di casa',
};

// Stage-aware results: renders a competition's SECTIONS newest-first — a standings
// table for each round-robin (group) stage and a bracket for each knockout stage. So
// a group+KO cup opens on the bracket and keeps the group tables underneath, which is
// the order the question comes in: com'è finita, e poi da dove veniva. Follows the
// switcher (and `?competition=`, see useCompetitionFromQuery).
export default function ClassificaPage() {
  const { selectedLeagueId, selectedLeague } = useLeagueContext();
  const { selectedCompetitionId } = useCompetitionContext();
  // Arrivare qui DA una competizione la seleziona: vedi useCompetitionFromQuery.
  useCompetitionFromQuery();
  const [structure, setStructure] = useState<CompetitionStructure | null>(null);
  const [prizes, setPrizes] = useState<CompetitionPrizeItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selectedLeagueId || !selectedCompetitionId) {
      setStructure(null);
      return;
    }
    setLoading(true);
    void getCompetitionStructure(selectedLeagueId, selectedCompetitionId)
      .then(setStructure)
      .catch(() => setStructure(null))
      .finally(() => setLoading(false));
  }, [selectedLeagueId, selectedCompetitionId]);

  useEffect(() => {
    if (!selectedCompetitionId) {
      setPrizes([]);
      return;
    }
    let alive = true;
    void getCompetitionPrizes(selectedCompetitionId)
      .then((p) => alive && setPrizes(p))
      .catch(() => alive && setPrizes([]));
    return () => {
      alive = false;
    };
  }, [selectedCompetitionId]);

  if (!selectedLeagueId) return <div className="text-sm text-ink-faint">Seleziona una lega.</div>;
  if (!selectedCompetitionId)
    return <div className="text-sm text-ink-faint">Questa lega non ha ancora competizioni.</div>;
  if (loading || !structure) return <div className="text-sm text-ink-faint">Caricamento…</div>;

  // DALL'ULTIMA FASE ALLA PRIMA. Le fasi erano disegnate nell'ordine in cui si
  // giocano — gironi, poi tabellone — che è l'ordine giusto per progettare una
  // competizione e quello sbagliato per LEGGERLA: chi apre i risultati vuole
  // sapere com'è finita, e trovava in cima i gironi di novembre con la finale in
  // fondo alla pagina. Un campionato ha una fase sola e non cambia di niente.
  //
  // Le fasi PARALLELE (i due gironi, che si giocano insieme) condividono l'ordine
  // e restano affiancate: invertirle fra loro non vorrebbe dire niente, perché
  // fra Girone A e Girone B non c'è un prima e un dopo.
  const phases = groupByOrder(structure.sections);
  const anyBracket = structure.sections.some((s) => s.type === 'knockout');

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-center gap-2">
          <SectionTitle>{VIEW_TITLE[structure.result_view] ?? 'Risultati'}</SectionTitle>
          <Badge tone="blue">{structure.name}</Badge>
        </div>
        {structure.result_view === 'risultati' ? (
          <div className="mt-1 text-[11px] text-ink-faint">
            Dall'ultima fase giocata alla prima: il tabellone, e sotto i gironi da cui è uscito.
          </div>
        ) : null}
      </Card>

      {/* What is at stake, and who has already taken it. Above the table because
          a prize is the reason the table matters; a prize nobody has won yet is
          still worth reading — it says what the season is being played for. */}
      {prizes.length ? (
        <Card className="p-4">
          <SectionTitle>Premi</SectionTitle>
          <ul className="mt-2 grid gap-2 sm:grid-cols-2">
            {prizes.map((p) => (
              <li
                key={p.prize_id}
                className={
                  'flex items-start gap-2 rounded-xl border px-3 py-2 ' +
                  (p.winner_team_names.length
                    ? 'border-warn/40 bg-warn-bg/60'
                    : 'border-line border-dashed')
                }
              >
                <span className="text-xl leading-none" aria-hidden>
                  {p.icon}
                </span>
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-ink">{p.name}</div>
                  <div className="truncate text-[11px] text-ink-faint">{p.condition_label}</div>
                  <div
                    className={
                      'truncate text-[11px] font-semibold ' +
                      (p.winner_team_names.length ? 'text-warn' : 'text-ink-faint')
                    }
                  >
                    {p.winner_team_names.length ? p.winner_team_names.join(', ') : 'ancora da assegnare'}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {phases.map((group) =>
        group[0].type === 'round_robin' ? (
          // I gironi che si giocano insieme, affiancati.
          <div key={group[0].order} className={group.length > 1 ? 'grid gap-4 lg:grid-cols-2' : ''}>
            {group.map((s) => (
              <Card key={s.name} className="p-4">
                {group.length > 1 || anyBracket ? <SectionTitle>{s.name}</SectionTitle> : null}
                <div className={group.length > 1 || anyBracket ? 'mt-2' : ''}>
                  <StandingsTable
                    rows={rows(s.standings ?? [], selectedLeague?.team_name)}
                    prizeRanks={s.prize_ranks}
                    qualifyRanks={s.qualify_ranks}
                  />
                </div>
              </Card>
            ))}
          </div>
        ) : (
          group.map((s) => <Bracket key={s.name} section={s} />)
        ),
      )}
    </div>
  );
}

/** Le fasi dalla più recente alla più antica, tenendo insieme quelle parallele.
 *
 *  Un `order` condiviso vuol dire "si giocano insieme" — i due gironi — e quelle
 *  restano un gruppo, nel loro ordine naturale: Girone A prima di Girone B non è
 *  una cronologia ed è già l'unico modo sensato di leggerle. */
function groupByOrder(sections: CompetitionSection[]): CompetitionSection[][] {
  const groups: CompetitionSection[][] = [];
  for (const s of [...sections].sort((a, b) => a.order - b.order)) {
    const last = groups[groups.length - 1];
    if (last && last[0].order === s.order) last.push(s);
    else groups.push([s]);
  }
  return groups.reverse();
}

function rows(s: LeagueStandingRow[], myTeam?: string | null): StandingRowVM[] {
  return s.map((r) => ({
    key: String(r.team_id),
    rank: r.rank,
    name: r.team,
    // ?? '' and not `r.crest`: undefined means "this caller has no crests at all"
    // and switches the column off for the whole table.
    crest: r.crest ?? '',
    played: r.played,
    wins: r.wins,
    draws: r.draws,
    losses: r.losses,
    goalsFor: r.goals_for,
    goalsAgainst: r.goals_against,
    goalDiff: r.goal_diff,
    points: r.points,
    avgScore: r.avg_score_for,
    provisional: r.provisional,
    highlight: myTeam ? r.team === myTeam : false,
  }));
}

function Bracket({ section }: { section: CompetitionSection }) {
  // Anche qui dal più recente: una fase può tenere dentro più turni ("Fase
  // finale" = semifinali E finale), e non avrebbe senso invertire le fasi fra
  // loro e lasciare la finale in coda dentro la sua.
  const rounds = [...(section.rounds ?? [])].sort((a, b) => b.round_no - a.round_no);
  if (!rounds.length) return null;
  // A phase that holds exactly its own round says its name twice — "Finale" over
  // "Finale" — which is how a cup built one phase per round (the shape the wizard
  // makes) came out. One of the two is enough.
  const sameName = rounds.length === 1 && rounds[0].label === section.name;
  return (
    <Card className="p-4">
      <SectionTitle>{section.name}</SectionTitle>
      <div className="mt-2 grid gap-4 md:grid-cols-3">
        {rounds.map((r) => (
          <div key={r.round_no}>
            {sameName ? null : (
              <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">{r.label}</div>
            )}
            <div className="mt-2 space-y-2">
              {r.fixtures.map((f) => (
                <BracketMatch key={f.fixture_id} f={f} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function BracketMatch({ f }: { f: LeagueFixtureItem }) {
  const hs = f.score?.home_total ?? 0;
  const as = f.score?.away_total ?? 0;
  const done = f.status === 'finished' && f.score;
  // Chi passa lo dice il server: su un 1-1 il risultato non basta, e in un
  // tabellone la domanda è sempre "e adesso chi va avanti".
  const through = f.advanced_team_id ?? null;
  const homeWin = through !== null ? through === f.home_team.team_id : !!done && hs > as;
  const awayWin = through !== null ? through === f.away_team.team_id : !!done && as > hs;
  return (
    <Link to={`/matches/${f.fixture_id}`} className="block rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm hover:opacity-80">
      <div className="flex items-center justify-between">
        <span className={homeWin ? 'font-bold text-ink' : 'text-ink-soft'}>{f.home_team.name}</span>
        <span className="font-mono text-xs font-bold">{done ? Math.round(hs) : '–'}</span>
      </div>
      <div className="flex items-center justify-between">
        <span className={awayWin ? 'font-bold text-ink' : 'text-ink-soft'}>{f.away_team.name}</span>
        <span className="font-mono text-xs font-bold">{done ? Math.round(as) : '–'}</span>
      </div>
      {/* Non più maiuscoletto: una frase che spiega una regola si legge, una
          targhetta di due parole si guardava. */}
      {f.advanced_reason ? (
        <div className="mt-1 text-[10px] leading-snug text-ink-faint">
          {ADVANCED_REASON[f.advanced_reason] ?? `passa: ${f.advanced_reason}`}
          {f.shootout ? ` ${f.shootout.home_goals}-${f.shootout.away_goals}` : ''}
          {/* IL NUMERO che ha deciso, non solo il suo nome. «Passa ai punteggi»
              su un 1-1 è un verdetto senza prova: i punteggi sono i fantavoto
              delle due formazioni, stanno da un'altra parte rispetto ai gol
              stampati qui sopra, e senza vederli non c'è modo di sapere se il
              risultato è quello giusto — che è esattamente la domanda che uno si
              fa quando la sua squadra esce da una finale pari. */}
          {f.advanced_reason === 'punteggio' && f.totals
            ? ` ${f.totals.home.toFixed(1)}–${f.totals.away.toFixed(1)}`
            : ''}
        </div>
      ) : null}
      {/* I tiri, in fila: verde chi ha segnato. Cinque pallini non appesantiscono
          il tabellone e raccontano tutta la serie. */}
      {f.shootout ? (
        <div className="mt-1 space-y-0.5">
          {(['home', 'away'] as const).map((side) => (
            <div key={side} className="flex items-center gap-1" title={f.shootout![side].map((k) => k.name).join(' · ')}>
              {f.shootout![side].map((k, i) => (
                <span
                  key={i}
                  aria-label={`${k.name}: ${k.scored ? 'gol' : 'sbagliato'}`}
                  className={
                    'inline-block h-1.5 w-1.5 rounded-full ' + (k.scored ? 'bg-good' : 'bg-ink-faint/50')
                  }
                />
              ))}
            </div>
          ))}
        </div>
      ) : null}
    </Link>
  );
}
