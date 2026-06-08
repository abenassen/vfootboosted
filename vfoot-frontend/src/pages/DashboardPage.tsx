import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getLeagueFixtures, getLeagueStandings } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import type { LeagueFixtureItem, LeagueStandingRow } from '../types/league';

export default function DashboardPage() {
  const { leagues, selectedLeagueId, selectedLeague } = useLeagueContext();
  const [standings, setStandings] = useState<LeagueStandingRow[]>([]);
  const [fixtures, setFixtures] = useState<LeagueFixtureItem[]>([]);

  useEffect(() => {
    if (!selectedLeagueId) {
      setStandings([]);
      setFixtures([]);
      return;
    }
    void getLeagueStandings(selectedLeagueId).then((r) => setStandings(r.standings)).catch(() => setStandings([]));
    void getLeagueFixtures(selectedLeagueId).then(setFixtures).catch(() => setFixtures([]));
  }, [selectedLeagueId]);

  if (!leagues.length) {
    return (
      <Card className="p-4">
        <SectionTitle>Benvenuto</SectionTitle>
        <div className="mt-2 text-sm text-slate-600">Non appartieni ancora a nessuna lega.</div>
        <Link to="/league-admin" className="mt-3 inline-flex rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white">
          Crea o unisciti a una lega
        </Link>
      </Card>
    );
  }
  if (!selectedLeagueId) {
    return <Card className="p-4 text-sm text-slate-600">Seleziona una lega dal selettore in alto.</Card>;
  }

  const myName = selectedLeague?.team_name ?? null;
  const myRow = myName ? standings.find((s) => s.team === myName) ?? null : null;
  const mine = fixtures.filter((f) => f.is_user_involved);
  const next = mine.filter((f) => f.status !== 'finished').sort((a, b) => a.round_no - b.round_no)[0] ?? null;
  const last = mine.filter((f) => f.status === 'finished').sort((a, b) => b.round_no - a.round_no)[0] ?? null;
  const feature = next ?? last;
  const seasonOver = !next && mine.length > 0;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <SectionTitle>{selectedLeague?.name}</SectionTitle>
            <div className="mt-1 text-2xl font-black">{myName ?? 'Spettatore'}</div>
            <div className="text-sm text-slate-500">
              {myRow ? `${myRow.rank}ª in classifica · ${myRow.points} pt` : 'Nessuna squadra associata'}
              {seasonOver ? ' · campionato concluso' : next ? ` · prossima: giornata ${next.round_no}` : ''}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/squad/formation">
              <Button>Formazione</Button>
            </Link>
            <Link to="/matches">
              <Button variant="secondary">Calendario</Button>
            </Link>
            <Link to="/league">
              <Button variant="secondary">Classifica</Button>
            </Link>
          </div>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="p-4">
          <SectionTitle>{next ? 'Prossima partita' : 'Ultima partita'}</SectionTitle>
          {feature ? (
            <div className="mt-2 flex items-center justify-between gap-2">
              <div>
                <div className="font-bold">
                  {feature.home_team.name} <span className="text-slate-400">vs</span> {feature.away_team.name}
                </div>
                <div className="text-sm text-slate-500">
                  Giornata {feature.round_no}
                  {feature.score ? ` · ${Math.round(feature.score.home_total)}–${Math.round(feature.score.away_total)}` : ''}
                </div>
              </div>
              <Link to={`/matches/${feature.fixture_id}`}>
                <Button variant="secondary" size="sm">
                  Dettagli
                </Button>
              </Link>
            </div>
          ) : (
            <div className="mt-2 text-sm text-slate-500">Nessuna partita per la tua squadra.</div>
          )}
        </Card>

        <Card className="p-4">
          <SectionTitle>Stato lega</SectionTitle>
          <ul className="mt-2 space-y-2 text-sm text-slate-700">
            <li className="flex items-center gap-2">
              <Badge tone={selectedLeague?.market_open ? 'green' : 'slate'}>
                Mercato {selectedLeague?.market_open ? 'aperto' : 'chiuso'}
              </Badge>
            </li>
            {myRow ? (
              <li>
                Bilancio: <b>{myRow.wins}</b>V · <b>{myRow.draws}</b>N · <b>{myRow.losses}</b>P — gol {myRow.goals_for}:{myRow.goals_against}
              </li>
            ) : null}
            {myRow ? <li>Punteggio Vfoot medio: <b>{myRow.avg_score_for.toFixed(1)}</b></li> : null}
            {seasonOver ? <li className="text-slate-500">Stagione conclusa — consulta classifica e calendario.</li> : null}
          </ul>
        </Card>
      </div>
    </div>
  );
}
