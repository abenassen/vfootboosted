from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("vfoot", "0055_leagues_default_to_own_deadline"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedlineupsnapshot",
            name="origin",
            field=models.CharField(default="manager", max_length=10),
        ),
    ]
