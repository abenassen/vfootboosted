from django.db import migrations
from django.db.models import F


def opened_when_planned(apps, schema_editor):
    """Le sessioni gia' esistenti sono nate aperte.

    Prima di questo campo ``opens_at`` era sempre l'istante della creazione: non
    si poteva programmare un'apertura, quindi ogni sessione si e' aperta quando
    e' stata creata. Senza il travaso, la prima richiesta che le tocca le
    prenderebbe per "appena aperte" e rifarebbe il giro del listone per niente.
    """
    MarketSession = apps.get_model("vfoot", "MarketSession")
    MarketSession.objects.filter(opened_at__isnull=True).update(opened_at=F("opens_at"))


def forget_opening(apps, schema_editor):
    MarketSession = apps.get_model("vfoot", "MarketSession")
    MarketSession.objects.update(opened_at=None)


class Migration(migrations.Migration):
    """Data only, separate from the schema change (see migrations-split rule)."""

    dependencies = [
        ("vfoot", "0058_marketsession_opened_at"),
    ]

    operations = [
        migrations.RunPython(opened_when_planned, forget_opening),
    ]
