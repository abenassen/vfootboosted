from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema only: the new choice and the new default. The data move is 0055."""

    dependencies = [
        ("vfoot", "0053_savedlineupsnapshot_edited_after_kickoff"),
    ]

    operations = [
        migrations.AlterField(
            model_name="fantasyleague",
            name="lineup_lock_mode",
            field=models.CharField(
                choices=[
                    ("matchday", "Al primo calcio d'inizio della giornata"),
                    ("own", "Alla prima partita di un tuo giocatore"),
                    ("player", "Ogni giocatore all'inizio della sua partita"),
                ],
                default="own",
                max_length=10,
            ),
        ),
    ]
