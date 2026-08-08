"""L'albo d'oro: cosa è stato vinto, da chi, e quando.

Un premio è una regola finché non diventa un fatto. ``competition_prizes`` possiede
la regola e sa dire chi la sta soddisfacendo; qui si passa dall'una all'altro: si
ASSEGNA, si salva, e da quel momento leggere l'albo d'oro è una query.

TRE DECISIONI CHE VALE LA PENA CONOSCERE
----------------------------------------
**Si assegna alla fine della competizione, e in un colpo solo.** Un premio
appartiene alla competizione: è la sua conclusione ad assegnarlo, anche quando il
vincitore era matematicamente già deciso — il primo di un girone si sa a metà
torneo, ma lo vince quando il torneo finisce. Una regola sola e un momento solo,
invece di "ogni premio quando la sua condizione si avvera", che sarebbe stato
più preciso e molto più difficile da raccontare.

**Si salva.** La versione precedente derivava il vincitore dai risultati a OGNI
lettura, e costava 287 ms per aprire la home e 403 per un albo d'oro — in crescita
con la carriera del fantallenatore, perché rileggeva i tabellini di ogni
competizione di ogni lega in cui avesse mai giocato. Il ricalcolo perpetuo serviva
a non andare mai stantii, ma quella è una cosa che va fatta QUANDO un risultato
cambia, non a ogni apertura di pagina. Il rischio di un dato salvato non è che
esista: è che nessuno lo aggiorni. Perciò esiste ``review_league``, e la rettifica
DICE cosa ha cambiato invece di riscriverlo di nascosto.

**La data è quella del registro, non dell'orologio.** Un premio è del giorno in cui
è stata conclusa la giornata che l'ha deciso. Leggere ``timezone.now()`` daterebbe
a oggi anche i trofei di una stagione riempita a posteriori.
"""
from __future__ import annotations

from vfoot.models import (
    AwardedPrize,
    CompetitionStage,
    FantasyCompetition,
    FantasyFixture,
    FantasyTeam,
)
from vfoot.services.competition_prizes import (
    competition_fixtures,
    describe_condition,
    prize_scope,
    prize_winner_team_ids,
)


# --------------------------------------------------------------------------- #
# Quando una competizione è finita, e quando lo è stata.                       #
# --------------------------------------------------------------------------- #
def _concluded_at(fixtures):
    """Quando l'ultima di queste partite è stata conteggiata, o None se una non lo
    è mai stata.

    None è la risposta onesta per una competizione i cui risultati sono stati
    scritti da qualcosa che non è una conclusione (un seed, una simulazione): non
    ha una data, e inventarne una la manderebbe in cima a un elenco cronologico
    a cui non appartiene.
    """
    stamps = [fx.fantasy_matchday.concluded_at if fx.fantasy_matchday_id else None
              for fx in fixtures]
    return max(stamps) if stamps and all(s is not None for s in stamps) else None


def is_complete(competition: FantasyCompetition, fixtures=None) -> bool:
    """C'è ancora del calcio in questa competizione?

    Due prove, e la seconda è quella che si dimentica: un tabellone sorteggia il
    turno successivo solo quando il precedente è finito, quindi "tutte le partite
    che esistono sono finite" è vero a ogni turno di una coppa.
    """
    fixtures = competition_fixtures(competition) if fixtures is None else fixtures
    if not fixtures:
        return False
    if any(fx.status != FantasyFixture.STATUS_FINISHED for fx in fixtures):
        return False
    drawn = {fx.stage_id for fx in fixtures}
    planned = set(CompetitionStage.objects.filter(competition=competition)
                  .values_list("id", flat=True))
    return not (planned - drawn)


# --------------------------------------------------------------------------- #
# L'assegnazione: il momento in cui la regola diventa un fatto.                #
# --------------------------------------------------------------------------- #
def assign_for_competition(competition: FantasyCompetition, fixtures=None) -> list[dict]:
    """Assegna i premi di una competizione FINITA. Idempotente.

    Restituisce i cambiamenti: ``[{"prize", "added": [team_id], "removed": [...]}]``,
    vuoto quando non c'era nulla da fare. È la stessa funzione che usa la
    conclusione e che usa la rettifica — la seconda esiste solo perché la prima
    possa essere ripetuta senza danno.
    """
    fixtures = competition_fixtures(competition) if fixtures is None else fixtures
    if not is_complete(competition, fixtures):
        return []

    changes: list[dict] = []
    for prize in competition.prizes.select_related("source_stage").all():
        winners = set(prize_winner_team_ids(prize, fixtures))
        current = set(AwardedPrize.objects.filter(prize=prize).values_list("team_id", flat=True))
        if winners == current:
            continue
        # Datato da CIÒ CHE LO HA DECISO: la finale finisce prima della
        # competizione (può seguirla una finale di consolazione), e un premio di
        # classifica è deciso dall'ultimo turno della classifica che legge.
        at = _concluded_at(prize_scope(prize, fixtures))
        AwardedPrize.objects.filter(prize=prize).exclude(team_id__in=winners).delete()
        # Nome e stemma COPIATI qui e mai piu' riletti: una squadra si ribattezza
        # quando vuole, e senza questa copia il ribattezzo riscriverebbe anche le
        # coppe vinte tre stagioni fa. Solo per le righe nuove — un premio gia'
        # assegnato tiene l'identita' del giorno in cui fu vinto, che e' il punto.
        identities = {
            tid: (name, crest)
            for tid, name, crest in FantasyTeam.objects
            .filter(id__in=winners - current).values_list("id", "name", "crest")
        }
        for tid in sorted(winners - current):
            name, crest = identities.get(tid, ("", ""))
            AwardedPrize.objects.update_or_create(
                prize=prize, team_id=tid,
                defaults={"awarded_at": at, "team_name": name, "team_crest": crest})
        AwardedPrize.objects.filter(prize=prize).update(awarded_at=at)
        changes.append({"prize": prize,
                        "added": sorted(winners - current),
                        "removed": sorted(current - winners)})
    return changes


