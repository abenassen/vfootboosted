import { Link } from 'react-router-dom';
import clsx from 'clsx';
import Avatar from '../Avatar';
import { Card, SectionTitle } from '../ui';
import { useAuth } from '../../auth/AuthContext';
import type { FixtureManager } from '../../types/league';
import type { MatchResult } from './MatchScoreHeader';

/** I due fantallenatori in fondo al tabellino.
 *
 *  Sopra ci sono novanta righe di numeri; qui sotto c'è chi le ha schierate. È
 *  l'unico punto della partita in cui l'avatar è grande abbastanza da guardarlo,
 *  ed è il motivo per cui esiste questa striscia: la faccia che uno si compone
 *  nel profilo non serve a niente se compare solo a 24 pixel in un menù.
 *
 *  Le due facce stanno nello stesso ordine dei nomi nel punteggio — casa a
 *  sinistra, ospiti a destra — e il vincitore è in grassetto con lo stesso
 *  criterio dell'intestazione: una regola sola per tutta la pagina.
 *
 *  Non si disegna niente se manca uno dei due: una sola faccia in una sfida a due
 *  non è mezzo tabellino, è un errore che sembra un dato. */
export function MatchManagers({
  home,
  away,
  homeTeam,
  awayTeam,
  result,
}: {
  home?: FixtureManager | null;
  away?: FixtureManager | null;
  homeTeam: string;
  awayTeam: string;
  result?: MatchResult;
}) {
  const { user } = useAuth();
  if (!home || !away) return null;
  return (
    <Card className="p-4">
      <SectionTitle>Gli allenatori</SectionTitle>
      <div className="mt-3 flex items-center justify-center gap-2 sm:gap-6">
        <ManagerSide
          side="home"
          manager={home}
          teamName={homeTeam}
          winner={result === 'home'}
          isSelf={user?.id === home.user_id}
        />
        {/* Sul telefono le due colonne sono alte (faccia, nome, squadra) e un "vs"
            centrato su tutta l'altezza finiva sotto le facce, all'altezza dei
            nomi: qui è appeso in alto, in mezzo agli occhi dei due. */}
        <div className="mt-5 shrink-0 self-start font-cond text-xs font-bold uppercase tracking-widest text-ink-faint sm:mt-0 sm:self-center">
          vs
        </div>
        <ManagerSide
          side="away"
          manager={away}
          teamName={awayTeam}
          winner={result === 'away'}
          isSelf={user?.id === away.user_id}
        />
      </div>
    </Card>
  );
}

function ManagerSide({
  side,
  manager,
  teamName,
  winner,
  isSelf,
}: {
  side: 'home' | 'away';
  manager: FixtureManager;
  teamName: string;
  winner: boolean;
  isSelf: boolean;
}) {
  return (
    <Link
      to={`/fantallenatori/${manager.user_id}`}
      title={`Scheda di ${manager.username}`}
      className={clsx(
        // Sul telefono la faccia sta SOPRA il nome: di fianco restavano una
        // sessantina di pixel per il testo e ogni nome utente finiva in
        // «classicd…». In colonna il nome ha tutta la mezza scheda.
        'group flex min-w-0 flex-1 flex-col items-center gap-2 rounded-xl px-1 py-1 text-center',
        // Da tablet in su le due facce si guardano attraverso il "vs", nello
        // stesso posto in cui i due nomi si guardano attraverso il punteggio là
        // in cima: la casa stringe verso il centro da sinistra, gli ospiti da
        // destra. Messe agli estremi opposti della scheda sembravano due voci di
        // un elenco, non i due che si sono affrontati.
        'sm:flex-row sm:justify-start sm:gap-3',
        side === 'home' ? 'sm:flex-row-reverse sm:text-right' : 'sm:text-left',
      )}
    >
      <Avatar
        descriptor={manager.avatar}
        username={manager.username}
        size={56}
        className={clsx(
          // L'anello verde è la stessa cosa che dice il grassetto sul nome e il
          // verde sul gol in cima: chi ha vinto. Su un pareggio nessuno dei due.
          'ring-2 ring-offset-2 ring-offset-surface',
          winner ? 'ring-good' : 'ring-line',
        )}
      />
      <span className="min-w-0 max-w-full">
        <span
          className={clsx(
            'block truncate text-sm group-hover:underline',
            winner ? 'font-black text-ink' : 'font-semibold text-ink-soft',
          )}
        >
          {manager.username}
          {isSelf ? <span className="ml-1.5 text-[10px] font-bold uppercase text-good">tu</span> : null}
        </span>
        {/* Il nome della squadra è già in cima: qui serve solo a dire di chi è
            questa faccia, quindi sta piccolo e non si clicca per conto suo. */}
        <span className="block truncate text-[11px] text-ink-faint">{teamName}</span>
      </span>
    </Link>
  );
}
