import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getCompetitions, getLeagueDetail, getLeagueStandings } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { useCompetitionContext } from '../league/CompetitionContext';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type { CompetitionItem, LeagueDetail, LeagueStandingRow } from '../types/league';

const COMP_TYPE_LABEL: Record<string, string> = { round_robin: 'Campionato', knockout: 'Coppa' };

// The LEAGUE page is the global hub: league info, participants, a SUMMARY of the
// competitions (no tables — standings/brackets live under each competition, on the
// Classifica page driven by the competition switcher).
export default function LeaguePage() {
  const { leagues, selectedLeagueId, selectedLeague } = useLeagueContext();
  const { setSelectedCompetitionId } = useCompetitionContext();
  const navigate = useNavigate();
  const openCompetition = (id: number) => {
    setSelectedCompetitionId(id);
    navigate('/matches');
  };
  const [detail, setDetail] = useState<LeagueDetail | null>(null);
  const [competitions, setCompetitions] = useState<CompetitionItem[]>([]);
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);
  // Standings give each participant's record (wins etc). Competition-scoped, so
  // we take the first one; pre-season every row is simply zeroed.
  const [standings, setStandings] = useState<Record<number, LeagueStandingRow>>({});

  useEffect(() => {
    setSelectedTeamId(null);
    if (!selectedLeagueId) {
      setDetail(null);
      return;
    }
    void getLeagueDetail(selectedLeagueId)
      .then(setDetail)
      .catch(() => setDetail(null));
    void getCompetitions(selectedLeagueId)
      .then(setCompetitions)
      .catch(() => setCompetitions([]));
  }, [selectedLeagueId]);

  useEffect(() => {
    if (!selectedLeagueId) {
      setStandings({});
      return;
    }
    void getLeagueStandings(selectedLeagueId)
      .then((res) => setStandings(Object.fromEntries(res.standings.map((r) => [r.team_id, r]))))
      .catch(() => setStandings({}));
  }, [selectedLeagueId]);

  if (!leagues.length) {
    return (
      <Card className="p-4">
        <SectionTitle>Lega</SectionTitle>
        <div className="mt-2 text-sm text-slate-600">Non appartieni ancora a nessuna lega.</div>
        <Link to="/league-admin" className="mt-3 inline-flex rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white">
          Vai a Le mie leghe (crea o unisciti)
        </Link>
      </Card>
    );
  }

  if (!selectedLeagueId || !detail) {
    return (
      <Card className="p-4">
        <SectionTitle>Lega</SectionTitle>
        <div className="mt-2 text-sm text-slate-600">Seleziona una lega dal selettore in alto per vedere i dettagli.</div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <SectionTitle>Lega Attiva</SectionTitle>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <div className="text-xl font-black">{detail.name}</div>
              <Badge tone={selectedLeague?.market_open ? 'green' : 'red'}>
                Mercato {selectedLeague?.market_open ? 'aperto' : 'chiuso'}
              </Badge>
            </div>
            <div className="mt-2 text-sm text-slate-600">Invite code: {detail.invite_code}</div>
          </div>
          <Link to="/matches">
            <Button variant="primary" size="sm">
              Sfoglia le partite →
            </Button>
          </Link>
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>Competizioni</SectionTitle>
        <div className="mt-1 text-[11px] text-slate-400">
          Classifiche e tabelloni sono nelle pagine Partite / Classifica, per la competizione selezionata in alto.
        </div>
        <div className="mt-2 space-y-2">
          {competitions.length ? (
            competitions.map((c) => (
              <div key={c.competition_id} className="flex items-center justify-between rounded-xl border px-3 py-2 text-sm">
                <div className="flex items-center gap-2">
                  <Badge tone={c.competition_type === 'knockout' ? 'amber' : 'blue'}>
                    {COMP_TYPE_LABEL[c.competition_type] ?? c.competition_type}
                  </Badge>
                  <div>
                    <div className="font-semibold">{c.name}</div>
                    <div className="text-xs text-slate-500">
                      {c.status} · fixture {c.fixtures.finished}/{c.fixtures.total}
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => openCompetition(c.competition_id)}
                  className="rounded-xl bg-slate-200 px-3 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-300"
                >
                  Apri
                </button>
              </div>
            ))
          ) : (
            <div className="text-sm text-slate-500">Nessuna competizione ancora creata.</div>
          )}
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>Partecipanti</SectionTitle>
        <div className="mt-1 text-[11px] text-slate-400">Clicca un partecipante per vederne il rendimento e aprirne la rosa.</div>
        <div className="mt-2 divide-y">
          {detail.teams.map((t, i) => {
            const row = standings[t.team_id];
            const selected = selectedTeamId === t.team_id;
            return (
              <div key={t.team_id}>
                <button
                  onClick={() => setSelectedTeamId((cur) => (cur === t.team_id ? null : t.team_id))}
                  className={`flex w-full items-center justify-between py-2 text-left text-sm ${selected ? 'bg-slate-50' : ''}`}
                >
                  <span className="flex items-center gap-2">
                    <span className="w-5 font-semibold text-slate-400">{i + 1}</span>
                    <span className="font-semibold">{t.name}</span>
                  </span>
                  <span className="flex items-center gap-3 text-slate-500">
                    {row ? <span className="text-xs">{row.points} pt</span> : null}
                    <span>{t.manager_username}</span>
                  </span>
                </button>
                {selected ? (
                  <div className="mb-2 ml-7 rounded-xl border border-slate-100 bg-slate-50 p-3">
                    <div className="text-sm font-semibold text-slate-800">{t.name}</div>
                    <div className="text-xs text-slate-500">Manager: {t.manager_username}</div>
                    {row && row.played > 0 ? (
                      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-slate-600">
                        <span>Posizione: <b className="text-slate-800">{row.rank}º</b></span>
                        <span>Vittorie: <b className="text-emerald-700">{row.wins}</b></span>
                        <span>Pareggi: <b>{row.draws}</b></span>
                        <span>Sconfitte: <b className="text-rose-700">{row.losses}</b></span>
                        <span>Punti: <b className="text-slate-800">{row.points}</b></span>
                      </div>
                    ) : (
                      <div className="mt-1 text-[12px] text-slate-400">Il campionato non è ancora iniziato.</div>
                    )}
                    <Link
                      to={`/teams/${t.team_id}`}
                      className="mt-2 inline-flex rounded-xl bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white"
                    >
                      Vedi la rosa completa →
                    </Link>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>Gestione Lega</SectionTitle>
        <div className="mt-2 text-sm text-slate-600">Mercato, roster, competizioni e asta sono nella sezione Gestione lega.</div>
        <Link to="/league-admin?tab=league" className="mt-3 inline-flex rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white">
          Apri Gestione lega
        </Link>
      </Card>
    </div>
  );
}