def complete_competition(competition: FantasyCompetition, fixtures=None) -> dict | None:
    """Chiude una competizione: bandiera, data e premi, in un gesto solo.

    None se non è finita. Chiamata dalla conclusione della giornata; è ciò che
    trasforma il trentottesimo clic in un evento diverso dagli altri trentasette.
    """
    fixtures = competition_fixtures(competition) if fixtures is None else fixtures
    if not is_complete(competition, fixtures):
        return None

    changes = assign_for_competition(competition, fixtures)
    at = _concluded_at(fixtures)
    fields = []
    if competition.status != FantasyCompetition.STATUS_DONE:
        competition.status = FantasyCompetition.STATUS_DONE
        fields.append("status")
    if competition.completed_at != at:
        competition.completed_at = at
        fields.append("completed_at")
    if fields:
        competition.save(update_fields=fields)
    return {"competition": competition, "at": at, "changes": changes}


def review_league(league) -> list[dict]:
    """Ricontrolla i premi di ogni competizione finita della lega, e riferisce.

    Il contrappeso al fatto di salvare: la si chiama dove un risultato può
    cambiare dopo che è stato contato (un ricalcolo, un voto d'ufficio). Se un
    trofeo cambia mano lo dice a chi ha appena premuto il pulsante, invece di
    riscriverlo in silenzio — che era il difetto della versione derivata: la
    rettifica funzionava, ma nessuno la vedeva accadere.
    """
    out = []
    for comp in FantasyCompetition.objects.filter(league=league).prefetch_related("prizes"):
        result = complete_competition(comp)
        if result and result["changes"]:
            out.extend({"competition": comp, **c} for c in result["changes"])
    return out


def reopen_incomplete(league) -> list[dict]:
    """Il contrario di ``complete_competition``, per le competizioni in cui è
    tornato ad esserci del calcio da giocare.

    Serve quando una giornata viene RIAPERTA — una simulazione che torna indietro,
    una rettifica che annulla una conclusione. Riaprire la giornata da sola non
    basta: la finale che si giocava lì torna da giocare, ma la coppa restava
    ``done`` con il suo trofeo in bacheca, e il risultato era una lega in cui il
    campionato risultava vinto con l'ultima giornata ancora da contare — e in cui
    la conclusione finale non annunciava più niente, perché per la banca dati non
    c'era più niente da chiudere.

    La prova è la stessa di ``is_complete``: si guarda se c'è ancora del calcio,
    non che cosa dice la bandiera. Restituisce, per ogni competizione riaperta,
    i premi che ha dovuto ritirare — perché anche togliere un trofeo è una cosa
    che va DETTA, non fatta di nascosto.
    """
    out = []
    for comp in FantasyCompetition.objects.filter(league=league).prefetch_related("prizes"):
        fixtures = competition_fixtures(comp)
        if is_complete(comp, fixtures):
            continue
        for stage in CompetitionStage.objects.filter(competition=comp,
                                                     status=CompetitionStage.STATUS_DONE):
            own = [fx for fx in fixtures if fx.stage_id == stage.id]
            if not own or any(fx.status != FantasyFixture.STATUS_FINISHED for fx in own):
                stage.status = CompetitionStage.STATUS_ACTIVE
                stage.save(update_fields=["status"])
        removed = sorted(AwardedPrize.objects.filter(prize__competition=comp)
                         .values_list("team_id", flat=True))
        AwardedPrize.objects.filter(prize__competition=comp).delete()
        was_done = comp.status == FantasyCompetition.STATUS_DONE or comp.completed_at
        if was_done:
            comp.status = FantasyCompetition.STATUS_ACTIVE
            comp.completed_at = None
            comp.save(update_fields=["status", "completed_at"])
        if was_done or removed:
            out.append({"competition": comp, "removed": removed})
    return out


