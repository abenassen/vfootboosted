"""Il travaso: tutto il pregresso e' gia' stato annunciato.

NON e' un dettaglio, ed e' il motivo per cui questa migrazione esiste separata
(v. 0048 per il vincolo tecnico che impone la separazione). Senza, il primo giro
del digest trova ogni consultazione gia' aperta con `consult_notified_at` nullo,
la considera mai spedita e la rispedisce a tutti: il rilascio che serve a togliere
la valanga di mail comincerebbe con una valanga di mail.
"""

from django.db import migrations, models
from django.db.models.functions import Coalesce


def already_told(apps, schema_editor):
    """Non si sa QUANDO fu annunciato (non c'era la colonna): `created_at` e
    `resolved_at` sono l'approssimazione onesta, e comunque da qui in poi conta
    solo che non siano nulli."""
    LeagueDecision = apps.get_model("vfoot", "LeagueDecision")
    LeagueDecision.objects.filter(consultation_open=True).update(
        consult_opened_at=models.F("created_at"),
        consult_notified_at=models.F("created_at"))
    LeagueDecision.objects.filter(status="resolved").update(
        outcome_notified_at=Coalesce("resolved_at", "created_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("vfoot", "0048_decision_digest"),
    ]

    operations = [
        migrations.RunPython(already_told, migrations.RunPython.noop),
    ]
