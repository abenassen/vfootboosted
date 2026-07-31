from django.db import migrations, models


def double_round_to_legs(apps, schema_editor):
    """andata/ritorno was a boolean; it is now a count of tornate."""
    CompetitionStage = apps.get_model("vfoot", "CompetitionStage")
    CompetitionStage.objects.filter(double_round=True).update(legs=2)


def legs_to_double_round(apps, schema_editor):
    CompetitionStage = apps.get_model("vfoot", "CompetitionStage")
    CompetitionStage.objects.filter(legs__gte=2).update(double_round=True)


def seed_format(apps, schema_editor):
    """Existing competitions predate the format field: infer it from the stages."""
    FantasyCompetition = apps.get_model("vfoot", "FantasyCompetition")
    for comp in FantasyCompetition.objects.all():
        types = set(comp.stages.values_list("stage_type", flat=True))
        if types == {"round_robin"}:
            fmt = "league"
        elif types == {"knockout"}:
            fmt = "cup"
        elif types:
            fmt = "groups_knockout"
        else:
            fmt = "league" if comp.competition_type == "round_robin" else "cup"
        FantasyCompetition.objects.filter(id=comp.id).update(format=fmt)


def backfill_round_layout(apps, schema_editor):
    """Give every existing stage the round bookkeeping the generators now keep.

    Read from the fixtures that are already there, so a league in flight keeps the
    exact rounds it has been playing.
    """
    CompetitionStage = apps.get_model("vfoot", "CompetitionStage")
    FantasyFixture = apps.get_model("vfoot", "FantasyFixture")
    for stage in CompetitionStage.objects.all():
        rounds = sorted(
            set(FantasyFixture.objects.filter(stage=stage).values_list("round_no", flat=True))
        )
        participants = stage.participants.count()
        if rounds:
            offset = rounds[0] - 1
            planned = rounds[-1] - offset
        else:
            offset = 0
            planned = 1
        CompetitionStage.objects.filter(id=stage.id).update(
            round_offset=offset,
            planned_rounds=max(1, planned),
            expected_participants=participants,
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [("vfoot", "0030_fantasyteam_crest")]

    operations = [
        migrations.AddField(
            model_name="fantasycompetition",
            name="format",
            field=models.CharField(
                choices=[
                    ("league", "Campionato"),
                    ("cup", "Coppa a eliminazione"),
                    ("groups_knockout", "Gironi + eliminazione"),
                    ("custom", "Personalizzata"),
                ],
                default="custom",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="fantasycompetition",
            name="round_calendar",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="competitionstage",
            name="legs",
            field=models.IntegerField(default=1),
        ),
        migrations.AddField(
            model_name="competitionstage",
            name="round_offset",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="competitionstage",
            name="planned_rounds",
            field=models.IntegerField(default=1),
        ),
        migrations.AddField(
            model_name="competitionstage",
            name="expected_participants",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="competitionstagerule",
            name="source_round",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="competitionprize",
            name="icon",
            field=models.CharField(blank=True, default="🏆", max_length=8),
        ),
        migrations.RunPython(double_round_to_legs, legs_to_double_round),
        migrations.RunPython(seed_format, noop),
        migrations.RunPython(backfill_round_layout, noop),
        migrations.RemoveField(model_name="competitionstage", name="double_round"),
    ]
