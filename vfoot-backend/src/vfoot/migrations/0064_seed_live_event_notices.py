"""Sigilla come «gia' detto» tutto cio' che e' accaduto prima di questa riga.

Separata dalla 0063 di proposito (v. la regola: schema e dati in migrazioni
diverse — una UPDATE nella stessa migrazione della chiave esterna fa fallire la
creazione dell'indice su Postgres, e SQLite non lo vede).

Senza questo passaggio l'annuncio, che da oggi confronta la partita col registro
invece che con un'istantanea, troverebbe il registro vuoto e riterrebbe NUOVO ogni
gol di ogni partita ancora aperta: un deploy fatto mentre si gioca sparerebbe in
tendina l'intera prima mezz'ora tutta insieme.

Solo le partite non ancora finalizzate (``data_ready=False``), che sono esattamente
quelle su cui l'annuncio puo' ancora girare. Le altre non le guarda nessuno.

``recipients`` resta vuoto e NON significa che non fu mandata a nessuno: significa
che di quelle consegne non abbiamo il registro, perche' prima non lo tenevamo. E'
il confine fra il prima e il dopo, ed e' bene che si veda.
"""
from django.db import migrations


def seal_the_past(apps, schema_editor):
    Match = apps.get_model("realdata", "Match")
    MatchAppearance = apps.get_model("realdata", "MatchAppearance")
    MatchDisciplinaryEvent = apps.get_model("realdata", "MatchDisciplinaryEvent")
    LiveEventNotice = apps.get_model("vfoot", "LiveEventNotice")
    CARD_RED, CARD_SECOND_YELLOW = "red", "second_yellow"

    open_matches = list(Match.objects.filter(data_ready=False)
                        .values_list("id", flat=True))
    if not open_matches:
        return
    rows = []
    for match_id, player_id, goals in MatchAppearance.objects.filter(
            match_id__in=open_matches, goals__gt=0).values_list(
            "match_id", "player_id", "goals"):
        rows += [LiveEventNotice(match_id=match_id, player_id=player_id,
                                 kind="goal", occurrence=occ, recipients=[])
                 for occ in range(1, int(goals) + 1)]
    for match_id, player_id in MatchDisciplinaryEvent.objects.filter(
            match_id__in=open_matches,
            card_type__in=(CARD_RED, CARD_SECOND_YELLOW)).values_list(
            "match_id", "player_id"):
        rows.append(LiveEventNotice(match_id=match_id, player_id=player_id,
                                    kind="red", occurrence=1, recipients=[]))
    LiveEventNotice.objects.bulk_create(rows, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("vfoot", "0063_live_event_notice")]
    operations = [migrations.RunPython(seal_the_past, migrations.RunPython.noop)]
