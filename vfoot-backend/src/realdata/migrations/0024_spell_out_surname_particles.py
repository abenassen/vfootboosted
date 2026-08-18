"""Le particelle gia' abbreviate dal fornitore, riscritte per esteso.

La riparazione all'ingresso (v. ``sofascore_adapter._player``) vale solo per i
giocatori che devono ancora arrivare: il nome breve si scrive UNA volta, alla
creazione, e nessuna importazione successiva lo tocca. Senza questo travaso
"Giorgio De Marzi" resterebbe "G. D. Marzi" per sempre.

Si apre solo cio' che il nome completo conferma, quindi e' innocua da rieseguire
e non ha bisogno di un inverso: un nome gia' a posto non viene toccato.
"""

from django.db import migrations

from realdata.services.identity import spell_out_particles


def repair(apps, schema_editor):
    Player = apps.get_model("realdata", "Player")
    fixed = []
    for pid, full, short in Player.objects.values_list("id", "full_name", "short_name"):
        new = spell_out_particles(short, full)
        if new != (short or ""):
            fixed.append(Player(id=pid, short_name=new))
    if fixed:
        Player.objects.bulk_update(fixed, ["short_name"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("realdata", "0023_maintenancerun_maintenanceproposal"),
    ]

    operations = [
        migrations.RunPython(repair, migrations.RunPython.noop),
    ]
