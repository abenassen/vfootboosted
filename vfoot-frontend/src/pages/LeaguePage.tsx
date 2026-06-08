import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCompetitions, getLeagueDetail, getLeagueStandings, getTeamRoster } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import { StandingsTable, type StandingRowVM } from '../components/league/StandingsTable';
import type { CompetitionItem, LeagueDetail, LeagueStandingRow, TeamRoster } from '../types/league';

function standingRows(rows: LeagueStandingRow[], myTeam?: string | null): StandingRowVM[] {
  return rows.map((r) => ({
    key: String(r.team_id),
    rank: r.rank,
    name: r.team,
    played: r.played,
    wins: r.wins,
    draws: r.draws,
    losses: r.losses,
    goalsFor: r.goals_for,
    goalsAgainst: r.goals_against,
    goalDiff: r.goal_diff,
    points: r.points,
    avgScore: r.avg_score_for,
    highlight: myTeam ? r.team === myTeam : false,
  }));
}

export default function LeaguePage() {
  const { leagues, selectedLeagueId, selectedLeague } = useLeagueContext();
  const [detail, setDetail] = useState<LeagueDetail | null>(null);
  const [competitions, setCompetitions] = useState<CompetitionItem[]>([]);
  const [standings, setStandings] = useState<LeagueStandingRow[]>([]);
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);
  const [roster, setRoster] = useState<TeamRoster | null>(null);

  useEffect(() => {
    setSelectedTeamId(null);
    if (!selectedLeagueId) {
      setDetail(null);
      setStandings([]);
      return;
    }
    void getLeagueDetail(selectedLeagueId)
      .then(setDetail)
      .catch(() => setDetail(null));
    void getCompetitions(selectedLeagueId)
      .then(setCompetitions)
      .catch(() => setCompetitions([]));
    void getLeagueStandings(selectedLeagueId)
      .then((r) => setStandings(r.standings))
      .catch(() => setStandings([]));
  }, [selectedLeagueId]);

  useEffect(() => {
    if (!selectedLeagueId || selectedTeamId == null) {
      setRoster(null);
      return;
    }
    void getTeamRoster(selectedLeagueId, selectedTeamId)
      .then(setRoster)
      .catch(() => setRoster(null));
  }, [selectedLeagueId, selectedTeamId]);

  if (!leagues.length) {
    return (
      <Card className="p-4">
        <SectionTitle>Lega</SectionTitle>
        <div className="mt-2 text-sm text-slate-600">Non appartieni ancora a nessuna lega.</div>
        <Link to="/league-admin" className="mt-3 inline-flex rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white">
          Vai a User Admin (crea/join)
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

      {standings.length ? (
        <Card className="p-4">
          <SectionTitle>Classifica</SectionTitle>
          <div className="mt-1 text-[11px] text-slate-400">Clicca una squadra per vederne la rosa.</div>
          <div className="mt-2">
            <StandingsTable
              rows={standingRows(standings, selectedLeague?.team_name)}
              promoCount={4}
              selectedKey={selectedTeamId != null ? String(selectedTeamId) : null}
              onRowClick={(row) => setSelectedTeamId((cur) => (cur === Number(row.key) ? null : Number(row.key)))}
            />
          </div>
          {roster ? (
            <div className="mt-3 rounded-xl border border-slate-100 bg-slate-50 p-3">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-slate-800">{roster.team_name} · rosa</div>
                <span className="text-xs text-slate-500">
                  {roster.players.length} giocatori · valore {roster.players.reduce((s, p) => s + p.price, 0)}
                </span>
              </div>
              <div className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
                {[...roster.players]
                  .sort((a, b) => b.price - a.price)
                  .map((p) => (
                    <div key={p.player_id} className="flex items-center justify-between text-sm">
                      <span className="text-slate-700">{p.name}</span>
                      <span className="font-mono text-xs text-slate-500">{p.price}</span>
                    </div>
                  ))}
              </div>
            </div>
          ) : null}
        </Card>
      ) : null}

      <Card className="p-4">
        <SectionTitle>Partecipanti</SectionTitle>
        <div className="mt-3 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="py-2">#</th>
                <th>Squadra</th>
                <th>Manager</th>
              </tr>
            </thead>
            <tbody>
              {detail.teams.map((t, i) => (
                <tr key={t.team_id} className="border-t">
                  <td className="py-2 font-semibold">{i + 1}</td>
                  <td className="py-2 font-semibold">{t.name}</td>
                  <td className="py-2">{t.manager_username}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>Competizioni</SectionTitle>
        <div className="mt-2 space-y-2">
          {competitions.length ? (
            competitions.map((c) => (
              <div key={c.competition_id} className="flex items-center justify-between rounded-xl border px-3 py-2 text-sm">
                <div>
                  <div className="font-semibold">{c.name}</div>
                  <div className="text-xs text-slate-500">
                    {c.competition_type} · {c.status} · fixture {c.fixtures.finished}/{c.fixtures.total}
                  </div>
                </div>
                <Link to={`/competitions/${c.competition_id}`} className="rounded-xl bg-slate-200 px-3 py-2 text-xs font-semibold text-slate-800">
                  Calendario
                </Link>
              </div>
            ))
          ) : (
            <div className="text-sm text-slate-500">Nessuna competizione ancora creata.</div>
          )}
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>Gestione Lega</SectionTitle>
        <div className="mt-2 text-sm text-slate-600">Mercato, roster, competizioni e asta sono nella sezione League Admin (contesto lega).</div>
        <Link to="/league-admin?tab=league" className="mt-3 inline-flex rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white">
          Apri League Admin (lega)
        </Link>
      </Card>
    </div>
  );
}
