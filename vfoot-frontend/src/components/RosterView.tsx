import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, SectionTitle, Badge } from './ui';
import { getLeagueDetail } from '../api';
import { useAuth } from '../auth/AuthContext';
import { useLeagueContext } from '../league/LeagueContext';
import type { LeagueTeam } from '../types/league';
import { CURRENCY_NAME_PLURAL, amount, price } from '../utils/currency';
import type { PlayerRole, MinutesLabel, TeamLineupContext, TeamLineupPlayer } from '../types/lineup';

// The structured roster: grouped by role, a spending summary, and a clickable
// detail per player. Shared between the manager's own Squad page and the
// read-only view of another participant's team, so both read identically.

const ROLE_LABEL: Record<PlayerRole, string> = { GK: 'POR', DEF: 'DIF', MID: 'CEN', ATT: 'ATT' };
const ROLE_NAME: Record<PlayerRole, string> = {
  GK: 'Portieri',
  DEF: 'Difensori',
  MID: 'Centrocampisti',
  ATT: 'Attaccanti',
};
const ROLE_CHIP: Record<PlayerRole, string> = {
  GK: 'bg-warn',
  DEF: 'bg-blue-500',
  MID: 'bg-good',
  ATT: 'bg-orange-500',
};
const ROLES: PlayerRole[] = ['GK', 'DEF', 'MID', 'ATT'];

/** «Fitz-Jim», «Fitz-Jim e Calò», «Fitz-Jim, Calò e Moreira»: l'elenco come si
 *  legge in una frase, che è l'unico posto dove serve. */
function namesOf(rows: { player_id: number; name: string | null }[]) {
  const names = rows.map((r) => r.name || 'un giocatore');
  if (names.length <= 1) return <b className="text-ink">{names[0] ?? ''}</b>;
  return (
    <b className="text-ink">
      {names.slice(0, -1).join(', ')} e {names[names.length - 1]}
    </b>
  );
}

