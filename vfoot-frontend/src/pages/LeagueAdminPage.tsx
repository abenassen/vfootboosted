import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  addRosterPlayer,
  concludeLeagueMatchday,
  recomputeLeagueMatchday,
  setLeagueMatchdayAwaiting,
  createLeague,
  getCompetitions,
  getLeagueDetail,
  getLeagueMatchdays,
  getRealSeasons,
  getTeamRoster,
  importRosterCsv,
  importRosterXlsx,
  joinLeague,
  searchPlayers,
  sellRosterPlayer,
  voidRosterSlot,
  updateLeagueSettings,
  updateMemberRole,
} from '../api';
import {
  ApiError,
  getMatchdayOfficeVotes,
  setMatchdayOfficeVotes,
  type LeagueSettingsPatch,
  type OfficeVoteMatch,
} from '../api/backend';
import { useAuth } from '../auth/AuthContext';
import { CURRENCY_SYMBOL, amount, price } from '../utils/currency';
import { ROLE_ORDER } from '../utils/market';
import type { PrizeChange, RecomputeResult } from '../api/backend';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import InviteShare from '../components/InviteShare';
import MarketAdminPanel from '../components/MarketAdminPanel';
import LeagueSetupChecklist from '../components/LeagueSetupChecklist';
import Crest from '../components/Crest';
import { competitionFormatLabel } from '../league/competitionFormat';
import type {
  ClassicRole,
  CompetitionItem,
  LeagueDetail,
  LeagueMatchdayItem,
  PlayerSearchItem,
  RealSeasonItem,
  TeamRoster,
} from '../types/league';

type AdminTab = 'user' | 'league';
type LeagueTab = 'roster' | 'competitions' | 'matchdays' | 'auction' | 'market';

