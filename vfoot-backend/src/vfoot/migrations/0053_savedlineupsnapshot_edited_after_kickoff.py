from django.db import migrations, models


class Migration(migrations.Migration):
    """Solo schema. Il default False e' gia' la risposta giusta per le righe
    esistenti — nessuna formazione salvata prima d'ora e' stata giudicata sotto
    questa regola — quindi non c'e' nessun dato da riscrivere, e non ce n'e' da
    mettere qui dentro: una UPDATE nella stessa migrazione di una modifica di
    schema e' esattamente cio' che su Postgres fa fallire l'indice."""

    dependencies = [
        ("vfoot", "0052_auctionnomination_uniq_open_nomination_per_session"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedlineupsnapshot",
            name="edited_after_kickoff",
            field=models.BooleanField(default=False),
        ),
    ]