export default function RosterView({ data }: { data: TeamLineupContext }) {
  const [openPlayer, setOpenPlayer] = useState<number | null>(null);
  const roster = [...data.roster].sort((a, b) => b.price - a.price);
  const budget = data.budget;
  // Solo sulla rosa POSSEDUTA: sulla pagina della formazione la differenza fra
  // le due rose e' gia' spiegata li', accanto ai giocatori che riguarda.
  const freeze = data.roster_scope === 'now' ? data.roster_freeze : null;
  const statsNote = data.stats_season
    ? data.stats_is_reference
      ? `Presenze, minuti e impiego sono aggiornati al campionato in corso (${data.stats_season}).`
      : `Il campionato non è ancora iniziato: presenze, minuti e impiego si riferiscono alla stagione ${data.stats_season}.`
    : null;

  return (
    <div className="space-y-4">
      <TeamSwitcher currentTeamId={data.team.team_id} ownTeamId={data.is_own ? data.team.team_id : null} />
      {budget ? (
        <Card className="p-4">
          <div className="grid grid-cols-3 gap-2">
            {/* La dote di partenza COMPRESO quel che l'admin ha dato dopo: e'
                lo stesso portafoglio, e mostrare i mille tondi accanto a un
                residuo che ne conta millecinquanta e' un conto che non torna. */}
            <Stat label="Budget" value={budget.initial + (budget.granted ?? 0) + (budget.trade_cash ?? 0)} />
            <Stat label="Speso" value={budget.spent} tone="rose" />
            <Stat label="Residuo" value={budget.remaining} tone="emerald" />
          </div>
          {budget.granted || budget.trade_cash ? (
            <div className="mt-1 text-[11px] text-ink-faint">
              Compresi{' '}
              {budget.granted ? <><b className="text-ink-soft">{price(budget.granted)}</b> dati dall’admin</> : null}
              {budget.granted && budget.trade_cash ? ' e ' : null}
              {budget.trade_cash ? <><b className="text-ink-soft">{price(budget.trade_cash)}</b> di conguagli da scambi</> : null}.
            </div>
          ) : null}
          {/* I tre numeri in alto non tornano da soli quando un contratto si e'
              chiuso in perdita: quei crediti non sono ne' spesi (chi li ha
              spesi non e' piu' in rosa) ne' residui. Detti qui, invece di
              lasciar fare la sottrazione a chi guarda e non torna. */}
          {budget.sunk ? (
            <div className="mt-1 text-[11px] text-ink-faint">
              <b className="text-ink-soft">{price(budget.sunk)}</b> persi in svincoli: pagati più di
              quanto è stato recuperato.
            </div>
          ) : null}
          {/* Il residuo e' quanto si possiede, il disponibile quanto si puo'
              ancora offrire. Finche' un'offerta e' aperta i due numeri sono
              diversi, ed e' lo stesso conto che fa la pagina Mercato. */}
          {budget.reserved ? (
            <div className="mt-1 text-[11px] text-ink-faint">
              Di cui <b className="text-ink-soft">{price(budget.reserved)}</b> impegnati in offerte
              aperte: puoi offrirne <b className="text-ink-soft">{price(budget.available)}</b>.
            </div>
          ) : null}
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink-faint">
            {ROLES.filter((r) => budget.by_role[r]).map((r) => (
              <span key={r}>
                {ROLE_NAME[r]}: <b className="text-ink-soft">{price(budget.by_role[r])}</b>
              </span>
            ))}
          </div>
        </Card>
      ) : null}

      {/* PERCHE' LA ROSA E LA FORMAZIONE NON COINCIDONO, per i giorni in cui non
          coincidono. A turno cominciato chi e' stato ceduto resta schierabile
          fino alla fine del turno e chi e' stato comprato entra dal successivo
          (R4): senza questa riga la pagina mostra l'effetto — un giocatore che
          non c'e' piu' ancora in campo, uno appena preso che non si puo'
          schierare — e tace la causa. */}
      {freeze && (freeze.leaving.length > 0 || freeze.arriving.length > 0) ? (
        <Card className="p-4 text-[13px] text-ink-soft">
          <b>Giornata {freeze.matchday} già cominciata.</b> Qui sotto c’è la rosa di adesso.{' '}
          {freeze.leaving.length ? (
            <>
              {namesOf(freeze.leaving)} {freeze.leaving.length > 1 ? 'sono stati ceduti' : 'è stato ceduto'}{' '}
              a turno iniziato e {freeze.leaving.length > 1 ? 'restano schierabili' : 'resta schierabile'}{' '}
              in questa giornata.{' '}
            </>
          ) : null}
          {freeze.arriving.length ? (
            <>
              {namesOf(freeze.arriving)} {freeze.arriving.length > 1 ? 'entrano' : 'entra'} dalla
              prossima giornata.
            </>
          ) : null}
        </Card>
      ) : null}

      {ROLES.map((role) => {
        const group = roster.filter((p) => p.role === role);
        if (!group.length) return null;
        return (
          <Card key={role} className="p-4">
            <div className="flex items-baseline justify-between">
              <SectionTitle>{ROLE_NAME[role]}</SectionTitle>
              <span className="text-xs text-ink-faint">
                {group.length} · {amount(group.reduce((s, p) => s + p.price, 0))}
              </span>
            </div>
            {/* L'intestazione delle colonne. Mancava, e il prezzo era una cifra
                senza nome in mezzo alla riga: qui la colonna dice di che moneta
                si parla una volta sola, in cima, invece di ripetere la parola
                venticinque volte. Stesse larghezze della riga (w-20 / w-28), o
                le etichette non starebbero sopra la loro colonna. */}
            <div className="mt-2 flex items-center justify-between gap-3 border-b pb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
              <span className="min-w-0">Giocatore</span>
              <span className="flex shrink-0 items-center gap-2">
                <span className="w-20 text-right normal-case tracking-normal">{CURRENCY_NAME_PLURAL}</span>
                <span className="hidden w-28 text-right sm:block">Impiego</span>
              </span>
            </div>
            <div className="divide-y">
              {group.map((p) => (
                <PlayerRow
                  key={p.player_id}
                  p={p}
                  open={openPlayer === p.player_id}
                  onToggle={() => setOpenPlayer((cur) => (cur === p.player_id ? null : p.player_id))}
                />
              ))}
            </div>
          </Card>
        );
      })}

      {statsNote ? <div className="px-1 text-[11px] text-ink-faint">{statsNote}</div> : null}
    </div>
  );
}

/** A scrollable strip of every participant, so the rosters can be browsed one from
 *  another without going back to the League page — the manager's own team routes to
 *  /squad, the others to /teams/:id. Answers the ask for tab/swipe navigation. */
