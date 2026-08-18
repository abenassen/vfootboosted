import { useState } from 'react';
import { reportCrestImage, revokeCrestImage } from '../api';
import Crest from './Crest';
import { Button, Card, SectionTitle } from './ui';
import { crestImageHash, parseCrest } from '../utils/crest';
import type { LeagueTeam } from '../types/league';

/** La moderazione degli stemmi caricati, dalla parte di chi guarda.
 *
 *  Non c'è un classificatore automatico e non ci sarà: su una macchina con un
 *  vCPU un modello costa più di quanto valga, e un servizio esterno costa soldi
 *  e regala falsi positivi. La sproporzione è dall'altra parte — uno stemma lo
 *  vedono i dieci di una lega, che si conoscono, e sono loro ad accorgersene
 *  prima e meglio di qualunque filtro.
 *
 *  Nota su chi decide cosa: il pulsante compare SOLO sugli stemmi caricati. Su
 *  uno composto non ci sarebbe niente da segnalare — le forme e i colori sono i
 *  nostri — e mostrarlo comunque insegnerebbe che si può segnalare una squadra
 *  invece di un'immagine.
 *
 *  Quale impronta si segnala la sa il client, che il descrittore lo ha appena
 *  letto per disegnarlo. Il server non lo apre: verifica solo che qualcuno in
 *  quella lega la nomini, ed è quella la sua autorizzazione.
 */

/** Il segnalatore, accanto allo stemma di un'altra squadra. */
export function CrestReportButton({
  leagueId,
  descriptor,
  className,
}: {
  leagueId: number;
  descriptor?: string | null;
  className?: string;
}) {
  const hash = crestImageHash(parseCrest(descriptor)?.img);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [state, setState] = useState<'idle' | 'sending' | 'done'>('idle');
  const [error, setError] = useState<string | null>(null);

  if (!hash) return null;

  async function invia() {
    setState('sending');
    setError(null);
    try {
      await reportCrestImage(leagueId, hash, reason.trim());
      setState('done');
      setOpen(false);
    } catch (e) {
      setState('idle');
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (state === 'done') {
    return (
      <div className={className}>
        <span className="text-xs text-ink-faint">Segnalazione inviata, grazie.</span>
      </div>
    );
  }

  return (
    <div className={className}>
      {open ? (
        <div className="space-y-2 rounded-xl border border-line p-3">
          <div className="text-xs font-semibold text-ink">Perché lo segnali?</div>
          <input
            className="w-full rounded-lg border px-2 py-1 text-sm"
            value={reason}
            maxLength={300}
            placeholder="Facoltativo: due parole all'admin"
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="flex gap-2">
            <Button size="sm" disabled={state === 'sending'} onClick={() => void invia()}>
              {state === 'sending' ? 'Invio…' : 'Segnala'}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
              Annulla
            </Button>
          </div>
          {error ? <div className="text-xs text-bad">{error}</div> : null}
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="text-xs text-ink-faint underline hover:text-ink"
        >
          ⚑ Segnala lo stemma
        </button>
      )}
    </div>
  );
}

/** Il pannello dell'admin: gli stemmi caricati in questa lega, e il pulsante per
 *  toglierli.
 *
 *  L'elenco NON viene da un endpoint: le squadre della lega il client le ha già,
 *  e il descrittore lo sa leggere lui. Chiedere al server «quali squadre hanno
 *  caricato un'immagine» vorrebbe dire insegnargli a interpretare un campo che
 *  ha sempre trattato come testo — per una lista di dieci righe che qui si
 *  ricava con un filtro.
 */
export function CrestModerationPanel({
  leagueId,
  teams,
}: {
  leagueId: number;
  teams: LeagueTeam[];
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tolti, setTolti] = useState<string[]>([]);

  const caricati = teams
    .map((t) => ({ team: t, hash: crestImageHash(parseCrest(t.crest)?.img) }))
    .filter((r) => r.hash !== '' && !tolti.includes(r.hash));

  async function rimuovi(hash: string, teamName: string) {
    if (busy) return;
    setBusy(hash);
    setError(null);
    try {
      await revokeCrestImage(leagueId, hash, `rimosso dall'admin (${teamName})`);
      // Sparisce dall'elenco senza ricaricare la lega: il descrittore della
      // squadra non è cambiato — è cambiato cosa risponde a quell'indirizzo — e
      // un refetch riporterebbe indietro esattamente le stesse righe.
      setTolti((prev) => [...prev, hash]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card className="p-4">
      <SectionTitle>Stemmi caricati</SectionTitle>
      <div className="mt-1 text-xs text-ink-faint">
        Le immagini caricate dai partecipanti. Toglierne una non cancella il loro
        stemma: torna quello composto che c'è sotto, e possono rifarlo quando
        vogliono. La rimozione vale ovunque quell'immagine compaia.
      </div>

      {caricati.length === 0 ? (
        <div className="mt-3 text-sm text-ink-faint">
          Nessuno ha caricato un'immagine: tutti gli stemmi sono composti.
        </div>
      ) : (
        <ul className="mt-3 space-y-2">
          {caricati.map(({ team, hash }) => (
            <li
              key={hash}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line px-3 py-2"
            >
              <div className="flex items-center gap-3">
                <Crest descriptor={team.crest} teamName={team.name} size={40} />
                <div className="min-w-0">
                  <div className="text-sm font-bold text-ink">{team.name}</div>
                  <div className="text-xs text-ink-faint">{team.manager_username}</div>
                </div>
              </div>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy === hash}
                onClick={() => void rimuovi(hash, team.name)}
              >
                {busy === hash ? 'Tolgo…' : 'Rimuovi'}
              </Button>
            </li>
          ))}
        </ul>
      )}

      {tolti.length ? (
        <div className="mt-3 text-xs text-ink-faint">
          {tolti.length === 1 ? 'Un\'immagine rimossa' : `${tolti.length} immagini rimosse`}. Le
          squadre mostrano di nuovo il loro stemma composto.
        </div>
      ) : null}
      {error ? <div className="mt-3 text-sm text-bad">{error}</div> : null}
    </Card>
  );
}
