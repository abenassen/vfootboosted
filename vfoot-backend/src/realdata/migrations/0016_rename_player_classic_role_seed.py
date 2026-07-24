from django.db import migrations


class Migration(migrations.Migration):
    """Rename Player.classic_role -> classic_role_seed.

    The field is only the raw Transfermarkt provider seed (winger -> CEN by
    convention), never the resolved scoring role — the name now says so. Data is
    preserved (a pure column rename).
    """

    dependencies = [
        ("realdata", "0015_alter_player_classic_role"),
    ]

    operations = [
        migrations.RenameField(
            model_name="player",
            old_name="classic_role",
            new_name="classic_role_seed",
        ),
    ]
