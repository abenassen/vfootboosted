import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ApiError,
  checkTrade,
  createTrade,
  getBudgetGrants,
  getTeamRoster,
  getTrades,
  grantCredits,
  revokeBudgetGrant,
  type BudgetGrantRow,
  type TradeRequest,
  type TradeRow,
} from '../api/backend';
import { Button, Card, SectionTitle } from './ui';
import { CURRENCY_NAME_PLURAL, amount as inWords, price } from '../utils/currency';
import { ROLE_LABEL, ROLE_ORDER, stamp } from '../utils/market';
import type { TeamRoster } from '../types/league';

type TeamRef = { team_id: number; name: string };

/** Le due cose che l'admin fa all'economia della lega dal di fuori: dare crediti,
 *  e registrare uno scambio fra due allenatori.
 *
 *  Stanno insieme perche' capitano insieme — la dote si distribuisce prima di una
 *  sessione di mercato, e gli scambi si trascrivono nella stessa mezz'ora — e
 *  perche' sono le due che nascono da un accordo preso fuori dall'app: qui non si
 *  applica un regolamento, si REGISTRA quello che i manager si sono detti. */
export default function LeagueEconomyPanel({
  leagueId, teams, mode, onChanged,
}: {
  leagueId: number;
  teams: TeamRef[];
  mode: string;
  /** Rose e budget sono cambiati: la pagina attorno si rilegga. */
  onChanged?: () => void;
}) {
  const [grants, setGrants] = useState<BudgetGrantRow[]>([]);
  const [trades, setTrades] = useState<TradeRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Quante operazioni sono passate di qui. Serve allo scambio: una concessione di
  // crediti cambia il portafoglio delle stesse squadre che ha in mano, e senza un
  // segnale mostrerebbe il residuo di prima — cioe' un numero che contraddice la
  // pagina Rose senza che nessuna delle due dica perche'.
  const [rev, setRev] = useState(0);

  const load = useCallback(async () => {
    try {
      const [g, t] = await Promise.all([getBudgetGrants(leagueId), getTrades(leagueId)]);
      setGrants(g.grants);
      setTrades(t.trades);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Errore nel caricamento.');
    }
  }, [leagueId]);

  useEffect(() => { void load(); }, [load]);

  const act = useCallback(async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
      setRev((n) => n + 1);
      onChanged?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Operazione non riuscita.');
    } finally {
      setBusy(false);
    }
  }, [load, onChanged]);

  return (
    <div className="space-y-4">
      {error && <Card className="border border-bad/40 bg-bad-bg p-3 text-sm text-bad">{error}</Card>}
      <GrantCard leagueId={leagueId} teams={teams} grants={grants} busy={busy} act={act} />
      <TradeCard leagueId={leagueId} teams={teams} mode={mode} trades={trades} busy={busy} act={act}
        rev={rev} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Crediti                                                             */
/* ------------------------------------------------------------------ */

function GrantCard({
  leagueId, teams, grants, busy, act,
}: {
  leagueId: number;
  teams: TeamRef[];
  grants: BudgetGrantRow[];
  busy: boolean;
  act: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [everyone, setEveryone] = useState(true);
  const [teamId, setTeamId] = useState<number | null>(teams[0]?.team_id ?? null);
  const [value, setValue] = useState('50');
  const [reason, setReason] = useState('');

  const n = Number(value);
  const valid = Number.isFinite(n) && n !== 0 && (everyone || teamId != null);

  return (
    <Card className="p-4">
      <SectionTitle>Crediti alle squadre</SectionTitle>
      <div className="mt-1 text-sm text-ink-soft">
        La dote che si distribuisce prima di una sessione di mercato, a tutti o a una
        sola squadra. Con un numero negativo si tolgono — ma mai sotto zero.
      </div>

      <div className="mt-3 space-y-3">
        <div className="flex flex-wrap gap-2">
          {([[true, 'A tutte le squadre'], [false, 'A una squadra']] as const).map(([v, label]) => (
            <button key={String(v)} type="button" onClick={() => setEveryone(v)}
              className={everyone === v
                ? 'rounded-xl bg-ink px-3 py-2 text-sm font-semibold text-surface'
                : 'rounded-xl border border-line px-3 py-2 text-sm text-ink-soft'}>
              {label}
            </button>
          ))}
        </div>

        {!everyone && (
          <label className="block text-sm">
            <span className="text-ink-soft">Squadra</span>
            <select className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-sm"
              value={teamId ?? ''} onChange={(e) => setTeamId(Number(e.target.value))}>
              {teams.map((t) => <option key={t.team_id} value={t.team_id}>{t.name}</option>)}
            </select>
          </label>
        )}

        <div className="flex flex-wrap items-end gap-3">
          <label className="block text-sm">
            <span className="text-ink-soft">Quanti {CURRENCY_NAME_PLURAL}</span>
            <input type="number" className="mt-1 w-28 rounded-xl border border-line px-3 py-2 text-sm"
              value={value} onChange={(e) => setValue(e.target.value)} />
          </label>
          <label className="block min-w-[12rem] flex-1 text-sm">
            <span className="text-ink-soft">Causale (facoltativa)</span>
            <input className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-sm"
              placeholder="es. Dote di riparazione" value={reason}
              onChange={(e) => setReason(e.target.value)} />
          </label>
        </div>

        <div className="text-xs text-ink-faint">
          {n < 0 ? 'Verranno tolti' : 'Riceveranno'} <b>{Number.isFinite(n) ? inWords(Math.abs(n)) : '—'}</b>
          {' '}{everyone ? `${teams.length} squadre` : (teams.find((t) => t.team_id === teamId)?.name ?? '—')}.
          {' '}La lega lo vede in bacheca.
        </div>

        <Button disabled={busy || !valid}
          onClick={() => act(() => grantCredits(leagueId, {
            amount: n,
            reason: reason.trim() || undefined,
            team_ids: everyone || teamId == null ? undefined : [teamId],
          }))}>
          {n < 0 ? 'Togli i crediti' : 'Dai i crediti'}
        </Button>
      </div>

      {grants.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-ink-faint">
            Concessioni ({grants.length})
          </div>
          <div className="mt-1 divide-y divide-line">
            {grants.map((g) => (
              <div key={g.batch} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <div className="min-w-0">
                  <b className={g.amount < 0 ? 'text-bad' : 'text-good'}>
                    {g.amount > 0 ? '+' : ''}{price(g.amount)}
                  </b>{' '}
                  <span className="text-ink-faint">
                    {g.everyone ? 'a tutti' : `a ${g.teams[0]?.name ?? '—'}`}
                    {g.reason ? ` · ${g.reason}` : ''} · {stamp(g.at)}
                  </span>
                </div>
                <Button size="sm" variant="ghost" disabled={busy}
                  onClick={() => {
                    if (window.confirm('Annullare questa concessione? I crediti tornano indietro.')) {
                      void act(() => revokeBudgetGrant(leagueId, g.batch));
                    }
                  }}>
                  Annulla
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* Scambio                                                             */
/* ------------------------------------------------------------------ */

function TradeCard({
  leagueId, teams, mode, trades, busy, act, rev,
}: {
  leagueId: number;
  teams: TeamRef[];
  mode: string;
  trades: TradeRow[];
  busy: boolean;
  act: (fn: () => Promise<unknown>) => Promise<void>;
  /** Sale a ogni operazione dell'economia: le due rose vanno rilette. */
  rev: number;
}) {
  const isClassic = mode === 'classic';
  const [aId, setAId] = useState<number | null>(teams[0]?.team_id ?? null);
  const [bId, setBId] = useState<number | null>(teams[1]?.team_id ?? null);
  const [rosterA, setRosterA] = useState<TeamRoster | null>(null);
  const [rosterB, setRosterB] = useState<TeamRoster | null>(null);
  const [pickedA, setPickedA] = useState<number[]>([]);
  const [pickedB, setPickedB] = useState<number[]>([]);
  const [cash, setCash] = useState('0');
  const [cashFrom, setCashFrom] = useState<'a' | 'b'>('a');
  const [note, setNote] = useState('');
  const [verdict, setVerdict] = useState<{
    ok: boolean; reason: string; remaining_a: number; remaining_b: number; settlement: number;
  } | null>(null);

  useEffect(() => {
    setPickedA([]); setRosterA(null);
    if (aId != null) void getTeamRoster(leagueId, aId).then(setRosterA).catch(() => setRosterA(null));
  }, [leagueId, aId]);
  useEffect(() => {
    setPickedB([]); setRosterB(null);
    if (bId != null) void getTeamRoster(leagueId, bId).then(setRosterB).catch(() => setRosterB(null));
  }, [leagueId, bId]);

  // Il portafoglio e' cambiato mentre questo pannello era aperto (crediti dati o
  // ritirati, uno scambio registrato): si rilegge senza toccare le spunte, perche'
  // il residuo qui dentro e quello della pagina Rose sono lo STESSO numero e non
  // possono divergere per il tempo che l'admin resta su questa schermata.
  useEffect(() => {
    if (!rev) return;   // 0 = niente e' ancora successo: caricano gli effetti qui sopra
    if (aId != null) void getTeamRoster(leagueId, aId).then(setRosterA).catch(() => undefined);
    if (bId != null) void getTeamRoster(leagueId, bId).then(setRosterB).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rev]);

  const cashN = Math.max(0, Number(cash) || 0);
  const request: TradeRequest | null = useMemo(() => (
    aId == null || bId == null ? null : {
      team_a: aId, team_b: bId, players_a: pickedA, players_b: pickedB,
      cash_amount: cashN, cash_from: cashFrom, note: note.trim(),
    }
  ), [aId, bId, pickedA, pickedB, cashN, cashFrom, note]);

  // Il verdetto arriva mentre si compone, non dopo aver premuto: comporre uno
  // scambio e' spuntare caselle su due rose, e scoprire alla fine che i ruoli non
  // combaciano vuol dire rifarlo da capo.
  useEffect(() => {
    if (!request || (!pickedA.length && !pickedB.length) || aId === bId) {
      setVerdict(null);
      return undefined;
    }
    const t = window.setTimeout(() => {
      void checkTrade(leagueId, request).then(setVerdict).catch(() => setVerdict(null));
    }, 250);
    return () => window.clearTimeout(t);
    // `rev`: il verdetto porta dentro il residuo delle due squadre, quindi
    // invecchia insieme a quello. Senza, una dote data mentre lo scambio e' gia'
    // composto lascia il «prima» aggiornato accanto a un «dopo» di prima.
  }, [leagueId, request, pickedA.length, pickedB.length, aId, bId, rev]);

  const sameTeam = aId != null && aId === bId;
  const canSave = !!request && !!verdict?.ok && !sameTeam && !busy;

  return (
    <Card className="p-4">
      <SectionTitle>Scambio fra due squadre</SectionTitle>
      <div className="mt-1 text-sm text-ink-soft">
        Il prezzo viaggia col giocatore: chi lo riceve lo eredita alla cifra a cui era
        stato comprato, ed è quella che deciderà il suo recupero il giorno che verrà
        svincolato.{' '}
        {isClassic
          ? 'I residui non si muovono: la differenza fra i contratti si pareggia in crediti. Si scambia a coppie di pari ruolo — anche più coppie insieme.'
          : 'In questa lega i ruoli non esistono: le due liste possono essere di lunghezze diverse.'}
      </div>

      {/* Le due colonne sono simmetriche perche' lo scambio lo e': in ciascuna si
          spunta chi PARTE, e chi parte di qua arriva di la'. */}
      <div className="mt-3 text-xs text-ink-faint">
        Spunta in ogni rosa chi parte: i selezionati passano all’altra squadra.
      </div>
      <div className="mt-2 grid gap-4 md:grid-cols-2">
        <TradeSide label="Prima squadra" teams={teams} teamId={aId} onTeam={setAId} roster={rosterA}
          picked={pickedA} onPicked={setPickedA} isClassic={isClassic}
          after={verdict?.ok && isClassic ? verdict.remaining_a : null} />
        <TradeSide label="Seconda squadra" teams={teams} teamId={bId} onTeam={setBId} roster={rosterB}
          picked={pickedB} onPicked={setPickedB} isClassic={isClassic}
          after={verdict?.ok && isClassic ? verdict.remaining_b : null} />
      </div>

      {sameTeam && (
        <div className="mt-3 text-sm text-bad">Scegli due squadre diverse.</div>
      )}

      {isClassic && (
        <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-line pt-3">
          <label className="block text-sm">
            <span className="text-ink-soft">Contropartita in {CURRENCY_NAME_PLURAL}</span>
            <input type="number" min={0} className="mt-1 w-28 rounded-xl border border-line px-3 py-2 text-sm"
              value={cash} onChange={(e) => setCash(e.target.value)} />
          </label>
          {cashN > 0 && (
            <label className="block text-sm">
              <span className="text-ink-soft">La paga</span>
              <select className="mt-1 rounded-xl border border-line px-3 py-2 text-sm"
                value={cashFrom} onChange={(e) => setCashFrom(e.target.value as 'a' | 'b')}>
                <option value="a">{teams.find((t) => t.team_id === aId)?.name ?? 'la prima'}</option>
                <option value="b">{teams.find((t) => t.team_id === bId)?.name ?? 'la seconda'}</option>
              </select>
            </label>
          )}
          <label className="block min-w-[12rem] flex-1 text-sm">
            <span className="text-ink-soft">Nota (facoltativa)</span>
            <input className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-sm"
              placeholder="es. accordo di gennaio" value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
        </div>
      )}

      {verdict && !verdict.ok && (
        <div className="mt-3 rounded-xl border border-bad/40 bg-bad-bg/40 px-3 py-2 text-sm text-ink">
          {verdict.reason}
        </div>
      )}
      {/* IL PAREGGIO SI DICE, anche se non si decide. L'admin non lo compone e non
          lo puo' cambiare — e' quello che tiene fermi i due residui — ma e' un
          movimento di crediti fra due squadre, e un movimento di crediti che
          nessuno vede e' esattamente cio' da cui nascono le segnalazioni. Il
          saldo a scambio fatto, invece, sta accanto al residuo di ogni squadra e
          non in fondo: detto qui era una seconda frase con dentro un numero —
          «Legends resta con 56» a un metro da «residuo 39» — e si leggeva come un
          secondo portafoglio, non come un dopo. */}
      {verdict?.ok && isClassic && (
        <div className="mt-3 text-sm text-ink-soft">
          {verdict.settlement === 0 ? (
            <>Scambio valido: contratti di pari valore, non si muove nulla.</>
          ) : (
            <>
              Scambio valido. I contratti non valgono uguale:{' '}
              <b>{price(Math.abs(verdict.settlement))}</b> passano da{' '}
              <b>{teams.find((t) => t.team_id === (verdict.settlement > 0 ? aId : bId))?.name}</b> a{' '}
              <b>{teams.find((t) => t.team_id === (verdict.settlement > 0 ? bId : aId))?.name}</b>{' '}
              per pareggiare, così i residui restano quelli di adesso. Cambia il
              recupero futuro, non la cassa.
            </>
          )}
        </div>
      )}

      <Button className="mt-3" disabled={!canSave}
        onClick={() => {
          if (!request) return;
          if (!window.confirm('Registrare lo scambio? Le rose cambiano subito, e le formazioni non ancora bloccate vengono riparate.')) return;
          void act(async () => {
            await createTrade(leagueId, request);
            // Le due rose le rilegge l'effetto su `rev`, con le stesse chiamate
            // che servono anche dopo una concessione di crediti.
            setPickedA([]); setPickedB([]); setCash('0'); setNote(''); setVerdict(null);
          });
        }}>
        Registra scambio
      </Button>

      {trades.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-ink-faint">
            Scambi registrati ({trades.length})
          </div>
          <div className="mt-1 divide-y divide-line">
            {trades.map((t) => (
              <div key={t.trade_id} className="py-2 text-sm">
                <div>
                  <b>{t.team_a_name}</b> <span className="text-ink-faint">⇄</span> <b>{t.team_b_name}</b>
                  <span className="text-ink-faint"> · {stamp(t.at)}</span>
                </div>
                <div className="text-xs text-ink-faint">
                  {t.a.map((p) => `${p.name} (${p.price})`).join(', ') || '—'}
                  {' → '}
                  {t.b.map((p) => `${p.name} (${p.price})`).join(', ') || '—'}
                  {t.cash ? ` · ${inWords(t.cash.amount)} da ${t.cash.from === 'a' ? t.team_a_name : t.team_b_name}` : ''}
                  {/* Il pareggio nello storico: mesi dopo, e' l'unica riga che
                      spiega due movimenti di crediti che nessuno ha pattuito. */}
                  {t.settlement
                    ? ` · ${inWords(t.settlement.amount)} di pareggio contratti da `
                      + `${t.settlement.from === 'a' ? t.team_a_name : t.team_b_name}`
                    : ''}
                  {t.note ? ` · ${t.note}` : ''}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

/** Una delle due parti: la squadra, e quali dei suoi giocatori partono.
 *
 *  La rosa si spunta, non si cerca: sono venticinque nomi che l'admin ha davanti,
 *  e un campo di ricerca qui vorrebbe dire digitare due volte per uno scambio che
 *  in classic e' quasi sempre uno contro uno. */
function TradeSide({
  label, teams, teamId, onTeam, roster, picked, onPicked, isClassic, after,
}: {
  label: string;
  teams: TeamRef[];
  teamId: number | null;
  onTeam: (id: number) => void;
  roster: TeamRoster | null;
  picked: number[];
  onPicked: (ids: number[]) => void;
  isClassic: boolean;
  /** Quanto resterebbe a scambio fatto, se lo scambio composto sta in piedi. */
  after: number | null;
}) {
  const toggle = (pid: number) => {
    onPicked(picked.includes(pid) ? picked.filter((x) => x !== pid) : [...picked, pid]);
  };
  const players = roster?.players ?? [];
  const groups = isClassic
    ? ROLE_ORDER.map((r) => [r, players.filter((p) => p.role === r)] as const).filter(([, g]) => g.length)
    : [['', players] as const];
  const total = players.filter((p) => picked.includes(p.player_id))
    .reduce((s, p) => s + p.price, 0);

  return (
    <div className="rounded-xl border border-line p-3">
      <label className="block text-sm">
        <span className="text-ink-soft">{label}</span>
        <select className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-sm"
          value={teamId ?? ''} onChange={(e) => onTeam(Number(e.target.value))}>
          {teams.map((t) => <option key={t.team_id} value={t.team_id}>{t.name}</option>)}
        </select>
      </label>
      {roster?.budget && (
        <div className="mt-1 text-xs text-ink-faint">
          residuo {price(roster.budget.remaining)}
          {after != null && after !== roster.budget.remaining ? (
            <> → <b className="text-ink">{price(after)}</b> a scambio fatto</>
          ) : null}
          {roster.budget.granted ? ` · ${price(roster.budget.granted)} dall'admin` : ''}
          {roster.budget.trade_cash > 0 ? ` · ${price(roster.budget.trade_cash)} incassati negli scambi` : ''}
          {roster.budget.trade_cash < 0 ? ` · ${price(-roster.budget.trade_cash)} girati negli scambi` : ''}
        </div>
      )}

      <div className="mt-2 max-h-64 space-y-2 overflow-auto">
        {players.length === 0 ? (
          <div className="text-xs text-ink-faint">Rosa vuota.</div>
        ) : groups.map(([role, group]) => (
          <div key={role || 'all'}>
            {role && (
              <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                {ROLE_LABEL[role]}
              </div>
            )}
            <div className="mt-1 space-y-1">
              {group.map((p) => (
                <label key={p.player_id}
                  className="flex items-center justify-between gap-2 rounded-lg px-1 py-0.5 text-sm hover:bg-surface-2">
                  <span className="flex min-w-0 items-center gap-2">
                    <input type="checkbox" checked={picked.includes(p.player_id)}
                      onChange={() => toggle(p.player_id)} />
                    <span className="truncate">{p.name}</span>
                  </span>
                  <span className="shrink-0 text-xs text-ink-faint">{price(p.price)}</span>
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-2 text-xs text-ink-faint">
        {picked.length === 0 ? 'Nessuno in partenza' : (
          <>Partono <b>{picked.length}</b> per <b>{price(total)}</b> di contratti</>
        )}
      </div>
    </div>
  );
}
