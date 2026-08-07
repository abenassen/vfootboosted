import { Link, useParams } from 'react-router-dom';
import { Button, Card, SectionTitle } from '../components/ui';
import { useAsync } from '../utils/useAsync';
import { getTeamLineup } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import RosterView from '../components/RosterView';
import Crest from '../components/Crest';

/** Another participant's roster, in the same structured view as one's own — the
 *  read-only counterpart of the Squad page, reached from the League page. The
 *  chosen XI is withheld by the backend; only the roster is shown. */
export default function TeamRosterPage() {
  const { teamId } = useParams();
  const { selectedLeagueId } = useLeagueContext();
  const { data, loading, error } = useAsync(
    () =>
      selectedLeagueId && teamId
        ? getTeamLineup(selectedLeagueId, null, null, Number(teamId))
        : Promise.reject(new Error('Parametri mancanti')),
    [selectedLeagueId, teamId],
  );

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega.</div>;
  if (loading) return <div className="text-sm text-slate-500">Caricamento rosa…</div>;
  if (error || !data) return <div className="text-sm text-red-600">Errore: {error?.message ?? '…'}</div>;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-start justify-between gap-3">
          {/* Crest and manager, not just the name: switching between teams from
              the strip changes only this header, and a line of text alone made
              it easy to lose track of whose roster is on screen. */}
          <div className="flex items-center gap-3">
            <Crest descriptor={data.team.crest} teamName={data.team.name} size={48} />
            <div>
              <SectionTitle>Rosa</SectionTitle>
              <div className="mt-0.5 text-xl font-black">{data.team.name}</div>
              <div className="text-sm text-slate-500">
                {data.team.manager ? (
                  <>
                    Fantallenatore:{' '}
                    {/* Cliccabile: da qui si arriva alla SUA scheda, dove stanno
                        l'albo d'oro e le altre squadre che schiera. Prima erano
                        appesi a questa pagina, che è la proprietà di una squadra
                        in una lega e non del fantallenatore. */}
                    {data.team.manager_user_id ? (
                      <Link
                        to={`/fantallenatori/${data.team.manager_user_id}`}
                        className="font-bold text-slate-700 hover:underline"
                      >
                        {data.team.manager}
                      </Link>
                    ) : (
                      <b className="text-slate-700">{data.team.manager}</b>
                    )}{' '}
                    ·{' '}
                  </>
                ) : null}
                {data.roster.length} giocatori
              </div>
            </div>
          </div>
          <Link to="/home">
            <Button variant="ghost" size="sm">
              ← Home lega
            </Button>
          </Link>
        </div>
      </Card>
      {/* Niente albo d'oro qui. Una rosa è la proprietà di UNA squadra in UNA
          lega e finisce con lei; i trofei di un fantallenatore no — si accumulano
          attraverso i campionati — e messi su questa pagina sembravano una cosa
          della lega corrente. Adesso stanno sulla sua scheda, linkata dal nome
          qui sopra e dal blocco Partecipanti della home lega. */}
      <RosterView data={data} />
    </div>
  );
}
