"""I rigori: come si decide una sfida che nemmeno i punteggi hanno deciso.

Non e' una monetina e non e' una simulazione col generatore casuale. Sono cinque
tiri, e ognuno ha due ingredienti che devono restare SEPARATI:

* **quanto e' bravo** — il voto puro del tiratore contro quello del portiere
  avversario. E' la parte che risente del merito, ed e' un confronto fra
  grandezze omogenee: tutti i ruoli hanno il voto puro centrato sul 6 con la
  stessa dispersione (misurato: portieri 5,96 · difensori 6,06 · centrocampisti
  6,01 · attaccanti 6,04), quindi la differenza fra i due significa qualcosa
  senza bisogno di coefficienti inventati. Il voto puro del portiere contiene
  gia' quanto ha parato, quindi non serve sommarci i gol evitati: sarebbe
  contarli due volte.
* **com'e' andata stavolta** — il tiro va o non va. Serve qualcosa di
  imprevedibile ma RIPRODUCIBILE, e non puo' essere il voto: e' su griglia di
  mezzi punti, ha due sole cifre decimali possibili e non e' un dado.

IL DADO SENZA IL GENERATORE CASUALE. L'ultima cifra dei metri palla al piede del
tiratore, in quella partita. E' uniforme sul serio (misurata su quarantamila
presenze: ogni cifra fra il 9,3% e il 10,5%), viene da cio' che il giocatore ha
davvero fatto in campo, e soprattutto e' la stessa domani: la serie di rigori si
puo' ricalcolare e da' lo stesso risultato. Con `random()` la stessa coppa
avrebbe un vincitore diverso a ogni ricalcolo.

CHI TIRA. I cinque col voto puro piu' alto fra chi e' sceso in campo. Nessuna
scelta in piu' per il fantallenatore, e il problema dei ruoli si risolve da se':
un difensore tira solo se ha giocato meglio degli altri, che e' giusto. Chi non
ha preso il voto non tira -- non c'era.

CHI E' SCESO IN CAMPO, e non chi era in distinta. La differenza non e' una
sottigliezza: un titolare senza voto viene rimpiazzato dal panchinaro, che il
voto ce l'ha. Leggendo la sola lista dei titolari sembrava che un terzo dei
giocatori fosse senza voto e che il 6% delle squadre non arrivasse a cinque
tiratori -- numeri che ad Andrea sono suonati subito falsi, e lo erano.
Sull'undici EFFETTIVO (titolari non sostituiti + panchinari entrati) le squadre
sotto i cinque tiratori sono ZERO su 404: l'82% ne ha undici, il caso peggiore
otto. Per questo l'undici effettivo lo calcola ``effective_xi`` e non ogni
chiamante per conto suo.

DUE CASI DI BORDO, misurati:
* il 3,5% delle squadre resta senza portiere col voto (il titolare e' s.v. e in
  panchina non c'era un secondo portiere da mandare dentro): il suo contributo
  diventa neutro (6.0) invece di penalizzare a caso;
* chi non ha i metri palla al piede (non e' nei dati) tira con la cifra del suo
  voto: peggio come dado, ma meglio che non tirare.
"""
from __future__ import annotations

# La conversione vera di un rigore, in tutti i campionati e in tutte le epoche:
# tre su quattro. E' la base da cui il merito sposta.
BASE = 0.75
# Quanto pesa un punto di scarto fra tiratore e portiere. Con scarti tipici di
# +-1,5 voti si va da 0,63 a 0,87: un buon tiratore contro un portiere in giornata
# storta segna quasi sempre, il contrario quasi mai, e nessuno dei due e' certo.
K = 0.08
FLOOR, CEILING = 0.55, 0.92
# Oltre i primi cinque si continua a oltranza, ma non all'infinito: finiti gli
# undici tiratori, la sfida torna al criterio successivo della catena (il fattore
# campo). Nei rigori veri non serve un limite perche' prima o poi qualcuno
# sbaglia; qui serve, perche' un tabellone che non si chiude blocca la coppa.
MAX_ROUNDS = 11
NEUTRAL_VOTE = 6.0


def effective_xi(team_payload: dict) -> list[dict]:
    """Chi ha davvero giocato: titolari non sostituiti + panchinari entrati.

    L'undici in distinta non e' l'undici che ha giocato, e confonderli fa
    sembrare senza voto gente che il voto ce l'ha -- il panchinaro entrato al
    posto del titolare s.v. e' esattamente il caso che le sostituzioni servono a
    coprire.
    """
    return ([l for l in team_payload.get("starters", []) if not l.get("replaced_by")]
            + [l for l in team_payload.get("bench", []) if l.get("entered")])