export default function LeagueAdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { user } = useAuth();
  const { leagues, selectedLeagueId, selectedLeague, setSelectedLeagueId, refreshLeagues } = useLeagueContext();
  const isAdmin = selectedLeague?.role === 'admin';

  const [activeTab, setActiveTab] = useState<AdminTab>('user');
  // L'id da portare in vista appena esiste: vedi l'effetto poco sotto.
  const [pendingReveal, setPendingReveal] = useState<string | null>(null);
  const [leagueTab, setLeagueTab] = useState<LeagueTab>('competitions');

  const [league, setLeague] = useState<LeagueDetail | null>(null);
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);
  const [roster, setRoster] = useState<TeamRoster | null>(null);
  // Match options are edited as a DRAFT and written only on "Salva". They used to
  // save on every change: one stray tap on a checkbox rewrote a rule that decides
  // how votes are counted, with no way back and nothing asking for confirmation.
  const [optionsDraft, setOptionsDraft] = useState<LeagueSettingsPatch | null>(null);
  const [createName, setCreateName] = useState('');
  const [createTeam, setCreateTeam] = useState('');
  // Reference season is mandatory at creation and immutable afterwards.
  const [createSeasonId, setCreateSeasonId] = useState<number | ''>('');
  // Same deal for the mode, and the form never asked: every league created from
  // the UI took the server default ('aura'), so the classic fantacalcio — listone,
  // asta, ruoli, vincoli di formazione — was unreachable from the interface.
  const [createMode, setCreateMode] = useState<'classic' | 'aura'>('classic');
  const [realSeasons, setRealSeasons] = useState<RealSeasonItem[]>([]);
  // L'invito della lega appena creata, mostrato finché non lo si chiude. Col nome
  // accanto al codice: serve a comporre il messaggio che si manda agli altri, e
  // il campo del modulo a quel punto è già stato svuotato.
  const [createdInvite, setCreatedInvite] = useState<{ code: string; name: string } | null>(null);
  const [joinCode, setJoinCode] = useState('');
  const [joinTeam, setJoinTeam] = useState('');

  const [playerQuery, setPlayerQuery] = useState('');
  const [playerResults, setPlayerResults] = useState<PlayerSearchItem[]>([]);
  const [selectedPlayer, setSelectedPlayer] = useState<PlayerSearchItem | null>(null);
  const [manualPrice, setManualPrice] = useState('1');
  // Scavalca il controllo di legalita' sull'acquisto. Non e' un'impostazione:
  // si accende per un acquisto e si spegne da sola appena e' andato a buon fine.
  const [forceBuy, setForceBuy] = useState(false);
  // Perche' l'acquisto e' stato rifiutato, tenuto qui e non letto dal banner in
  // cima alla pagina: quello indovina il proprio tono dal testo del messaggio
  // (vedi l'effetto poco sotto), quindi un rifiuto che non contiene la parola
  // "errore" gli risulta un'informazione — e comunque sta fuori schermo, mentre
  // la ragione serve accanto al campo dove si e' appena scritto il prezzo.
  const [buyRefusal, setBuyRefusal] = useState<string | null>(null);
  // Quale contratto si sta chiudendo o cancellando, e a quanto. Uno per volta,
  // e la conferma sta nella riga: un window.confirm qui bloccherebbe la pagina e
  // direbbe comunque meno di quanto dice la frase che si legge sotto il nome.
  const [sellFor, setSellFor] = useState<number | null>(null);
  const [sellPrice, setSellPrice] = useState('');
  const [voidFor, setVoidFor] = useState<number | null>(null);

  const [csvText, setCsvText] = useState('team_name,manager_username,player_id,price\n');
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [rosterXlsxFile, setRosterXlsxFile] = useState<File | null>(null);


  const [competitions, setCompetitions] = useState<CompetitionItem[]>([]);
  const [matchdays, setMatchdays] = useState<LeagueMatchdayItem[]>([]);

  const [msg, setMsg] = useState<string>('');
  const [msgTone, setMsgTone] = useState<'info' | 'success' | 'warning' | 'error'>('info');
  const [busy, setBusy] = useState(false);
  // When concluding a classic matchday hits teams with no lineup, we prompt the admin
  // to pick forfait/previous per team, then re-conclude with those resolutions.
  const [lineupPrompt, setLineupPrompt] = useState<{
    md: LeagueMatchdayItem;
    kind: 'conclude' | 'recompute';
    use?: 'current' | 'snapshot';
    teams: Array<{ team_id: number; name: string; has_previous_lineup: boolean; previous_lineup_stale: number }>;
    resolutions: Record<number, 'forfait' | 'previous'>;
  } | null>(null);
  // The office-vote panel for one matchday: the matches with no final data, and the
  // ruling the admin is about to impose on the ones he ticks.
  const [officePanel, setOfficePanel] = useState<{
    md: LeagueMatchdayItem;
    matches: OfficeVoteMatch[];
    picked: Record<number, boolean>;
    voto: string;
  } | null>(null);

  const selectedTeamName = useMemo(
    () => league?.teams.find((t) => t.team_id === selectedTeamId)?.name ?? '',
    [league, selectedTeamId]
  );
  /** The saved values, i.e. what "Annulla" goes back to and what "dirty" is
   *  measured against. */
  function optionsOf(d: LeagueDetail): LeagueSettingsPatch {
    return {
      max_substitutions: d.max_substitutions,
      defense_bonus_enabled: d.defense_bonus_enabled,
      defense_bonus_mode: d.defense_bonus_mode,
      keeper_clean_sheet_enabled: d.keeper_clean_sheet_enabled,
      home_advantage_bonus: d.home_advantage_bonus,
      enforce_lineup_deadline: d.enforce_lineup_deadline,
      lineup_lock_mode: d.lineup_lock_mode,
    };
  }

  /** Bring an element into view AFTER the click that reveals it has been painted.
   *  Switching a sub-tab and scrolling in the same handler scrolls to something
   *  that is not in the DOM yet; two frames is what it takes for React to commit
   *  and lay out the new panel. */
  /** Come sopra, ma per un elemento che ANCORA NON C'È: si aspetta che nasca.
   *
   *  È il caso del link che arriva da un'altra pagina. Il pannello sta dietro ai
   *  dati della lega, cioè a una chiamata di rete, e chiedere lo scroll subito
   *  significa cercare un id che nel DOM non esiste: nessun errore, nessuno
   *  scroll, e da fuori sembra che il link non faccia niente. Si guarda a ogni
   *  frame finché non compare, con un tetto di un paio di secondi perché un
   *  elemento che non arriverà mai (lega senza permessi, chiamata fallita) non
   *  lasci un ciclo acceso per sempre. */
  useEffect(() => {
    if (!pendingReveal) return;
    let alive = true;
    let tries = 0;
    const look = () => {
      if (!alive) return;
      const el = document.getElementById(pendingReveal);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        setPendingReveal(null);
        return;
      }
      if (tries++ < 120) requestAnimationFrame(look);
      else setPendingReveal(null);
    };
    requestAnimationFrame(look);
    return () => {
      alive = false;
    };
  }, [pendingReveal]);

  function revealAfterRender(elementId: string) {
    requestAnimationFrame(() =>
      requestAnimationFrame(() =>
        document.getElementById(elementId)?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
      ),
    );
  }

  async function loadLeagueDetail(leagueId: number) {
    const d = await getLeagueDetail(leagueId);
    setLeague(d);
    // Reseed the draft from the server on every (re)load, so switching league
    // never carries another league's unsaved options across.
    setOptionsDraft(optionsOf(d));
    // Pick the first team when none is selected OR when the selected team belongs
    // to a previously-viewed league (otherwise the roster load 404s on switch).
    if (d.teams.length && !d.teams.some((t) => t.team_id === selectedTeamId)) {
      setSelectedTeamId(d.teams[0].team_id);
    }
  }

  async function loadRoster(leagueId: number, teamId: number) {
    const r = await getTeamRoster(leagueId, teamId);
    setRoster(r);
  }

  async function loadCompetitions(leagueId: number) {
    setCompetitions(await getCompetitions(leagueId));
  }

  async function loadMatchdays(leagueId: number) {
    const items = await getLeagueMatchdays(leagueId);
    setMatchdays(items);
  }

  // Cambiare scheda cambia anche l'indirizzo: la barra in cima ne ricava il
  // titolo della pagina, e senza questo passaggio diceva «Le mie leghe» mentre
  // sotto c'era la gestione della lega appena creata.
  function goToTab(tab: AdminTab) {
    setActiveTab(tab);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set('tab', tab);
        return next;
      },
      { replace: true },
    );
  }

  useEffect(() => {
    const tab = searchParams.get('tab');
    if (tab === 'league') setActiveTab('league');
    if (tab === 'user') setActiveTab('user');
    // Deep link straight to a section of the league tab: the conclusion reminder
    // mails a link and it should land on the queue, not on the tab bar.
    if (tab && (['roster', 'competitions', 'matchdays', 'auction', 'market'] as const)
        .includes(tab as LeagueTab)) {
      setActiveTab('league');
      setLeagueTab(tab as LeagueTab);
      // …E CI SI PORTA DAVANTI. La scheda giusta si apre in fondo a una pagina
      // lunga, quindi «Gestisci sessione» atterrava in cima e la sessione da
      // gestire restava fuori schermo: sembrava che il link avesse solo cambiato
      // pagina. Non basta `revealAfterRender`, che aspetta due frame: arrivando
      // da un altro indirizzo la scheda non esiste ancora — sta dietro a
      // `league`, che è una chiamata di rete — e due frame dopo non è ancora
      // nata. Qui si chiede lo scroll e ci pensa l'effetto sotto, quando compare.
      setPendingReveal('vfoot-league-tabs');
    }
  }, [searchParams]);

  // Seasons available as a league's reference championship (for the create form).
  // SOLO QUELLI IN CORSO: una lega si gioca su un campionato che si sta giocando,
  // e la stagione non si cambia più dopo (v. LeagueReferenceSeasonView). Offrire
  // l'anno scorso voleva dire offrire una lega che non può giocare una giornata;
  // il server rifiuta comunque, questo è perché non lo si chieda nemmeno.
  useEffect(() => {
    void getRealSeasons(true)
      .then((s) => {
        setRealSeasons(s);
        setCreateSeasonId((cur) => (cur === '' && s.length ? s[0].id : cur));
      })
      .catch(() => setRealSeasons([]));
  }, []);

  useEffect(() => {
    if (!selectedLeagueId) {
      setLeague(null);
      setRoster(null);
      setCompetitions([]);
      setMatchdays([]);
      return;
    }
    void loadLeagueDetail(selectedLeagueId).catch((e) => setMsg(`Errore dettaglio lega: ${e.message}`));
    void loadCompetitions(selectedLeagueId).catch((e) => setMsg(`Errore competizioni: ${e.message}`));
    void loadMatchdays(selectedLeagueId).catch((e) => setMsg(`Errore matchdays: ${e.message}`));
  }, [selectedLeagueId]);

  useEffect(() => {
    if (!selectedLeagueId || !selectedTeamId) return;
    // Only load once the league detail for THIS league is in and the selected team
    // actually belongs to it — avoids a 404 with a team_id left over from another
    // league while the new detail is still loading.
    if (league?.league_id !== selectedLeagueId) return;
    if (!league.teams.some((t) => t.team_id === selectedTeamId)) return;
    void loadRoster(selectedLeagueId, selectedTeamId).catch((e) => setMsg(`Errore roster: ${e.message}`));
  }, [selectedLeagueId, selectedTeamId, league]);

  useEffect(() => {
    if (!selectedLeagueId || playerQuery.trim().length < 2) {
      setPlayerResults([]);
      return;
    }

    const t = window.setTimeout(() => {
      void searchPlayers(playerQuery, selectedLeagueId)
        .then(setPlayerResults)
        .catch(() => setPlayerResults([]));
    }, 250);

    return () => window.clearTimeout(t);
  }, [playerQuery, selectedLeagueId]);

  useEffect(() => {
    if (!msg) {
      setMsgTone('info');
      return;
    }
    const low = msg.toLowerCase();
    if (low.startsWith('api ') || low.startsWith('errore') || low.includes('failed') || low.includes('error')) {
      setMsgTone('error');
      return;
    }
    if (low.includes('in attesa') || low.includes('warning') || low.includes('attenzione')) {
      setMsgTone('warning');
      return;
    }
    if (
      low.includes('creat') ||
      low.includes('aggiornat') ||
      low.includes('aggiunt') ||
      low.includes('conclus')
    ) {
      setMsgTone('success');
      return;
    }
    setMsgTone('info');
  }, [msg]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setMsg('');
    try {
      await action();
    } catch (e) {
      setMsgTone('error');
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  // Decided server-side now: the same rule that the conclude endpoint enforces,
  // including the exception that lets a PARKED matchday be closed out of order as
  // soon as its postponed match is recovered.
  function concludeDisabledReason(md: LeagueMatchdayItem): string | null {
    return md.can_conclude ? null : md.conclude_blocked_reason || 'Non concludibile';
  }

  // The two honest answers to an incomplete matchday, side by side: rule on the
  // missing matches, or wait for them. This opens the first one.
  async function openOfficePanel(md: LeagueMatchdayItem) {
    if (!selectedLeagueId) return;
    const r = await getMatchdayOfficeVotes(selectedLeagueId, md.fantasy_matchday_id);
    setOfficePanel({
      md,
      matches: r.matches,
      picked: Object.fromEntries(r.matches.map((m) => [m.match_id, m.office_vote != null])),
      voto: String(r.matches.find((m) => m.office_vote != null)?.office_vote ?? 6),
    });
  }

  async function applyOfficeVotes(remove = false) {
    if (!selectedLeagueId || !officePanel) return;
    const ids = officePanel.matches.filter((m) => officePanel.picked[m.match_id]).map((m) => m.match_id);
    if (!ids.length) {
      setMsg('Nessuna partita selezionata');
      return;
    }
    const voto = Number(officePanel.voto);
    if (!remove && (!Number.isFinite(voto) || voto < 0 || voto > 10)) {
      setMsg('Il voto deve stare fra 0 e 10');
      return;
    }
    const r = await setMatchdayOfficeVotes(
      selectedLeagueId, officePanel.md.fantasy_matchday_id, ids, voto, 'Partita rinviata', remove);
    setOfficePanel((p) => (p ? { ...p, matches: r.matches } : p));
    await loadMatchdays(selectedLeagueId);
    setMsg(
      remove
        ? `Voto d'ufficio revocato su ${ids.length} partit${ids.length === 1 ? 'a' : 'e'}`
        : `Voto d'ufficio ${voto} su ${ids.length} partit${ids.length === 1 ? 'a' : 'e'}: ora puoi concludere`,
    );
  }

  // Park the current matchday (a postponement: the league moves on and this round is
  // scored when the recovery is played), or bring it back into the queue.
  async function awaitAction(md: LeagueMatchdayItem, awaiting: boolean, reason = '') {
    if (!selectedLeagueId) return;
    await setLeagueMatchdayAwaiting(selectedLeagueId, md.fantasy_matchday_id, awaiting, reason);
    await loadMatchdays(selectedLeagueId);
    setMsg(
      awaiting
        ? `Giornata ${md.real_matchday} in attesa: la lega avanza, la chiuderai al recupero`
        : `Giornata ${md.real_matchday} di nuovo in coda`,
    );
  }

  // If a matchday op reports classic teams without a lineup, open the resolution
  // prompt (per team: forfait/previous) instead of surfacing an error. Returns true
  // when it handled the error; false lets the caller re-throw to run().
  function openLineupPrompt(
    md: LeagueMatchdayItem,
    err: unknown,
    kind: 'conclude' | 'recompute',
    use?: 'current' | 'snapshot',
  ): boolean {
    if (!(err instanceof ApiError) || err.status !== 400) return false;
    let body: unknown = null;
    try {
      body = JSON.parse(err.detail);
    } catch {
      return false;
    }
    const teams = (body as { teams_without_lineup?: unknown })?.teams_without_lineup;
    if (!Array.isArray(teams) || !teams.length) return false;
    const typed = teams as Array<{ team_id: number; name: string; has_previous_lineup: boolean; previous_lineup_stale: number }>;
    const res: Record<number, 'forfait' | 'previous'> = {};
    for (const t of typed) res[t.team_id] = t.has_previous_lineup ? 'previous' : 'forfait';
    setLineupPrompt({ md, kind, use, teams: typed, resolutions: res });
    return true;
  }

  function resolutionsPayload(resolutions?: Record<number, 'forfait' | 'previous'>) {
    return resolutions
      ? (Object.fromEntries(Object.entries(resolutions).map(([k, v]) => [String(k), v])) as Record<string, 'forfait' | 'previous'>)
      : undefined;
  }

  async function concludeAction(md: LeagueMatchdayItem, resolutions?: Record<number, 'forfait' | 'previous'>) {
    if (!selectedLeagueId) return;
    try {
      await concludeLeagueMatchday(selectedLeagueId, md.fantasy_matchday_id, false, resolutionsPayload(resolutions));
    } catch (err) {
      if (openLineupPrompt(md, err, 'conclude')) return;
      throw err;
    }
    setLineupPrompt(null);
    await loadMatchdays(selectedLeagueId);
    await loadCompetitions(selectedLeagueId);
    setMsg(`Giornata ${md.real_matchday} conclusa`);
  }

  // Re-score a concluded matchday. use: 'current' = live rules (updates snapshot);
  // 'snapshot' = the frozen rules (e.g. after fixing a vote).
  async function recomputeAction(
    md: LeagueMatchdayItem,
    use: 'current' | 'snapshot',
    resolutions?: Record<number, 'forfait' | 'previous'>,
  ) {
    if (!selectedLeagueId) return;
    let out: RecomputeResult;
    try {
      out = (await recomputeLeagueMatchday(
        selectedLeagueId, md.fantasy_matchday_id, use, false, resolutionsPayload(resolutions),
      )) as RecomputeResult;
    } catch (err) {
      if (openLineupPrompt(md, err, 'recompute', use)) return;
      throw err;
    }
    setLineupPrompt(null);
    await loadMatchdays(selectedLeagueId);
    await loadCompetitions(selectedLeagueId);
    // Un ricalcolo puo' spostare un trofeo gia' assegnato. Dirlo qui e' il punto:
    // e' l'unico momento in cui c'e' un essere umano che guarda, e sa di aver
    // appena fatto qualcosa.
    const moved = out?.prizes_changed ?? [];
    const suffix = moved.length
      ? ' · ' + moved
          .map((p: PrizeChange) => `${p.icon} ${p.name}: ora ${p.now.join(', ') || 'nessuno'}${p.before.length ? ` (era ${p.before.join(', ')})` : ''}`)
          .join(' · ')
      : '';
    setMsg(
      `Giornata ${md.real_matchday} ricalcolata (${use === 'snapshot' ? 'regole congelate' : 'regole attuali'})${suffix}`,
    );
  }

  return (
    <div className="space-y-4">
      {/* Il titolo della pagina lo dà la scheda attiva, e nella scheda utente
          non c'e': era «Le mie leghe» — lo stesso nome del bottone in barra —
          sopra una scheda intitolata «Le tue leghe» che elenca le stesse leghe.
          Tre volte la stessa cosa in mezzo schermo, e nessuna delle tre aggiunge
          niente. Adesso l'elenco si intitola da sé. */}
      {activeTab === 'league' ? (
        <Card className="p-4">
          <SectionTitle>Gestione lega</SectionTitle>
          <div className="mt-2 text-sm text-ink-soft">
            {selectedLeague ? selectedLeague.name : 'Nessuna lega selezionata.'}
          </div>

          {/* Renders itself only while something is still missing, so it greets a
              brand-new league and then gets out of the way for good. */}
          {league ? (
            <LeagueSetupChecklist
              league={league}
              competitions={competitions}
              onGoToInvite={() => {
                // The invite code lives in the league card ABOVE the tab bar, so
                // there is no tab to switch to — just scroll to it.
                revealAfterRender('vfoot-invite-code');
              }}
              onGoToCompetitions={() => {
                setLeagueTab('competitions');
                // The tab BAR, not the panel: it lands with "Competizioni" visibly
                // selected and the form starting right underneath, instead of
                // dropping the user into the middle of a form with no context.
                revealAfterRender('vfoot-league-tabs');
              }}
            />
          ) : null}
        </Card>
      ) : null}

      {/* Fuori dalla scheda di intestazione perche' quella ora esiste solo per la
          lega: un messaggio di errore sulla creazione deve comparire lo stesso. */}
      {msg ? (
        <div
          className={`rounded-xl px-3 py-2 text-sm ${
            msgTone === 'error'
              ? 'bg-bad-bg text-bad'
              : msgTone === 'warning'
                ? 'bg-warn-bg text-warn'
                : msgTone === 'success'
                  ? 'bg-good-bg text-good'
                  : 'bg-surface-2 text-ink-soft'
          }`}
          role="status"
          aria-live="polite"
        >
          <span className="mr-2 font-semibold">
            {msgTone === 'error' ? 'Errore' : msgTone === 'warning' ? 'Attenzione' : msgTone === 'success' ? 'OK' : 'Info'}:
          </span>
          {msg}
        </div>
      ) : null}

      {activeTab === 'user' ? (
        <>
          <Card className="p-4">
            <SectionTitle>Le mie leghe</SectionTitle>
            {leagues.length ? (
              <div className="mt-3 space-y-2">
                {leagues.map((l) => {
                  const active = l.league_id === selectedLeagueId;
                  const team = l.team_name?.trim() || null;
                  return (
                    <div
                      key={l.league_id}
                      className={clsx(
                        'flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2',
                        active ? 'border-brand bg-brand/10' : 'border-line',
                      )}
                    >
                      {/* Lo stemma, che qui mancava: è la pagina che ELENCA le
                          leghe, cioè l'unico posto in cui si confrontano fra
                          loro, ed erano righe di solo testo. */}
                      <Crest descriptor={l.team_crest} teamName={team} size={34} className={team ? undefined : 'opacity-40'} />
                      {/* La riga intera cambia lega, non solo il bottone in
                          fondo: su un telefono quel bottone era un bersaglio da
                          sessanta pixel in una riga larga trecento, e restare
                          sulla pagina dopo averla scelta è ciò che permette di
                          vedere che la scelta ha fatto effetto. */}
                      <button
                        type="button"
                        onClick={() => setSelectedLeagueId(l.league_id)}
                        className="min-w-0 flex-1 text-left"
                        aria-pressed={active}
                      >
                        <div className={clsx('truncate font-semibold', active ? 'text-brand-strong' : 'text-ink')}>
                          {l.name}
                        </div>
                        <div className="text-xs text-ink-faint">
                          Squadra: {team ?? 'non impostata'}
                          {active ? ' · lega attiva' : ''}
                        </div>
                      </button>
                      <Badge tone={l.role === 'admin' ? 'green' : 'slate'}>
                        {l.role === 'admin' ? 'amministratore' : 'partecipante'}
                      </Badge>
                      <Button
                        size="sm"
                        variant={active ? 'primary' : 'secondary'}
                        onClick={() => {
                          setSelectedLeagueId(l.league_id);
                          goToTab('league');
                        }}
                      >
                        {l.role === 'admin' ? 'Gestisci' : 'Apri'}
                      </Button>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="mt-3 text-sm text-ink-soft">
                Non appartieni ancora a nessuna lega. Creane una o unisciti con un invite code qui sotto.
              </div>
            )}
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="p-4">
              <SectionTitle>Crea Lega</SectionTitle>
              <form
                className="mt-3 space-y-2"
                onSubmit={(e: FormEvent) => {
                  e.preventDefault();
                  void run(async () => {
                    if (createSeasonId === '') throw new Error('Seleziona il campionato di riferimento.');
                    const res = await createLeague({
                      name: createName,
                      team_name: createTeam,
                      reference_season_id: createSeasonId,
                      mode: createMode,
                    });
                    setCreatedInvite({ code: res.invite_code, name: createName });
                    setMsg('Lega creata. Seguendo i passi qui sotto diventa giocabile.');
                    setCreateName('');
                    setCreateTeam('');
                    await refreshLeagues();
                    setSelectedLeagueId(res.league_id);
                    // The vote-affecting rules live in Gestione lega, so send the new
                    // admin straight there instead of leaving them on the create form.
                    goToTab('league');
                  });
                }}
              >
                <label className="block text-sm font-medium text-ink-soft">
                  Nome lega <span className="text-bad">*</span>
                  <input className="mt-1 w-full rounded-xl border px-3 py-2 font-normal" placeholder="es. I Fenomeni del Lunedì" value={createName} onChange={(e) => setCreateName(e.target.value)} required />
                  {/* Every place that shows the name already labels it as a league
                      (the "Lega" label over the switcher, the Gestione lega page),
                      so a name starting with "Lega" reads doubled everywhere. */}
                  <span className="mt-1 block text-[11px] font-normal text-ink-faint">
                    Non serve iniziare con «Lega»: compare già come etichetta accanto al nome.
                  </span>
                </label>
                <label className="block text-sm font-medium text-ink-soft">
                  Nome tua squadra <span className="text-bad">*</span>
                  <input className="mt-1 w-full rounded-xl border px-3 py-2 font-normal" placeholder="Nome tua squadra" value={createTeam} onChange={(e) => setCreateTeam(e.target.value)} required />
                </label>
                <fieldset className="block text-sm font-medium text-ink-soft">
                  <legend>Come si fanno i punti <span className="text-bad">*</span></legend>
                  <div className="mt-1 grid gap-2 sm:grid-cols-2">
                    {/* Aura si vede ma non si sceglie: il motore a zone non e'
                        pronto, e una lega creata in quella modalita' resterebbe
                        ferma. Mostrarla spenta dice che esiste ed e' in lavoro;
                        toglierla del tutto direbbe che non esiste. */}
                    {([
                      ['classic', 'Fantacalcio classico', 'Voti + bonus/malus, ruoli P/D/C/A, listone e asta. Quello a cui giocano tutti.', false],
                      ['aura', 'Aura', 'Duelli per zona del campo: conta dove giocano i tuoi, non solo il voto.', true],
                    ] as const).map(([value, title, blurb, locked]) => (
                      <label
                        key={value}
                        className={clsx(
                          'rounded-xl border-2 p-3 transition',
                          locked
                            ? 'cursor-not-allowed border-line bg-surface-2/60 opacity-60'
                            : 'cursor-pointer',
                          // La scelta si deve VEDERE: prima selezionato e non
                          // selezionato differivano di un grigio su bianco.
                          !locked && createMode === value
                            ? 'border-brand bg-brand/10'
                            : !locked
                              ? 'border-line hover:border-brand/40'
                              : null,
                        )}
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <input
                            type="radio"
                            name="league-mode"
                            value={value}
                            checked={createMode === value}
                            disabled={locked}
                            onChange={() => {
                              if (!locked) setCreateMode(value);
                            }}
                          />
                          <span className="font-semibold">{title}</span>
                          {locked ? <Badge tone="slate">in arrivo</Badge> : null}
                        </div>
                        <div className="mt-1 pl-6 text-xs font-normal text-ink-faint">{blurb}</div>
                        {locked ? (
                          <div className="mt-1 pl-6 text-xs font-normal text-ink-faint">
                            Non ancora disponibile: per ora si gioca in classico.
                          </div>
                        ) : null}
                      </label>
                    ))}
                  </div>
                  <span className="mt-1 block text-[11px] font-normal text-ink-faint">
                    Si sceglie ora e non si cambia più, come il campionato di riferimento.
                  </span>
                </fieldset>
                <label className="block text-sm font-medium text-ink-soft">
                  Campionato di riferimento <span className="text-bad">*</span>
                  <select
                    className="mt-1 w-full rounded-xl border px-3 py-2 font-normal"
                    value={createSeasonId}
                    onChange={(e) => setCreateSeasonId(e.target.value ? Number(e.target.value) : '')}
                    required
                  >
                    <option value="">Campionato di riferimento…</option>
                    {realSeasons.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="text-xs text-ink-faint">
                  <span className="text-bad">*</span> Campi obbligatori. Il campionato di riferimento non è
                  modificabile dopo la creazione: rose, listone e calendario dipendono da esso.
                </div>
                <Button type="submit" disabled={busy}>Crea</Button>
              </form>
              {createdInvite ? (
                <div className="mt-3 rounded-xl border border-good/40 bg-good-bg px-3 py-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="text-sm font-semibold text-good">Manda questo a chi deve giocare</div>
                    <button
                      type="button"
                      onClick={() => setCreatedInvite(null)}
                      className="text-xs font-semibold text-ink-faint hover:text-ink-soft"
                    >
                      Chiudi
                    </button>
                  </div>
                  <div className="mt-2">
                    <InviteShare code={createdInvite.code} leagueName={createdInvite.name} compact />
                  </div>
                </div>
              ) : null}
            </Card>

            <Card className="p-4">
              <SectionTitle>Unisciti a Lega</SectionTitle>
              <form
                className="mt-3 space-y-2"
                onSubmit={(e: FormEvent) => {
                  e.preventDefault();
                  void run(async () => {
                    const team = joinTeam;
                    const res = await joinLeague({ invite_code: joinCode, team_name: joinTeam });
                    // «Join completato» diceva in inglese, e a meta': in una lega
                    // non si entra e basta, ci si entra CON una squadra, ed e'
                    // l'unica cosa che chi ha appena compilato il modulo vuole
                    // vedere confermata.
                    setMsg(`Sei entrato in «${res.name}» con ${team}.`);
                    setJoinCode('');
                    setJoinTeam('');
                    await refreshLeagues();
                    setSelectedLeagueId(res.league_id);
                  });
                }}
              >
                {/* «Invite code» e «Join» erano le uniche due parole inglesi in
                    pagina, e nominavano la stessa cosa che il riquadro accanto
                    chiama gia' «codice invito». */}
                <label className="block text-sm font-medium text-ink-soft">
                  Codice invito <span className="text-bad">*</span>
                  <input className="mt-1 w-full rounded-xl border px-3 py-2 font-normal" placeholder="es. Wo2FqVF2" value={joinCode} onChange={(e) => setJoinCode(e.target.value)} required />
                </label>
                <label className="block text-sm font-medium text-ink-soft">
                  Nome tua squadra <span className="text-bad">*</span>
                  <input className="mt-1 w-full rounded-xl border px-3 py-2 font-normal" placeholder="Nome tua squadra" value={joinTeam} onChange={(e) => setJoinTeam(e.target.value)} required />
                </label>
                <Button type="submit" disabled={busy}>Entra nella lega</Button>
              </form>
            </Card>
          </div>
        </>
      ) : !isAdmin ? (
        <Card className="p-4">
          <SectionTitle>Gestione lega</SectionTitle>
          <div className="mt-2 text-sm text-ink-soft">
            Serve il ruolo <b>admin</b> in questa lega per gestire roster, competizioni, giornate e asta.
            {selectedLeague ? ` Il tuo ruolo qui è "${selectedLeague.role}".` : ' Seleziona una lega.'}
          </div>
        </Card>
      ) : (
        <>
          <Card className="p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <SectionTitle>
                Gestione lega{selectedLeague ? <span className="ml-1 normal-case text-ink">· {selectedLeague.name}</span> : null}
              </SectionTitle>
            </div>
            <div className="mt-1 text-[11px] text-ink-faint">
              Riferita alla lega selezionata in alto. Cambia lega dal selettore in cima alla pagina.
            </div>

            {league ? (
              <div className="mt-3 space-y-3 text-sm">
                <div id="vfoot-invite-code" className="scroll-mt-24">
                  <InviteShare
                    code={league.invite_code}
                    path={league.invite_link}
                    leagueName={league.name}
                  />
                </div>
                {/* Qui stava "Modifiche manuali alla rosa: abilitate / bloccate".
                    Chiudeva soltanto add/rimuovi/import — tutte azioni dell'admin,
                    e l'interruttore era in questa stessa pagina: un lucchetto che
                    chi ha la chiave mette a se' stesso. Non fermava ne' l'asta ne'
                    il mercato a offerte, che hanno il loro stato e non lo
                    leggevano. Chi lo chiudeva e se ne dimenticava si ritrovava un
                    "Market is closed." davanti all'import di un foglio. */}
                {(() => {
                  // Everything in here edits a DRAFT. These four rules decide how
                  // votes are counted for the whole league, and they used to be
                  // written to the server on the change event — one mis-tap on a
                  // phone silently changed the regulation for everybody.
                  const saved = optionsOf(league);
                  const draft = optionsDraft ?? saved;
                  const set = (patch: LeagueSettingsPatch) =>
                    setOptionsDraft({ ...draft, ...patch });
                  const changed = (Object.keys(saved) as Array<keyof LeagueSettingsPatch>)
                    .filter((k) => draft[k] !== saved[k]);
                  const dirty = changed.length > 0;

                  return (
                    <div
                      className={clsx(
                        'space-y-3 rounded-xl border px-3 py-2 transition',
                        dirty ? 'border-warn bg-warn-bg/60' : '',
                      )}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="font-semibold">Opzioni partita</div>
                        {dirty ? (
                          <span className="rounded-full bg-warn px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
                            {changed.length} modifica{changed.length > 1 ? 'he' : ''} non salvata{changed.length > 1 ? 'e' : ''}
                          </span>
                        ) : null}
                      </div>

                      <div>
                        <label className="flex items-center gap-2 text-sm">
                          <span>Sostituzioni massime per giornata</span>
                          <input
                            type="number"
                            min={0}
                            max={11}
                            value={draft.max_substitutions ?? 0}
                            onChange={(e) => set({ max_substitutions: Number(e.target.value) })}
                            className="w-16 rounded-lg border px-2 py-1 text-sm"
                          />
                        </label>
                        <div className="mt-1 text-[11px] text-ink-faint">
                          Un titolare senza voto viene rimpiazzato dal primo panchinaro utile, fino a questo numero.
                        </div>
                      </div>

                      <div className="border-t pt-2">
                        <label className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={!!draft.defense_bonus_enabled}
                            onChange={(e) => set({ defense_bonus_enabled: e.target.checked })}
                          />
                          <span>Modificatore difesa</span>
                        </label>
                        <label className="mt-2 flex items-center gap-2 text-sm">
                          <span>Applicazione</span>
                          <select
                            value={draft.defense_bonus_mode}
                            disabled={!draft.defense_bonus_enabled}
                            onChange={(e) =>
                              set({ defense_bonus_mode: e.target.value as 'add_own' | 'subtract_opponent' })
                            }
                            className="rounded-lg border px-2 py-1 text-sm disabled:opacity-50"
                          >
                            <option value="add_own">Aggiunto alla propria squadra</option>
                            <option value="subtract_opponent">Sottratto alla squadra avversaria</option>
                          </select>
                        </label>
                        <div className="mt-1 text-[11px] text-ink-faint">
                          Premia chi schiera ≥4 difensori titolari: media dei 3 migliori difensori + portiere (voti
                          puri) → bonus a fasce.
                        </div>
                      </div>

                      <div className="border-t pt-2">
                        <label className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={!!draft.keeper_clean_sheet_enabled}
                            onChange={(e) => set({ keeper_clean_sheet_enabled: e.target.checked })}
                          />
                          <span>Modificatore portiere imbattuto</span>
                        </label>
                        <div className="mt-1 text-[11px] text-ink-faint">
                          +1 al fantatotale se il portiere schierato prende voto e non subisce gol.
                        </div>
                      </div>

                      <div className="border-t pt-2">
                        <label className="flex items-center gap-2 text-sm">
                          <span>Fattore campo</span>
                          <input
                            type="number"
                            min={0}
                            max={6}
                            step={0.5}
                            value={draft.home_advantage_bonus ?? 0}
                            onChange={(e) => set({ home_advantage_bonus: Number(e.target.value) })}
                            className="w-16 rounded-lg border px-2 py-1 text-sm"
                          />
                          <span className="text-ink-faint">al fantatotale di chi gioca in casa</span>
                        </label>
                        <div className="mt-1 text-[11px] text-ink-faint">
                          0 = spento. Vale <b>solo dove il campo esiste</b>: turni di coppa con andata e ritorno e
                          tornate di andata e ritorno di un campionato o girone. In una gara secca, o nella tornata
                          dispari in più, chi ospita l'ha deciso il calendario e il bonus non viene assegnato.
                        </div>
                      </div>

                      <div className="border-t pt-2">
                        <label className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={!!draft.enforce_lineup_deadline}
                            onChange={(e) => set({ enforce_lineup_deadline: e.target.checked })}
                          />
                          <span>Blocca la formazione</span>
                        </label>
                        <div className="mt-1 text-[11px] text-ink-faint">
                          Attivo in una lega reale. <b>Disattivalo</b> per le leghe di test su una stagione già
                          conclusa (altrimenti ogni formazione risulterebbe bloccata).
                        </div>
                        {draft.enforce_lineup_deadline ? (
                          <div className="mt-2 space-y-2 border-l-2 border-line pl-3">
                            <label className="flex items-start gap-2 text-sm">
                              <input
                                type="radio"
                                className="mt-1"
                                name="lineup_lock_mode"
                                checked={(draft.lineup_lock_mode ?? 'matchday') === 'matchday'}
                                onChange={() => set({ lineup_lock_mode: 'matchday' })}
                              />
                              <span>
                                <b>Al primo calcio d'inizio della giornata</b>
                                <span className="mt-0.5 block text-[11px] text-ink-faint">
                                  Tutta la formazione si chiude insieme, prima che si giochi la prima partita.
                                  È la regola tradizionale del fantacalcio.
                                </span>
                              </span>
                            </label>
                            <label className="flex items-start gap-2 text-sm">
                              <input
                                type="radio"
                                className="mt-1"
                                name="lineup_lock_mode"
                                checked={draft.lineup_lock_mode === 'player'}
                                onChange={() => set({ lineup_lock_mode: 'player' })}
                              />
                              <span>
                                <b>Ogni giocatore all'inizio della sua partita</b>
                                <span className="mt-0.5 block text-[11px] text-ink-faint">
                                  Chi ha la partita iniziata resta dov'è; sul resto della formazione si
                                  decide fino all'ultimo calcio d'inizio della giornata.
                                </span>
                              </span>
                            </label>
                          </div>
                        ) : null}
                      </div>

                      <div className="flex flex-wrap items-center gap-2 border-t pt-3">
                        <Button
                          size="sm"
                          disabled={!dirty || busy}
                          onClick={() =>
                            void run(async () => {
                              if (!league) return;
                              // Only the fields that actually changed travel: the
                              // rest are left alone rather than rewritten with the
                              // same value.
                              const patch: LeagueSettingsPatch = {};
                              for (const k of changed) Object.assign(patch, { [k]: draft[k] });
                              await updateLeagueSettings(league.league_id, patch);
                              await loadLeagueDetail(league.league_id);
                              setMsg('Opzioni partita salvate.');
                            })
                          }
                        >
                          Salva opzioni
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={!dirty || busy}
                          onClick={() => setOptionsDraft(saved)}
                        >
                          Annulla
                        </Button>
                        {!dirty ? (
                          <span className="text-[11px] text-ink-faint">Nessuna modifica in sospeso.</span>
                        ) : null}
                      </div>
                    </div>
                  );
                })()}
                <div>
                  <div className="font-semibold">Membri</div>
                  <div className="mt-2 space-y-1">
                    {(() => {
                      const adminCount = league.members.filter((x) => x.role === 'admin').length;
                      // A member is administered as a person, but recognised by his
                      // team: in a league of ten, "gino" says far less than
                      // "Deportivo Merenda", which is the name in every table and
                      // fixture on the site.
                      const teamOf = new Map(league.teams.map((t) => [t.manager_user_id, t]));
                      return league.members.map((m) => {
                        const demoting = m.role === 'admin';
                        const isLastAdmin = demoting && adminCount <= 1;
                        const nextRole = demoting ? 'manager' : 'admin';
                        const team = teamOf.get(m.user_id) ?? null;
                        return (
                          // On a phone the role button is as wide as the row, so a
                          // non-wrapping row squeezed the team name down to its first
                          // letter. Let the actions drop to their own line instead.
                          <div
                            key={m.membership_id}
                            className="flex flex-col gap-2 rounded-xl border px-3 py-2 sm:flex-row sm:items-center sm:justify-between"
                          >
                            <div className="flex min-w-0 items-center gap-2">
                              {/* No crest for someone without a team: the seeded
                                  fallback would invent one for a team that does
                                  not exist. */}
                              {team ? (
                                <Crest descriptor={team.crest} teamName={team.name} size={28} />
                              ) : (
                                <span className="h-7 w-7 shrink-0 rounded-full border border-dashed border-line" />
                              )}
                              <div className="min-w-0">
                                <div className="truncate font-semibold text-ink">
                                  {team?.name ?? <span className="italic text-ink-faint">nessuna squadra</span>}
                                </div>
                                <div className="truncate text-xs text-ink-faint">{m.username}</div>
                              </div>
                            </div>
                            <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                              {/* "manager" is the value the database stores, not a
                                  word to show: it grants nothing on its own — every
                                  participant right comes from BEING a member — so a
                                  badge naming it suggests a permission that does not
                                  exist. "partecipante" is also what the Le mie leghe
                                  tab already calls it. */}
                              <Badge tone={m.role === 'admin' ? 'green' : 'slate'}>
                                {m.role === 'admin' ? 'amministratore' : 'partecipante'}
                              </Badge>
                              <Button
                                size="sm"
                                variant="secondary"
                                disabled={isLastAdmin}
                                title={
                                  isLastAdmin
                                    ? 'È l\'unico amministratore: promuovine un altro prima di togliergli il ruolo.'
                                    : undefined
                                }
                                onClick={() =>
                                  void run(async () => {
                                    if (!league) return;
                                    if (m.user_id === user?.id && demoting) {
                                      const confirmed = window.confirm(
                                        'Confermi di rimuovere il tuo ruolo di amministratore? Perderai l\'accesso a questa pagina.'
                                      );
                                      if (!confirmed) return;
                                    } else if (!demoting) {
                                      // Promoting hands over the whole league: rose,
                                      // regolamento, calendario, asta. Worth a
                                      // question, and one mis-tap away otherwise.
                                      const confirmed = window.confirm(
                                        `Rendere ${m.username} amministratore? Potrà modificare regolamento, rose, calendario e ruoli, incluso il tuo.`
                                      );
                                      if (!confirmed) return;
                                    }
                                    await updateMemberRole(league.league_id, m.membership_id, nextRole);
                                    await loadLeagueDetail(league.league_id);
                                  })
                                }
                              >
                                {demoting ? 'Revoca amministratore' : 'Rendi amministratore'}
                              </Button>
                              {isLastAdmin ? (
                                <span className="text-xs text-warn">unico amministratore</span>
                              ) : null}
                            </div>
                          </div>
                        );
                      });
                    })()}
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-3 rounded-xl border border-warn/40 bg-warn-bg p-3 text-sm text-warn">
                Seleziona una lega dal menu. Le funzioni avanzate sono disponibili solo su una lega selezionata.
              </div>
            )}
          </Card>

          {league ? (
            <>
              <Card id="vfoot-league-tabs" className="p-4 scroll-mt-4">
                {/* Five tabs do not fit 390px: the BAR scrolls, so the page does
                    not get a horizontal scrollbar of its own. */}
                <div className="-mx-1 overflow-x-auto px-1">
                  <div className="inline-flex rounded-xl bg-surface-2 p-1">
                  {([
                    ['roster', 'Roster'],
                    ['competitions', 'Competizioni'],
                    ['matchdays', 'Matchdays'],
                    ['auction', 'Asta'],
                    ['market', 'Mercato'],
                  ] as Array<[LeagueTab, string]>).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setLeagueTab(id)}
                      className={
                        'whitespace-nowrap ' +
                        (leagueTab === id
                          ? 'rounded-lg bg-surface px-3 py-2 text-sm font-semibold'
                          : 'px-3 py-2 text-sm font-semibold text-ink-soft')
                      }
                    >
                      {label}
                    </button>
                  ))}
                  </div>
                </div>
              </Card>

              {leagueTab === 'roster' ? (
                <div className="grid gap-4 lg:grid-cols-2">
                  <Card className="p-4">
                    <SectionTitle>Roster Team</SectionTitle>
                    <div className="mt-2 text-xs text-ink-faint">I nomi qui sotto (es. Alpha/Beta) sono i team fantasy della lega, non calciatori reali.</div>
                    <div className="mt-2">
                      <label htmlFor="roster-team-select" className="mb-1 block text-xs font-semibold text-ink-faint">Fantasy Team</label>
                      <select id="roster-team-select" className="w-full rounded-xl border px-3 py-2 text-sm" value={selectedTeamId ?? ''} onChange={(e) => setSelectedTeamId(Number(e.target.value))}>
                        {league.teams.map((t) => (
                          <option key={t.team_id} value={t.team_id}>{t.name}</option>
                        ))}
                      </select>
                    </div>

                    <div className="mt-3 rounded-xl border p-3">
                      <div className="text-xs font-semibold text-ink-faint">Aggiungi giocatore per nome</div>
                      <label htmlFor="roster-player-search" className="sr-only">Cerca giocatore</label>
                      <input
                        id="roster-player-search"
                        className="mt-2 w-full rounded-xl border px-3 py-2 text-sm"
                        placeholder="Cerca giocatore (es. Lautaro, Leao...)"
                        value={playerQuery}
                        onChange={(e) => {
                          setPlayerQuery(e.target.value);
                          setSelectedPlayer(null);
                        }}
                      />
                      {playerResults.length ? (
                        <div className="mt-2 max-h-36 overflow-auto space-y-1">
                          {playerResults.map((p) => (
                            <button
                              key={p.player_id}
                              type="button"
                              className="w-full rounded-lg border px-2 py-1 text-left text-xs hover:bg-surface-2"
                              onClick={() => {
                                setSelectedPlayer(p);
                                setPlayerQuery(p.full_name);
                              }}
                            >
                              {p.full_name} <span className="text-ink-faint">(id {p.player_id})</span>
                            </button>
                          ))}
                        </div>
                      ) : null}

                      <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_120px_auto]">
                        <div className="rounded-xl border bg-surface-2 px-3 py-2 text-sm">
                          {selectedPlayer ? `Selezionato: ${selectedPlayer.full_name}` : 'Seleziona un giocatore dalla ricerca'}
                        </div>
                        <label htmlFor="roster-player-price" className="sr-only">Prezzo acquisto</label>
                        <input id="roster-player-price" className="rounded-xl border px-3 py-2 text-sm" placeholder="Prezzo" value={manualPrice} onChange={(e) => setManualPrice(e.target.value)} />
                        <Button
                          size="sm"
                          onClick={() =>
                            void run(async () => {
                              if (!selectedLeagueId || !selectedTeamId || !selectedPlayer) return;
                              setBuyRefusal(null);
                              try {
                                await addRosterPlayer(
                                  selectedLeagueId, selectedTeamId, selectedPlayer.player_id,
                                  Number(manualPrice), forceBuy);
                              } catch (e) {
                                if (e instanceof ApiError) setBuyRefusal(e.message);
                                throw e;
                              }
                              await loadRoster(selectedLeagueId, selectedTeamId);
                              setPlayerQuery('');
                              setPlayerResults([]);
                              setSelectedPlayer(null);
                              setForceBuy(false);
                            })
                          }
                        >
                          Compra
                        </Button>
                      </div>
                      {/* Il rifiuto si legge qui, e la spunta per scavalcarlo compare
                          solo adesso: e' l'unico momento in cui serve saperlo. */}
                      {buyRefusal ? (
                        <div className="mt-2 rounded-xl border border-bad/40 bg-bad-bg/40 px-3 py-2 text-[11px]">
                          <div className="text-ink">{buyRefusal}</div>
                          <label className="mt-2 flex items-center gap-2 text-ink-faint">
                            <input
                              type="checkbox"
                              checked={forceBuy}
                              onChange={(e) => setForceBuy(e.target.checked)}
                            />
                            Forza: scavalca slot e budget (per rose ricostruite da altrove)
                          </label>
                        </div>
                      ) : null}
                    </div>

                    <div className="mt-3 rounded-xl border p-3">
                      <div className="text-xs font-semibold text-ink-faint">Import roster in blocco</div>
                      <div className="mt-1 text-xs text-ink-faint">
                        Riempi più squadre in una volta. Colonne: <code>team_name</code> oppure{' '}
                        <code>manager_username</code>, più <code>player_id</code> e <code>price</code>. Puoi
                        incollare il testo oppure caricare un file <code>.csv</code>. Gli <b>id</b> dei
                        giocatori si trovano nel <Link to="/listone" className="underline">Listone</Link>{' '}
                        (o cercandoli qui sopra).
                      </div>
                      <label htmlFor="roster-csv-file" className="sr-only">Seleziona file CSV</label>
                      <input
                        id="roster-csv-file"
                        type="file"
                        accept=".csv,text/csv"
                        className="mt-2 block w-full rounded-xl border px-3 py-2 text-xs"
                        onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
                      />
                      <label htmlFor="roster-csv-text" className="sr-only">Testo CSV roster</label>
                      <textarea
                        id="roster-csv-text"
                        className="mt-2 h-24 w-full rounded-xl border px-3 py-2 text-xs"
                        value={csvText}
                        onChange={(e) => setCsvText(e.target.value)}
                      />
                      <Button
                        size="sm"
                        className="mt-2"
                        onClick={() =>
                          void run(async () => {
                            if (!selectedLeagueId) return;
                            if (!csvFile && !csvText.trim()) {
                              setMsg('Inserisci CSV nel box oppure seleziona un file .csv');
                              return;
                            }
                            await importRosterCsv(selectedLeagueId, csvText, csvFile);
                            if (selectedTeamId) await loadRoster(selectedLeagueId, selectedTeamId);
                            setCsvFile(null);
                          })
                        }
                      >
                        Import CSV
                      </Button>
                    </div>

                    <div className="mt-3 rounded-xl border border-good/40 bg-good-bg/40 p-3">
                      <div className="text-xs font-semibold text-ink-faint">Import da listone .xlsx compilato</div>
                      <div className="mt-1 text-xs text-ink-faint">
                        Scarica il listone dalla pagina <Link to="/listone" className="underline">Listone</Link>,
                        compila le colonne <b>Assegnato a</b> (menu a discesa) e <b>Prezzo</b>, poi ricaricalo
                        qui: assegna le rose in un colpo solo, con gli <b>id</b> già corretti.
                      </div>
                      <label htmlFor="roster-xlsx-file" className="sr-only">Seleziona file xlsx del listone</label>
                      <input
                        id="roster-xlsx-file"
                        type="file"
                        accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        className="mt-2 block w-full rounded-xl border px-3 py-2 text-xs"
                        onChange={(e) => setRosterXlsxFile(e.target.files?.[0] ?? null)}
                      />
                      <Button
                        size="sm"
                        className="mt-2"
                        disabled={!rosterXlsxFile}
                        onClick={() =>
                          void run(async () => {
                            if (!selectedLeagueId || !rosterXlsxFile) return;
                            const res = await importRosterXlsx(selectedLeagueId, rosterXlsxFile);
                            if (selectedTeamId) await loadRoster(selectedLeagueId, selectedTeamId);
                            setRosterXlsxFile(null);
                            setMsg(`Import xlsx: ${res.imported} assegnati${res.skipped ? `, ${res.skipped} saltati` : ''}.`);
                          })
                        }
                      >
                        Importa da xlsx
                      </Button>
                    </div>
                  </Card>

                  {/* Questa colonna serve a RIEMPIRE, non a leggere: una riga di
                      conti — quanto resta e quali caselle mancano, cioe' le due
                      domande che decidono se puoi ancora comprare — e poi i nomi
                      con le due azioni. La rosa si studia dalla pagina Rose, che
                      ha statistiche, reparti e tutto il resto. */}
                  <Card className="p-4">
                    <SectionTitle>Roster corrente</SectionTitle>
                    <div className="mt-2 text-sm text-ink-soft">Team: <span className="font-semibold">{selectedTeamName || '-'}</span></div>
                    {roster?.budget ? (
                      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border bg-surface-2 px-3 py-2 text-[11px]">
                        <span>
                          speso <b className="text-ink">{price(roster.budget.spent)}</b> di {price(roster.budget.initial)}
                        </span>
                        <span>
                          residuo{' '}
                          <b className={roster.budget.remaining < roster.budget.slots_remaining_total ? 'text-bad' : 'text-good'}>
                            {price(roster.budget.remaining)}
                          </b>
                        </span>
                        <span className="text-ink-faint">
                          {ROLE_ORDER.map((r) => {
                            const s = roster.budget!.slots[r as ClassicRole];
                            return `${r} ${s.filled}/${s.quota}`;
                          }).join(' · ')}
                        </span>
                        {roster.budget.slots_remaining_total === 0 ? (
                          <Badge tone="green">rosa completa</Badge>
                        ) : (
                          <Badge tone="slate">{roster.budget.slots_remaining_total} da riempire</Badge>
                        )}
                      </div>
                    ) : null}
                    <div className="mt-2 max-h-[520px] overflow-auto space-y-1 text-xs">
                      {roster?.players.length ? (
                        [...roster.players]
                          .sort((a, b) =>
                            (ROLE_ORDER.indexOf(a.role ?? '') - ROLE_ORDER.indexOf(b.role ?? ''))
                            || a.name.localeCompare(b.name))
                          .map((p) => (
                          <div key={p.slot_id} className="rounded-lg border px-2 py-1">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <span className="min-w-0">
                                {p.role ? <Badge tone="blue">{p.role}</Badge> : null}{' '}
                                <b className="text-ink">{p.name}</b>{' '}
                                <span className="text-ink-faint">{price(p.price)}</span>
                              </span>
                              {sellFor === p.slot_id || voidFor === p.slot_id ? null : (
                                <span className="flex items-center gap-1">
                                  <Button
                                    size="sm"
                                    variant="secondary"
                                    onClick={() => {
                                      setVoidFor(null);
                                      setSellFor(p.slot_id);
                                      setSellPrice(String(p.price));
                                    }}
                                  >
                                    Vendi
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="secondary"
                                    onClick={() => { setSellFor(null); setVoidFor(p.slot_id); }}
                                  >
                                    Annulla contratto
                                  </Button>
                                </span>
                              )}
                            </div>

                            {sellFor === p.slot_id ? (
                              <div className="mt-2 flex flex-wrap items-center gap-2 border-t pt-2">
                                <label htmlFor={`sell-${p.slot_id}`} className="text-ink-faint">
                                  Rientrano in cassa
                                </label>
                                <input
                                  id={`sell-${p.slot_id}`}
                                  className="w-20 rounded-lg border px-2 py-1"
                                  value={sellPrice}
                                  onChange={(e) => setSellPrice(e.target.value)}
                                />
                                <span className="text-ink-faint">
                                  {CURRENCY_SYMBOL} (pagato {p.price})
                                </span>
                                <Button
                                  size="sm"
                                  disabled={busy}
                                  onClick={() =>
                                    void run(async () => {
                                      if (!selectedLeagueId || !selectedTeamId) return;
                                      await sellRosterPlayer(
                                        selectedLeagueId, selectedTeamId, p.player_id,
                                        Number(sellPrice));
                                      await loadRoster(selectedLeagueId, selectedTeamId);
                                      setSellFor(null);
                                    })
                                  }
                                >
                                  Conferma vendita
                                </Button>
                                <Button size="sm" variant="secondary" onClick={() => setSellFor(null)}>
                                  Lascia stare
                                </Button>
                              </div>
                            ) : null}

                            {voidFor === p.slot_id ? (
                              <div className="mt-2 flex flex-wrap items-center gap-2 border-t pt-2">
                                <span className="text-ink-faint">
                                  Cancella il contratto: come se non fosse mai stato firmato.
                                  Tornano in cassa {amount(p.price)} e non ne resta traccia.
                                </span>
                                <Button
                                  size="sm"
                                  disabled={busy}
                                  onClick={() =>
                                    void run(async () => {
                                      if (!selectedLeagueId || !selectedTeamId) return;
                                      await voidRosterSlot(selectedLeagueId, selectedTeamId, p.slot_id);
                                      await loadRoster(selectedLeagueId, selectedTeamId);
                                      setVoidFor(null);
                                    })
                                  }
                                >
                                  Annulla davvero
                                </Button>
                                <Button size="sm" variant="secondary" onClick={() => setVoidFor(null)}>
                                  Lascia stare
                                </Button>
                              </div>
                            ) : null}
                          </div>
                        ))
                      ) : (
                        <div className="text-ink-faint">Nessun giocatore nel roster.</div>
                      )}
                    </div>
                  </Card>
                </div>
              ) : null}

              {leagueTab === 'competitions' ? (
                <div className="space-y-4">
                  {/* Creating and editing used to happen in the same form, on this
                      page: a "select or create" dropdown, then four numbered cards
                      that were half wizard and half editor. They are two different
                      moments, so they are two different places now — this tab only
                      LISTS what exists and points at them. */}
                  <Card className="p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <SectionTitle>Competizioni</SectionTitle>
                      <Link
                        to="/league-admin/competitions/new"
                        className="rounded-xl bg-ink px-3 py-2 text-sm font-semibold text-paper hover:opacity-90"
                      >
                        + Crea competizione
                      </Link>
                    </div>

                    <div className="mt-3 space-y-2">
                      {competitions.map((c) => {
                        const dependsOn = c.dependencies.map((d) => d.source_competition_name);
                        const mds = Object.values(c.round_calendar ?? {});
                        return (
                          <Link
                            key={c.competition_id}
                            to={`/league-admin/competitions/${c.competition_id}`}
                            className="flex items-start justify-between gap-3 rounded-xl border border-line p-3 transition hover:border-line hover:bg-surface-2"
                          >
                            <div className="min-w-0">
                              <div className="truncate text-sm font-semibold text-ink">{c.name}</div>
                              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                                <Badge tone="slate">{competitionFormatLabel(c)}</Badge>
                                <Badge tone={c.status === 'done' ? 'green' : c.status === 'active' ? 'amber' : 'slate'}>
                                  {c.status === 'done' ? 'conclusa' : c.status === 'active' ? 'in corso' : 'bozza'}
                                </Badge>
                                {c.prizes.map((p) => (
                                  <span key={p.prize_id} title={`${p.name} — ${p.condition_label}`} className="text-base leading-none">
                                    {p.icon}
                                  </span>
                                ))}
                              </div>
                              {dependsOn.length ? (
                                <div className="mt-1 text-[11px] text-ink-faint">
                                  partecipanti da: {dependsOn.join(', ')}
                                </div>
                              ) : null}
                            </div>
                            <div className="shrink-0 text-right text-[11px] text-ink-faint">
                              <div>
                                {c.fixtures.finished}/{c.fixtures.total} gare
                              </div>
                              <div>
                                {c.rounds.length} {c.rounds.length === 1 ? 'giornata' : 'giornate'}
                              </div>
                              {mds.length ? (
                                <div>
                                  reali {Math.min(...mds)}–{Math.max(...mds)}
                                </div>
                              ) : null}
                            </div>
                          </Link>
                        );
                      })}
                      {!competitions.length ? (
                        <div className="rounded-xl border border-dashed border-line p-4 text-center text-sm text-ink-faint">
                          Nessuna competizione. Il percorso guidato costruisce un campionato, una coppa o un girone con
                          playoff in quattro passi.
                        </div>
                      ) : null}
                    </div>

                    <div className="mt-4 border-t pt-3 text-xs text-ink-faint">
                      Ti serve una formula diversa dalle tre guidate?{' '}
                      <Link to="/league-admin/competitions/advanced" className="font-semibold underline">
                        Costruzione avanzata
                      </Link>
                      : la componi turno per turno.
                    </div>
                  </Card>
                </div>
              ) : null}

              {leagueTab === 'matchdays' ? (
                <Card className="p-4">
                  <SectionTitle>Giornate — progressione della lega</SectionTitle>
                  <div className="mt-1 text-xs text-ink-faint">
                    Questo è il <b>registro</b> della lega: cosa è stato conteggiato. Il campionato va avanti da sé —
                    formazioni e blocchi seguono il calendario reale e non aspettano queste chiusure. Se una partita è
                    stata rinviata puoi mettere la giornata <b>in attesa</b>: la lega prosegue e la chiudi al recupero.
                  </div>
                  <div className="mt-3 space-y-2 text-sm">
                    {matchdays.length ? (
                      matchdays.map((md) => {
                        const disabledReason = concludeDisabledReason(md);
                        const canConclude = !disabledReason;
                        const phaseChip =
                          md.phase === 'concluded'
                            ? { tone: 'green' as const, label: 'Conclusa' }
                            : md.phase === 'awaiting'
                            ? { tone: 'amber' as const, label: 'In attesa di recupero' }
                            : md.phase === 'current'
                            ? { tone: 'amber' as const, label: 'Da conteggiare' }
                            : { tone: 'slate' as const, label: 'Futura' };
                        const frame =
                          md.phase === 'current' || md.phase === 'awaiting'
                            ? 'border-warn/40 bg-warn-bg'
                            : md.phase === 'concluded'
                            ? 'border-line bg-surface'
                            : 'border-line bg-surface-2 opacity-70';
                        return (
                          <div key={md.fantasy_matchday_id} className={'rounded-xl border p-3 ' + frame}>
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-semibold">
                                {md.real_competition_season.competition} · Giornata {md.real_matchday}
                              </span>
                              <Badge tone={phaseChip.tone}>{phaseChip.label}</Badge>
                              <Badge tone={md.real_completion.is_completed ? 'green' : 'amber'}>
                                reale {md.real_completion.completed}/{md.real_completion.total}
                              </Badge>
                              {md.is_playing ? <Badge tone="blue">In campo ora</Badge> : null}
                              {md.is_fieldable ? <Badge tone="blue">Schierabile</Badge> : null}
                            </div>
                            <div className="mt-1 text-xs text-ink-soft">
                              Fixture fantasy: {md.fixtures.finished}/{md.fixtures.total}
                              {md.concluded_by ? ` · conclusa da ${md.concluded_by}` : ''}
                              {md.awaiting_reason ? ` · ${md.awaiting_reason}` : ''}
                            </div>
                            {/* What ELSE hangs on this one. Said here because this is
                                where the two gestures that stall a competition live:
                                closing late, and parking for a recovery. The league
                                steps over an open round by design — a cup reading its
                                table cannot, and there was nothing anywhere to say so. */}
                            {(md.decides ?? []).length ? (
                              <div className="mt-1.5 rounded-lg border border-line bg-surface/70 px-2 py-1.5 text-xs text-ink-soft">
                                <b>Decide una fase:</b>
                                <ul className="mt-0.5 space-y-0.5">
                                  {(md.decides ?? []).map((d) => (
                                    <li key={d.stage_id}>
                                      {d.competition_name} · {d.stage_name} — {d.rule_text}
                                      {d.at_risk ? (
                                        <span className="ml-1 font-semibold text-warn">
                                          (le sue giornate sono già passate: verrà spostata più avanti)
                                        </span>
                                      ) : d.target_matchday != null ? (
                                        <span className="text-ink-faint">
                                          {' '}
                                          · si gioca alla giornata {d.target_matchday}
                                        </span>
                                      ) : null}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                            {md.phase === 'current' || md.phase === 'awaiting' ? (
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <Button
                                  size="sm"
                                  aria-label={`Concludi giornata ${md.real_matchday}`}
                                  disabled={!canConclude || busy}
                                  onClick={() => void run(() => concludeAction(md))}
                                >
                                  {md.phase === 'awaiting' ? 'Concludi il recupero' : 'Concludi giornata'}
                                </Button>
                                {/* The explicit gesture: whether to wait for a
                                    postponed match or not is a decision of the
                                    league, never something the calendar does by
                                    itself. */}
                                {md.phase === 'current' && !md.real_completion.is_completed ? (
                                  <button
                                    type="button"
                                    disabled={busy}
                                    onClick={() => void run(() => openOfficePanel(md))}
                                    className="text-xs font-semibold text-accent hover:text-accent disabled:opacity-50"
                                  >
                                    Voto d'ufficio…
                                  </button>
                                ) : null}
                                {md.phase === 'current' && !md.real_completion.is_completed ? (
                                  <button
                                    type="button"
                                    disabled={busy}
                                    onClick={() => {
                                      const reason = window.prompt(
                                        `Giornata ${md.real_matchday}: la lega va avanti e questa resta in attesa del recupero.\n\nMotivo (facoltativo):`,
                                        'Partita rinviata',
                                      );
                                      if (reason !== null) void run(() => awaitAction(md, true, reason));
                                    }}
                                    className="text-xs font-semibold text-warn hover:text-warn disabled:opacity-50"
                                  >
                                    Avanza, questa resta in attesa
                                  </button>
                                ) : null}
                                {md.phase === 'awaiting' ? (
                                  <button
                                    type="button"
                                    disabled={busy}
                                    onClick={() => void run(() => awaitAction(md, false))}
                                    className="text-xs font-semibold text-ink-faint hover:text-ink disabled:opacity-50"
                                  >
                                    Rimetti in coda
                                  </button>
                                ) : null}
                                {disabledReason ? (
                                  <span className="text-xs text-warn">{disabledReason}</span>
                                ) : null}
                              </div>
                            ) : null}

                            {md.phase === 'concluded' ? (
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  disabled={busy}
                                  onClick={() => {
                                    if (window.confirm(`Ricalcolare la giornata ${md.real_matchday} con il regolamento ATTUALE della lega? Risultato e tabellini verranno riscritti.`))
                                      void run(() => recomputeAction(md, 'current'));
                                  }}
                                >
                                  Ricalcola (regole attuali)
                                </Button>
                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() => {
                                    if (window.confirm(`Ricalcolare la giornata ${md.real_matchday} con il regolamento CONGELATO alla conclusione (es. dopo una correzione voti)?`))
                                      void run(() => recomputeAction(md, 'snapshot'));
                                  }}
                                  className="text-xs font-semibold text-ink-faint hover:text-ink disabled:opacity-50"
                                >
                                  …con regole congelate
                                </button>
                              </div>
                            ) : null}

                            {officePanel && officePanel.md.fantasy_matchday_id === md.fantasy_matchday_id ? (
                              <div className="mt-3 rounded-xl border border-accent/40 bg-accent/10 p-3">
                                <div className="text-sm font-semibold text-accent">
                                  Voto d'ufficio — solo per questa lega
                                </div>
                                <div className="mt-1 text-xs text-accent">
                                  Un voto <b>imposto</b>, non un dato: vale come voto puro e come fantavoto, senza
                                  bonus né malus, perché la partita non si è giocata. Le altre leghe non ne sono
                                  toccate: possono aspettare il recupero.
                                </div>
                                {officePanel.matches.length ? (
                                  <>
                                    <div className="mt-2 space-y-1">
                                      {officePanel.matches.map((m) => (
                                        <label
                                          key={m.match_id}
                                          className="flex items-center gap-2 rounded-lg bg-surface px-2 py-1.5 text-sm"
                                        >
                                          <input
                                            type="checkbox"
                                            checked={!!officePanel.picked[m.match_id]}
                                            onChange={(e) =>
                                              setOfficePanel((p) =>
                                                p
                                                  ? { ...p, picked: { ...p.picked, [m.match_id]: e.target.checked } }
                                                  : p,
                                              )
                                            }
                                          />
                                          <span className="min-w-0 flex-1 truncate">
                                            {m.home} — {m.away}
                                          </span>
                                          <Badge tone={m.status === 'postponed' ? 'amber' : 'slate'}>
                                            {m.status === 'postponed' ? 'rinviata' : m.status}
                                          </Badge>
                                          {m.office_vote != null ? (
                                            <Badge tone="green">d'ufficio {m.office_vote}</Badge>
                                          ) : null}
                                        </label>
                                      ))}
                                    </div>
                                    <div className="mt-2 flex flex-wrap items-center gap-2">
                                      <label className="text-xs text-accent">
                                        Voto{' '}
                                        <input
                                          type="number"
                                          step="0.5"
                                          min="0"
                                          max="10"
                                          value={officePanel.voto}
                                          onChange={(e) =>
                                            setOfficePanel((p) => (p ? { ...p, voto: e.target.value } : p))
                                          }
                                          className="w-16 rounded-lg border border-line px-2 py-1"
                                        />
                                      </label>
                                      <Button size="sm" disabled={busy} onClick={() => void run(() => applyOfficeVotes(false))}>
                                        Imponi
                                      </Button>
                                      <button
                                        type="button"
                                        disabled={busy}
                                        onClick={() => void run(() => applyOfficeVotes(true))}
                                        className="text-xs font-semibold text-ink-faint hover:text-ink disabled:opacity-50"
                                      >
                                        Revoca
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => setOfficePanel(null)}
                                        className="text-xs font-semibold text-ink-faint hover:text-ink"
                                      >
                                        Chiudi
                                      </button>
                                    </div>
                                  </>
                                ) : (
                                  <div className="mt-2 text-xs text-accent">
                                    Nessuna partita senza dati definitivi in questa giornata.
                                  </div>
                                )}
                              </div>
                            ) : null}

                            {lineupPrompt && lineupPrompt.md.fantasy_matchday_id === md.fantasy_matchday_id ? (
                              <div className="mt-3">
                                <div className="rounded-xl border border-warn/40 bg-warn-bg p-3">
                                    <div className="text-sm font-semibold text-warn">
                                      Alcune squadre non hanno schierato la formazione
                                    </div>
                                    <div className="mt-1 text-xs text-warn">
                                      Scegli per ciascuna: <b>forfait</b> (fantatotale 0) oppure <b>rischiera la precedente</b>
                                      (filtrata sui giocatori ancora in rosa).
                                    </div>
                                    <div className="mt-2 space-y-1.5">
                                      {lineupPrompt.teams.map((t) => (
                                        <div key={t.team_id} className="flex flex-wrap items-center gap-2 rounded-lg bg-surface px-2 py-1.5">
                                          <span className="min-w-0 flex-1 text-sm font-medium">{t.name}</span>
                                          <div className="inline-flex overflow-hidden rounded-lg border border-line text-xs">
                                            {(['previous', 'forfait'] as const).map((opt) => {
                                              const active = lineupPrompt.resolutions[t.team_id] === opt;
                                              const disabled = opt === 'previous' && !t.has_previous_lineup;
                                              return (
                                                <button
                                                  key={opt}
                                                  type="button"
                                                  disabled={disabled}
                                                  onClick={() =>
                                                    setLineupPrompt((p) =>
                                                      p ? { ...p, resolutions: { ...p.resolutions, [t.team_id]: opt } } : p,
                                                    )
                                                  }
                                                  className={
                                                    (active ? 'bg-ink text-paper ' : 'bg-surface text-ink-soft ') +
                                                    (disabled ? 'cursor-not-allowed opacity-40 ' : 'hover:bg-surface-2 ') +
                                                    'px-2.5 py-1 font-semibold'
                                                  }
                                                >
                                                  {opt === 'previous' ? 'Precedente' : 'Forfait'}
                                                </button>
                                              );
                                            })}
                                          </div>
                                          {t.has_previous_lineup && t.previous_lineup_stale > 0 ? (
                                            <span className="text-[11px] text-warn">
                                              {t.previous_lineup_stale} non più in rosa
                                            </span>
                                          ) : !t.has_previous_lineup ? (
                                            <span className="text-[11px] text-ink-faint">nessuna precedente</span>
                                          ) : null}
                                        </div>
                                      ))}
                                    </div>
                                    <div className="mt-2 flex gap-2">
                                      <Button
                                        size="sm"
                                        disabled={busy}
                                        onClick={() =>
                                          void run(() =>
                                            lineupPrompt.kind === 'recompute'
                                              ? recomputeAction(md, lineupPrompt.use ?? 'current', lineupPrompt.resolutions)
                                              : concludeAction(md, lineupPrompt.resolutions),
                                          )
                                        }
                                      >
                                        {lineupPrompt.kind === 'recompute' ? 'Ricalcola con queste scelte' : 'Concludi con queste scelte'}
                                      </Button>
                                      <button
                                        type="button"
                                        onClick={() => setLineupPrompt(null)}
                                        className="text-xs font-semibold text-ink-faint hover:text-ink"
                                      >
                                        Annulla
                                      </button>
                                    </div>
                                </div>
                              </div>
                            ) : null}
                          </div>
                        );
                      })
                    ) : (
                      <div className="text-ink-faint">
                        Nessuna giornata: crea una competizione e mappala sulle giornate reali (tab Competizioni).
                      </div>
                    )}
                  </div>
                </Card>
              ) : null}

              {leagueTab === 'auction' ? (
                <Card className="p-4">
                  <SectionTitle>Asta</SectionTitle>
                  <div className="mt-2 text-sm text-ink-soft">
                    L’asta si svolge nella <b>Sala asta</b> live: chiamata del giocatore (manuale, casuale
                    o casuale per ruolo), rilanci in tempo reale, aggiudicazione e assegnazione diretta,
                    con controllo automatico di budget e slot. Da lì puoi anche avviare l’asta iniziale.
                  </div>
                  <Link to="/auction" className="mt-3 inline-flex">
                    <Button>Apri la sala asta</Button>
                  </Link>
                </Card>
              ) : null}

              {leagueTab === 'market' && league ? (
                <MarketAdminPanel leagueId={league.league_id} />
              ) : null}
            </>
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              <Card className="p-4">
                <SectionTitle>Funzioni di gestione lega</SectionTitle>
                <ul className="mt-3 space-y-2 text-sm text-ink-soft">
                  <li>• Mercato di riparazione: apri/gestisci sessioni di offerte, valida gli scambi</li>
                  <li>• Modifica roster con ricerca giocatori per nome</li>
                  <li>• Crea competizioni (campionato o coppa)</li>
                  <li>• Gestione asta (prossimo chiamato, chiamati, budget)</li>
                </ul>
              </Card>
              <Card className="p-4">
                <SectionTitle>Come Procedere</SectionTitle>
                <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm text-ink-soft">
                  <li>Passa alla scheda Le mie leghe per creare una lega o unirti a una esistente.</li>
                  <li>Seleziona la lega nel menu in alto.</li>
                  <li>Torna su Gestione lega per i controlli avanzati.</li>
                </ol>
              </Card>
            </div>
          )}
        </>
      )}
    </div>
  );
}
