"""Le consultazioni passano dal digest: le colonne della coda.

Solo schema. Il travaso del pregresso sta nella 0049 e non qui, ed e' una
separazione obbligata, non stilistica: l'indice della chiave esterna nuova viene
creato da Django in fondo alla transazione della migrazione, quindi DOPO una
eventuale UPDATE fatta nella stessa. Su PostgreSQL quella UPDATE lascia in sospeso
i trigger del vincolo appena aggiunto e il CREATE INDEX muore con «pending trigger
events» — su SQLite no, il che e' esattamente il modo in cui una migrazione passa
in sviluppo e si ferma in produzione.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


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
    ]

