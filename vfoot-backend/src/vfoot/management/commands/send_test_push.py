"""Send one push to a user's registered installations, to prove the server can.

    python manage.py send_test_push --user andrea

This is the one check the automated suite cannot do for you: it uses THIS
deployment's VAPID keys and the subscriptions actually stored in the database, so
it answers "can my server reach my phone", not "is my code correct". Run it after
setting the keys, and again from the Linode after a deploy.

Reports per installation, because that is where the answer lives: a user with the
app on the phone and the site on a laptop has two, and one failing while the
other works is the normal shape of a problem here.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from vfoot.models import PushSubscription
from vfoot.services import push_channel


class Command(BaseCommand):
    help = "Invia una notifica push di prova alle installazioni di un utente."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="username destinatario")
        parser.add_argument("--title", default="Prova da Vfoot Boosted")
        parser.add_argument("--body", default="Se la vedi, le notifiche funzionano.")
        parser.add_argument("--url", default="/home",
                            help="dove porta il click sulla notifica")

    def handle(self, *args, **o):
        if not push_channel.configured():
            raise CommandError(
                "VAPID non configurato: genera le chiavi con `manage.py vapid_keys` "
                "e mettile in VFOOT_VAPID_PUBLIC_KEY / VFOOT_VAPID_PRIVATE_KEY.")
        try:
            user = User.objects.get(username=o["user"])
        except User.DoesNotExist:
            raise CommandError(f"Nessun utente '{o['user']}'.")

        subs = list(PushSubscription.objects.filter(user=user))
        if not subs:
            raise CommandError(
                f"'{user.username}' non ha installazioni iscritte. Deve aprire "
                "Profilo -> Notifiche e installazione e attivarle (su iPhone, "
                "prima aggiungere l'app alla schermata Home).")

        self.stdout.write(f"{len(subs)} installazioni per {user.username}:")
        for s in subs:
            label = s.user_agent[:60] or s.endpoint[:60]
            self.stdout.write(f"  - {label}")

        sent = push_channel.send_to_user(user, title=o["title"], body=o["body"],
                                        url=o["url"], tag="test")
        # send_to_user deletes whatever the push service reported as gone, so the
        # difference between the two counts is the useful part of the output.
        left = PushSubscription.objects.filter(user=user).count()
        if sent:
            self.stdout.write(self.style.SUCCESS(
                f"\nConsegnate al servizio push: {sent}/{len(subs)}."))
        else:
            self.stdout.write(self.style.ERROR(
                "\nNessuna consegna riuscita. Guarda i log per lo stato HTTP: "
                "404/410 = subscription morta (rimossa ora), 401/403 = chiavi "
                "VAPID sbagliate o cambiate dopo l'iscrizione."))
        if left != len(subs):
            self.stdout.write(self.style.WARNING(
                f"Rimosse {len(subs) - left} subscription non più valide."))
        self.stdout.write(
            "\nNota: la consegna al servizio push non garantisce la comparsa a "
            "schermo — il dispositivo puo' essere offline (il messaggio resta in "
            "coda) o l'utente aver revocato il permesso nel sistema.")
