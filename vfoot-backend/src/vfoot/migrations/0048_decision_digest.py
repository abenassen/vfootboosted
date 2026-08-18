"""Le consultazioni passano dal digest: le colonne della coda, e il travaso.

Il travaso NON e' un dettaglio. Senza, il primo giro del digest trova ogni
consultazione gia' aperta con `consult_notified_at` nullo, la considera mai
spedita e la rispedisce a tutti: il rilascio che serve a togliere la valanga di
mail comincerebbe con una valanga di mail. Quindi tutto cio' che esiste ora e'
gia' notificato per definizione, e la coda parte vuota.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models.functions import Coalesce


def already_told(apps, schema_editor):
    """Tutto il pregresso e' gia' stato annunciato all'epoca, un messaggio per
    decisione. Non si sa QUANDO (non c'era la colonna): `created_at` e
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
        ('vfoot', '0047_crestimage_crestreport_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='leaguedecision',
            name='consult_notified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='leaguedecision',
            name='consult_opened_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='leaguedecision',
            name='consult_opened_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='leaguedecision',
            name='outcome_notified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(already_told, migrations.RunPython.noop),
    ]

