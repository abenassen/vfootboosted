from django.db import migrations


def matchday_to_own(apps, schema_editor):
    """Leagues on the old default move to the new one.

    Only ``matchday``: it was the default, so nobody chose it. ``player`` was a
    choice and stays — it is also the only mode the extra rules are written for,
    and silently turning it off under a league would change its game.
    """
    FantasyLeague = apps.get_model("vfoot", "FantasyLeague")
    FantasyLeague.objects.filter(lineup_lock_mode="matchday").update(lineup_lock_mode="own")


def own_to_matchday(apps, schema_editor):
    FantasyLeague = apps.get_model("vfoot", "FantasyLeague")
    FantasyLeague.objects.filter(lineup_lock_mode="own").update(lineup_lock_mode="matchday")


class Migration(migrations.Migration):
    """Data only, separate from the schema change (see migrations-split rule)."""

    dependencies = [
        ("vfoot", "0054_fantasyleague_lineup_lock_own"),
    ]

    operations = [
        migrations.RunPython(matchday_to_own, own_to_matchday),
    ]
