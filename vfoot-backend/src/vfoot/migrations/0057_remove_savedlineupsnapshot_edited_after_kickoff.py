from django.db import migrations


class Migration(migrations.Migration):
    """The flag that switched the defender rule on when the manager edited after
    kickoff. The rule is the league's now (Ruleset.defence_first) and nothing reads
    or writes this column: a field nobody reads is a lie in the model."""

    dependencies = [
        ("vfoot", "0056_savedlineupsnapshot_origin"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="savedlineupsnapshot",
            name="edited_after_kickoff",
        ),
    ]
