import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCompetitions, getLeagueDetail } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { Badge, Card, SectionTitle } from '../components/ui';
import type { CompetitionItem, LeagueDetail } from '../types/league';

export default function LeaguePage() {
  const { leagues, selectedLeagueId, selectedLeague } = useLeagueContext();
  const [detail, setDetail] = useState<LeagueDetail | null>(null);
  const [competitions, setCompetitions] = useState<CompetitionItem[]>([]);

  useEffect(() => {
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
        <SectionTitle>Lega Attiva</SectionTitle>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <div className="text-xl font-black">{detail.name}</div>
          <Badge tone={selectedLeague?.market_open ? 'green' : 'red'}>
            Mercato {selectedLeague?.market_open ? 'aperto' : 'chiuso'}
          </Badge>
        </div>
        <div className="mt-2 text-sm text-slate-600">Invite code: {detail.invite_code}</div>
      </Card>

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