function TeamSwitcher({ currentTeamId }: { currentTeamId: number; ownTeamId: number | null }) {
  const { selectedLeagueId } = useLeagueContext();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [teams, setTeams] = useState<LeagueTeam[]>([]);

  useEffect(() => {
    if (!selectedLeagueId) return;
    let alive = true;
    void getLeagueDetail(selectedLeagueId)
      .then((d) => alive && setTeams(d.teams))
      .catch(() => setTeams([]));
    return () => {
      alive = false;
    };
  }, [selectedLeagueId]);

  // Which chip routes to /squad: the team the current user manages.
  const ownId = teams.find((t) => t.manager_user_id === user?.id)?.team_id ?? null;

  if (teams.length < 2) return null;
  return (
    <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
      {teams.map((t) => {
        const active = t.team_id === currentTeamId;
        const own = t.team_id === ownId;
        const dest = own ? '/squad' : `/teams/${t.team_id}`;
        return (
          <button
            key={t.team_id}
            onClick={() => navigate(dest)}
            title={own ? 'La tua squadra' : undefined}
            className={`flex shrink-0 items-center gap-1 rounded-full px-3 py-1 text-xs font-semibold ${
              active
                ? 'bg-ink text-paper'
                : own
                  // Marked even when it is not the one on screen: in a strip of
                  // eight unfamiliar names, yours should not have to be recalled.
                  ? 'bg-good-bg text-good ring-1 ring-good/40 hover:bg-good-bg'
                  : 'bg-surface-2 text-ink-soft hover:bg-surface-2'
            }`}
          >
            {/* No crest here on purpose. The strip is a way to move between
                rosters, not to look at them: badges made every chip taller for no
                information the name does not already carry, and having the crest
                in two places at once invited them to disagree. */}
            {own ? <span aria-hidden>★</span> : null}
            {t.name}
          </button>
        );
      })}
    </div>
  );
}

function Stat({ label, value, tone = 'slate' }: { label: string; value: number; tone?: 'slate' | 'rose' | 'emerald' }) {
  const color = tone === 'rose' ? 'text-bad' : tone === 'emerald' ? 'text-good' : 'text-ink';
  return (
    <div className="rounded-xl bg-surface-2 px-3 py-2 text-center">
      <div className="text-[10px] uppercase tracking-wide text-ink-faint">{label}</div>
      {/* Anche qui la moneta: erano tre numeri nudi sopra una colonna che
          adesso dice «vfooties», e la domanda «vfooties anche questi?» non deve
          nascere. */}
      <div className={`text-lg font-bold tabular-nums ${color}`}>{price(value)}</div>
    </div>
  );
}

