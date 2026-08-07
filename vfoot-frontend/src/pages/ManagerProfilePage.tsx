import { Link, useParams } from 'react-router-dom';
import { Badge, Button, Card, SectionTitle } from '../components/ui';
import Avatar from '../components/Avatar';
import Crest from '../components/Crest';
import HonoursBoard from '../components/HonoursBoard';
import { getManagerProfile } from '../api';
import { useAsync } from '../utils/useAsync';
import { useLeagueContext } from '../league/LeagueContext';

/** La scheda pubblica di un fantallenatore: chi è, dove gioca, cosa ha vinto.
 *
 *  Esiste perché queste tre cose non appartengono a una lega. Una rosa sì — è la
 *  proprietà di UNA squadra in UNA lega e finisce con quella — mentre il
 *  fantallenatore attraversa i campionati e i suoi trofei con lui. Finché l'albo
 *  d'oro stava sulla pagina delle rose sembrava una cosa della lega corrente, e
 *  per vedere quello di un avversario bisognava passare dalla sua rosa, che è
 *  tutt'altra domanda.
 *
 *  Da qui in poi la home lega distingue i due clic: sulla SQUADRA si va alla rosa,
 *  sul NOME si arriva qui.
 *
 *  Cosa non c'è, di proposito: l'email, e ogni altro modo di raggiungerlo. La
 *  pagina la apre chiunque condivida una lega, quindi porta solo quello che uno
 *  mette in campo. E le leghe elencate sono solo quelle in comune — chi altro
 *  frequenta non sono affari di chi guarda (il server lo impone comunque).
 */
export default function ManagerProfilePage() {
  const { userId } = useParams();
  const { selectedLeagueId } = useLeagueContext();
  const id = Number(userId);
  const { data, loading, error } = useAsync(
    () => (Number.isFinite(id) ? getManagerProfile(id) : Promise.reject(new Error('Utente non valido'))),
    [id],
  );

  if (loading) return <div className="text-sm text-slate-500">Caricamento profilo…</div>;
  if (error || !data) {
    // Un 404 qui vuol dire "non avete leghe in comune", ed è il caso normale, non
    // un guasto: si dice così invece di mostrare un errore tecnico.
    return (
      <Card className="p-6 text-center">
        <div className="text-3xl">🔒</div>
        <div className="mt-2 font-semibold text-slate-700">Questo profilo non è visibile</div>
        <div className="mt-1 text-sm text-slate-500">
          Puoi vedere la scheda dei fantallenatori con cui condividi almeno una lega.
        </div>
        <Link to="/home" className="mt-4 inline-block">
          <Button size="sm" variant="secondary">← Home lega</Button>
        </Link>
      </Card>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-4">
            <Avatar descriptor={data.avatar} username={data.username} size={64} />
            <div className="min-w-0">
              <SectionTitle>Fantallenatore</SectionTitle>
              <div className="mt-0.5 text-2xl font-black leading-tight">{data.username}</div>
              <div className="text-sm text-slate-500">
                {data.leagues.length} {data.leagues.length === 1 ? 'lega' : 'leghe'}
                {data.joined_at ? ` · iscritto dal ${new Date(data.joined_at).toLocaleDateString('it-IT')}` : ''}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/home">
              <Button size="sm" variant="ghost">← Home lega</Button>
            </Link>
            {/* Sulla PROPRIA scheda il passaggio alle impostazioni: è la stessa
                persona, ma avatar, username e password si cambiano di là. */}
            {data.is_self ? (
              <Link to="/profilo">
                <Button size="sm" variant="secondary">⚙️ Il tuo profilo</Button>
              </Link>
            ) : null}
          </div>
        </div>
      </Card>

      {/* Prima delle leghe: quello che ha VINTO dice di un avversario più di
          quante squadre schiera, ed è il motivo per cui si apre questa pagina. */}
      <HonoursBoard userId={data.user_id} name={data.username} own={data.is_self} />

      <Card className="p-4">
        <SectionTitle>{data.is_self ? 'Le tue leghe' : 'Leghe in comune'}</SectionTitle>
        {data.leagues.length ? (
          <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
            {data.leagues.map((l) => {
              const here = l.league_id === selectedLeagueId;
              // La rosa si apre solo dentro la lega selezionata: la pagina rose
              // legge la lega dal contesto, e un link da un'altra mostrerebbe la
              // rosa sbagliata invece di dare errore.
              const roster = here && l.team_id ? `/teams/${l.team_id}` : null;
              const body = (
                <>
                  <Crest descriptor={l.team_crest} teamName={l.team_name ?? l.name} size={30} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-slate-800">
                      {l.team_name ?? <span className="italic text-slate-400">nessuna squadra</span>}
                    </span>
                    <span className="block truncate text-xs text-slate-500">{l.name}</span>
                  </span>
                  {l.role === 'admin' ? <Badge tone="blue">admin</Badge> : null}
                </>
              );
              return roster ? (
                <Link
                  key={l.league_id}
                  to={roster}
                  className="flex items-center gap-2 rounded-xl border border-slate-100 px-3 py-2 transition hover:bg-slate-50"
                >
                  {body}
                </Link>
              ) : (
                <div
                  key={l.league_id}
                  className="flex items-center gap-2 rounded-xl border border-slate-100 px-3 py-2"
                >
                  {body}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="mt-2 text-sm text-slate-500">
            {data.is_self ? 'Non fai ancora parte di nessuna lega.' : 'Nessuna lega in comune.'}
          </div>
        )}
      </Card>
    </div>
  );
}