# --------------------------------------------------------------------------- #
# Le letture: adesso sono query.                                               #
# --------------------------------------------------------------------------- #
def _frozen_identity(name, crest, team) -> tuple[str | None, str]:
    """(nome, stemma) di chi ha vinto: quelli congelati, o la squadra viva.

    IL NOME decide per tutti e due, e la ragione vale la riga in piu': lo stemma
    congelato puo' benissimo essere VUOTO — nessuno aveva ancora aperto l'editor,
    e la pagina disegna uno stemma a partire dal nome — mentre il nome di una
    squadra non lo e' mai. Trattando ogni campo per conto suo con un ``or``, una
    squadra senza stemma al momento della vittoria si ritrovava addosso quello
    che si e' scelta dopo: il nome era quello giusto e lo stemma no, che e'
    peggio di sbagliarli entrambi perche' sembra funzionare.
    """
    if name:
        return name, crest or ""
    return (team.name if team else None), (team.crest if team else "")


def _awards_qs():
    return (AwardedPrize.objects
            .select_related("prize", "prize__competition", "prize__competition__league",
                            "prize__source_stage", "team")
            .order_by("-awarded_at", "prize_id"))


def league_honours(league) -> dict:
    """Le competizioni finite della lega e i premi che hanno assegnato.

    ``winners`` porta l'identita' CONGELATA di chi ha vinto — com'era il giorno
    dell'assegnazione, non com'e' adesso. ``team_ids`` resta accanto perche' un
    id non invecchia e serve a chi deve linkare la squadra di oggi.
    """
    finished = [
        {"competition": c, "at": c.completed_at}
        for c in FantasyCompetition.objects.filter(
            league=league, status=FantasyCompetition.STATUS_DONE).order_by("-completed_at", "id")
    ]
    awards: dict[int, dict] = {}
    for a in _awards_qs().filter(prize__competition__league=league):
        row = awards.setdefault(a.prize_id, {"prize": a.prize, "competition": a.prize.competition,
                                             "team_ids": [], "winners": [], "at": a.awarded_at})
        row["team_ids"].append(a.team_id)
        name, crest = _frozen_identity(a.team_name, a.team_crest, a.team)
        row["winners"].append({"team_id": a.team_id, "name": name, "crest": crest})
    return {"finished": finished, "awards": list(awards.values())}


def manager_honours(user, *, leagues=None) -> list[dict]:
    """L'albo d'oro di un fantallenatore: ogni premio vinto da una sua squadra.

    Fra leghe diverse di proposito. Una lega dura una stagione e un fantallenatore
    no: un palmarès che ricomincia ogni agosto non varrebbe niente, e il senso
    della cosa è proprio che si accumuli. ``leagues`` lo restringe a quelle che chi
    guarda può vedere.
    """
    qs = _awards_qs().filter(team__manager__user=user)
    if leagues is not None:
        qs = qs.filter(prize__competition__league__in=leagues)
    rows = list(qs)
    # Quanti hanno vinto lo STESSO premio: un primato a pari merito non deve
    # leggersi come una vittoria netta. Una query sola per tutti.
    shared = {}
    for prize_id, team_id in (AwardedPrize.objects
                              .filter(prize_id__in={a.prize_id for a in rows})
                              .values_list("prize_id", "team_id")):
        shared.setdefault(prize_id, set()).add(team_id)
    return [{
        "prize": a.prize,
        "competition": a.prize.competition,
        "team": a.team,
        "team_name": a.team_name,
        "team_crest": a.team_crest,
        "at": a.awarded_at,
        "shared_with": len(shared.get(a.prize_id, ())) - 1,
    } for a in rows]


def prize_winners(competition: FantasyCompetition) -> dict[int, list[int]]:
    """{prize_id: [team_id]} già assegnati, per la pagina della competizione."""
    out: dict[int, list[int]] = {}
    for prize_id, team_id in (AwardedPrize.objects
                              .filter(prize__competition=competition)
                              .values_list("prize_id", "team_id")):
        out.setdefault(prize_id, []).append(team_id)
    return out


def serialize_award(award: dict) -> dict:
    """Una riga di albo d'oro, come la vuole il browser.

    Nome e stemma sono quelli CONGELATI all'assegnazione, non quelli che la
    squadra porta oggi: un albo d'oro racconta com'erano le cose allora, e
    leggerli dal vivo faceva comparire ogni trofeo con lo stemma di adesso. Sulle
    righe piu' vecchie di questi campi si ricade sulla squadra viva, che e'
    esattamente la risposta che si dava prima.
    """
    prize = award["prize"]
    comp = award["competition"]
    team = award.get("team")
    name, crest = _frozen_identity(award.get("team_name"), award.get("team_crest"), team)
    return {
        "prize_id": prize.id,
        "name": prize.name,
        "icon": prize.icon or "🏆",
        "condition_label": describe_condition(prize),
        "competition_id": comp.id,
        "competition_name": comp.name,
        "competition_format": comp.format,
        "league_id": comp.league_id,
        "league_name": comp.league.name,
        "team_id": team.id if team else None,
        "team_name": name,
        "crest": crest,
        "shared_with": award.get("shared_with", 0),
        "at": award["at"].isoformat() if award["at"] else None,
    }