function PlayerRow({ p, open, onToggle }: { p: TeamLineupPlayer; open: boolean; onToggle: () => void }) {
  return (
    <div className="py-2.5">
      <button type="button" onClick={onToggle} className="flex w-full items-center justify-between gap-3 text-left">
        <div className="flex min-w-0 items-center gap-2">
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ${ROLE_CHIP[p.role]}`}>
            {ROLE_LABEL[p.role]}
          </span>
          <div className="min-w-0">
            <div className="truncate font-semibold text-ink">{p.name}</div>
            <div className="truncate text-xs text-ink-faint">{p.real_team ?? '—'}</div>
          </div>
        </div>
        {/* Fixed columns: the price sits in its own right-aligned slot so a missing
            usage badge (a newcomer with no history) never shifts it out of line. */}
        <div className="flex shrink-0 items-center gap-2">
          <span className="w-20 text-right font-mono text-sm font-bold tabular-nums text-ink-soft">{price(p.price)}</span>
          <span className="hidden w-28 text-right sm:block">
            <MinutesBadge label={p.minutes_label} />
          </span>
        </div>
      </button>
      {open ? <PlayerDetail p={p} /> : null}
    </div>
  );
}

/** What we actually know about a player, made explicit rather than crammed into a
 *  cryptic "36 pres · 2.5 medi". The key clarification: "presenze" counts every
 *  call-up (bench included), which is why a reserve reads many appearances and
 *  almost no minutes — so starts are shown separately. */
function PlayerDetail({ p }: { p: TeamLineupPlayer }) {
  const vote = p.value != null ? p.value.toFixed(2) : null;
  return (
    <div className="mt-2 rounded-xl bg-surface-2 px-3 py-2 text-[12px]">
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
        <Field label="Squadra" value={p.real_team ?? '—'} />
        <Field
          label="Da titolare"
          value={p.starts != null ? `${p.starts} su ${p.appearances} conv.` : `${p.appearances} conv.`}
        />
        <Field label="Minuti medi" value={`${p.avg_minutes}′`} />
        <Field label="Media voto" value={vote ?? '—'} hint={p.value_basis === 'estimate' ? 'stimata' : undefined} />
      </div>
      {p.next_match ? (
        <div className="mt-1.5 text-[11px] text-ink-faint">
          Prossima: {p.next_match.home ? 'in casa contro' : 'in trasferta contro'}{' '}
          <b className="text-ink-soft">{p.next_match.opponent}</b>
        </div>
      ) : null}
      {/* Che cosa vuol dire l'etichetta di QUESTO giocatore, per esteso. Sul
          badge sta come titolo, ma un titolo lo vede solo chi ha un mouse e chi
          sa che c'è: su un telefono non esiste. Qui la frase sta accanto ai
          numeri da cui è ricavata — presenze e minuti medi — e si legge come la
          loro conclusione. */}
      {p.minutes_label !== 'unknown' ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-line pt-1.5 text-[11px] text-ink-faint">
          <MinutesBadge label={p.minutes_label} />
          <span className="font-semibold text-ink-soft">{MINUTES_MEANING[p.minutes_label]}</span>
          <span>{recentUsage(p)}</span>
        </div>
      ) : null}
    </div>
  );
}

function Field({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-ink-faint">{label}</div>
      <div className="font-semibold text-ink-soft">
        {value}
        {hint ? <span className="ml-1 text-[10px] font-normal text-ink-faint">({hint})</span> : null}
      </div>
    </div>
  );
}

/** Che cosa promette ciascun tag. Una frase, al presente, su cosa aspettarsi.
 *
 *  Non una regola: la regola («almeno il 60% delle giornate e 60 minuti medi»)
 *  spiega come il numero è stato calcolato, e chi guarda una rosa non sta
 *  chiedendo quello — sta chiedendo se schierarlo. I numeri veri li mostra la
 *  riga sotto, che è la prova; questa è la conclusione. */
const MINUTES_MEANING: Record<Exclude<MinutesLabel, 'unknown'>, string> = {
  high: 'Gioca quasi sempre, e gioca tutta la partita.',
  medium: 'Gioca spesso, ma non è detto che parta titolare.',
  low: 'Gioca poco: rischio alto di ritrovarlo senza voto.',
};

/** La prova, coi numeri di QUESTO giocatore: «4 volte su 6, 71′ di media».
 *
 *  È il motivo per cui il tag ha cambiato base. Prima leggeva l'intera stagione e
 *  a marzo un titolare fermo da due mesi restava «titolare abituale», perché le
 *  ventidue partite di prima pesavano più delle ultime otto. Ora guarda le ultime
 *  giornate, e siccome è una finestra breve conviene dire quale: senza, «gioca
 *  quasi sempre» su un giocatore che quest'anno ha saltato mezzo campionato
 *  sembra un errore. */
function recentUsage(p: TeamLineupPlayer): string | null {
  if (!p.recent_window) return null;
  const giornate = p.recent_window === 1 ? 'giornata' : 'giornate';
  // Mai in campo si dice così e non «in campo 0 volte»: è la frase più
  // importante che questa riga possa contenere e non deve suonare come un conto.
  if (!p.recent_appearances) return `Ultime ${p.recent_window} ${giornate}: mai in campo.`;
  const volte = p.recent_appearances === 1 ? 'una volta' : `${p.recent_appearances} volte`;
  return `Ultime ${p.recent_window} ${giornate}: in campo ${volte}, ${Math.round(
    p.recent_avg_minutes,
  )}′ di media.`;
}

function MinutesBadge({ label }: { label: MinutesLabel }) {
  // 'unknown' = niente da cui giudicare (preseason, o mai convocato nella
  // finestra): tacere, invece di dare del panchinaro a chi non si conosce.
  if (label === 'unknown') return null;
  const meaning = MINUTES_MEANING[label];
  if (label === 'high') return <Badge tone="green" title={meaning}>titolare abituale</Badge>;
  if (label === 'medium') return <Badge tone="slate" title={meaning}>spesso in campo</Badge>;
  return <Badge tone="amber" title={meaning}>poco impiegato</Badge>;
}
