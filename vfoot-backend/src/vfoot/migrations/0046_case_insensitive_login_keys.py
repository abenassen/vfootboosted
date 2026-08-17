"""Rende univoci username ed email a meno del maiuscolo, nel database.

Il login cerca l'account con ``iexact`` e accetta indifferentemente l'username o
l'indirizzo: perche' quella ricerca sia sicura, deve poter restituire **una sola**
riga. L'unicita' non puo' stare solo nei serializer, perche' `createsuperuser` e i
comandi di gestione non ci passano; qui e' un vincolo del database, e vale per
ogni strada che crei un utente.

L'indice sull'email e' **parziale**: Django ammette l'email vuota (un superutente
creato da riga di comando senza indirizzo), e senza il ``WHERE`` due account senza
email collidono fra loro sulla stringa vuota. Chi non ha indirizzo semplicemente
non potra' entrare per email — non e' un identificativo.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('vfoot', '0045_feedback'),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX auth_user_username_ci_key "
                "ON auth_user (LOWER(username));"
            ),
            reverse_sql="DROP INDEX IF EXISTS auth_user_username_ci_key;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX auth_user_email_ci_key "
                "ON auth_user (LOWER(email)) WHERE email <> '';"
            ),
            reverse_sql="DROP INDEX IF EXISTS auth_user_email_ci_key;",
        ),
    ]