def _kickers(lines: list[dict]) -> list[dict]:
    """Chi tira, nell'ordine: i migliori voti puri di chi era in campo."""
    voted = [l for l in lines if l.get("voto_puro") is not None]
    # A parita' di voto decide il player_id, non l'ordine in cui la formazione e'
    # stata scritta: due squadre con gli stessi voti devono tirare nello stesso
    # ordine oggi e fra un anno.
    return sorted(voted, key=lambda l: (-float(l["voto_puro"]), l.get("player_id") or 0))


def _keeper_vote(lines: list[dict]) -> float:
    """Il voto del portiere schierato, o il 6 quando non c'e'.

    Il 3,5% delle squadre resta senza: il portiere titolare e' s.v. e in panchina
    non c'era un secondo portiere da mandare dentro. Trattarlo come uno zero
    sarebbe un disastro inventato; il 6 e' l'assenza di giudizio, che e'
    esattamente cio' che manca.
    """
    gk = next((l for l in lines
               if l.get("lineup_role") == "GK" and l.get("voto_puro") is not None), None)
    return float(gk["voto_puro"]) if gk else NEUTRAL_VOTE


def conversion(shooter_vote: float, keeper_vote: float) -> float:
    """Quanto vale questo rigore, fra FLOOR e CEILING."""
    p = BASE + K * (float(shooter_vote) - float(keeper_vote))
    return max(FLOOR, min(CEILING, p))


def _roll(line: dict, dice: dict[int, tuple[float, int]]) -> float:
    """Il dado, fra 0 e 1: due cifre prese da cio' che il tiratore ha fatto in campo.

    La prima e' l'ultima cifra dei metri palla al piede, la seconda l'ultima dei
    tocchi. Servono ENTRAMBE: con una sola il dado ha dieci facce, e dieci facce
    trasformano una probabilita' di 0,75 in una conversione dell'80% -- misurato,
    non temuto. Con due facce da dieci l'errore di grana scende all'1%.

    Nessuna delle due cifre e' scelta da qualcuno, tutte e due vengono da una
    misura reale, e domani sono le stesse: la serie si puo' ricalcolare.

    Senza quei dati si ripiega sulla cifra del voto -- un dado peggiore, ma una
    sfida decisa e' meglio di un tabellone bloccato.
    """
    pid = line.get("player_id")
    if pid not in dice:
        return (int(round(float(line.get("voto_puro") or NEUTRAL_VOTE) * 10)) % 10) / 10.0
    metres, touches = dice[pid]
    return ((int(round(float(metres) * 10)) % 10) * 10 + int(touches) % 10) / 100.0


def shootout(home_lines: list[dict], away_lines: list[dict],
             dice: dict[int, tuple[float, int]] | None = None) -> dict:
    """La serie, tiro per tiro. Deterministica: stessi dati, stesso risultato.

    ``dice`` e' {player_id: (metri palla al piede, tocchi)} della giornata; senza,
    ogni tiro ripiega sul dado di riserva. Restituisce il tabellino della serie e il
    vincitore, o ``winner`` None se dopo undici tiri per parte sono ancora pari —
    caso in cui decide il criterio successivo della catena.
    """
    dice = dice or {}
    sides = {"home": _kickers(home_lines), "away": _kickers(away_lines)}
    keeper = {"home": _keeper_vote(home_lines), "away": _keeper_vote(away_lines)}
    kicks: dict[str, list[dict]] = {"home": [], "away": []}
    score = {"home": 0, "away": 0}

    for i in range(MAX_ROUNDS):
        for side in ("home", "away"):
            takers = sides[side]
            if i >= len(takers):
                continue
            line = takers[i]
            p = conversion(line["voto_puro"], keeper["away" if side == "home" else "home"])
            r = _roll(line, dice)
            scored = r < p
            score[side] += int(scored)
            kicks[side].append({
                "player_id": line.get("player_id"),
                "name": line.get("name"),
                "voto_puro": float(line["voto_puro"]),
                "p": round(p, 3),
                "roll": r,
                "scored": scored,
            })
        # Finiti i cinque si va A OLTRANZA: uno per parte, e vince chi si trova
        # avanti A PARITA' DI TIRI BATTUTI. Il controllo va fatto solo a giro
        # chiuso, altrimenti chi tira per primo vincerebbe a meta' turno -- gli
        # basterebbe segnare, senza dare all'altro la sua occasione di pareggiare.
        if i + 1 >= 5 and score["home"] != score["away"] \
                and len(kicks["home"]) == len(kicks["away"]):
            break

    winner = None
    if score["home"] != score["away"]:
        winner = "home" if score["home"] > score["away"] else "away"
    return {"home": kicks["home"], "away": kicks["away"],
            "home_goals": score["home"], "away_goals": score["away"],
            "winner": winner}
