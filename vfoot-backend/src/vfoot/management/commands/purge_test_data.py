"""Cancella utenti e leghe di prova, e nient'altro.

Un collaudo end-to-end in PRODUZIONE lascia in giro account, leghe, aste,
formazioni e decisioni. Doverli togliere a mano dall'admin, una tabella alla
volta, e' esattamente il modo in cui si cancella per sbaglio qualcosa di vero.

Cosa considera "di prova": il PREFISSO. Utenti il cui `username` inizia col
prefisso, e leghe il cui `name` inizia col prefisso. Niente euristiche piu'
furbe (data di creazione, email finta): un criterio che si legge a occhio e'
l'unico che permette di fidarsi del `--yes`.

    manage.py purge_test_data                 # elenca e basta (dry-run implicito)
    manage.py purge_test_data --yes           # cancella davvero
    manage.py purge_test_data --prefix qa_ --yes

L'ordine delle cancellazioni non e' decorativo: `AuctionNomination.nominator` e
`AuctionBid.bidder` puntano a `LeagueMembership` con PROTECT, quindi la
cancellazione a cascata della lega si blocca se prima non si e' svuotata l'asta.
Stessa storia per `FantasyFixture` verso `FantasyTeam`. Qui l'ordine e' scritto
una volta, dal basso verso l'alto.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from vfoot.models import (
    AuctionBid,
    AuctionEvent,
    AuctionNomination,
    AuctionSession,
    AwardedPrize,
    CompetitionQualificationRule,
    CompetitionStageParticipant,
    CompetitionTeam,
    FantasyCompetition,
    FantasyFixture,
    FantasyFixtureDetail,
    FantasyLeague,
    FantasyLineupSubmission,
    FantasyMatchday,
    FantasyRosterSlot,
    FantasyTeam,
    LeagueDecision,
    LeagueDecisionVote,
    LeagueMembership,
    LeaguePlayerRole,
    MarketEvent,
    MarketOffer,
    MarketSession,
    OfficeOverride,
    SavedLineupSnapshot,
)

DEFAULT_PREFIX = "test_"


class Command(BaseCommand):
    help = "Cancella utenti e leghe di prova identificati da un prefisso nel nome."

    def add_arguments(self, parser):
        parser.add_argument("--prefix", default=DEFAULT_PREFIX,
                            help=f"prefisso di username e nome lega (default: {DEFAULT_PREFIX!r})")
        parser.add_argument("--yes", action="store_true",
                            help="cancella davvero; senza questo elenca soltanto")

    def handle(self, *args, **opts):
        prefix = opts["prefix"]
        if not prefix or len(prefix) < 3:
            raise CommandError("Prefisso troppo corto: cancellerebbe piu' del previsto.")

        leagues = list(FantasyLeague.objects.filter(name__startswith=prefix))
        users = list(User.objects.filter(username__startswith=prefix))

        # Anche le leghe possedute o abitate da un utente di prova, altrimenti la
        # cancellazione dell'utente si scontra col PROTECT su FantasyLeague.owner.
        extra = FantasyLeague.objects.filter(
            owner__in=users,
        ).exclude(pk__in=[lg.pk for lg in leagues])
        leagues += list(extra)

        if not leagues and not users:
            self.stdout.write(f"Niente da cancellare col prefisso {prefix!r}.")
            return

        self.stdout.write(self.style.WARNING(f"Prefisso {prefix!r}"))
        for lg in leagues:
            members = LeagueMembership.objects.filter(league=lg).count()
            self.stdout.write(f"  lega  #{lg.id} {lg.name} ({lg.mode}, {members} membri)")
        for u in users:
            self.stdout.write(f"  utente #{u.id} {u.username} <{u.email}>")

        if not opts["yes"]:
            self.stdout.write(self.style.NOTICE("\nProva a vuoto: rilancia con --yes per cancellare."))
            return

        league_ids = [lg.pk for lg in leagues]
        with transaction.atomic():
            counts = {}

            def wipe(label, queryset):
                n = queryset.delete()[0]
                if n:
                    counts[label] = counts.get(label, 0) + n

            # --- asta -------------------------------------------------------
            wipe("bid", AuctionBid.objects.filter(nomination__session__league_id__in=league_ids))
            wipe("nomination", AuctionNomination.objects.filter(session__league_id__in=league_ids))
            wipe("auction event", AuctionEvent.objects.filter(session__league_id__in=league_ids))
            wipe("auction", AuctionSession.objects.filter(league_id__in=league_ids))

            # --- mercato ----------------------------------------------------
            wipe("market event", MarketEvent.objects.filter(session__league_id__in=league_ids))
            wipe("market offer", MarketOffer.objects.filter(session__league_id__in=league_ids))
            wipe("market session", MarketSession.objects.filter(league_id__in=league_ids))

            # --- partite fantacalcio ---------------------------------------
            fixtures = FantasyFixture.objects.filter(competition__league_id__in=league_ids)
            wipe("lineup", FantasyLineupSubmission.objects.filter(fixture__in=fixtures))
            wipe("fixture detail", FantasyFixtureDetail.objects.filter(fixture__in=fixtures))
            wipe("awarded prize", AwardedPrize.objects.filter(prize__competition__league_id__in=league_ids))
            wipe("fixture", fixtures)

            # --- competizioni ----------------------------------------------
            wipe("stage participant",
                 CompetitionStageParticipant.objects.filter(stage__competition__league_id__in=league_ids))
            wipe("competition team", CompetitionTeam.objects.filter(competition__league_id__in=league_ids))
            wipe("qualification rule",
                 CompetitionQualificationRule.objects.filter(competition__league_id__in=league_ids))
            wipe("competition", FantasyCompetition.objects.filter(league_id__in=league_ids))
            wipe("matchday", FantasyMatchday.objects.filter(league_id__in=league_ids))

            # --- decisioni sui ruoli ---------------------------------------
            wipe("vote", LeagueDecisionVote.objects.filter(decision__league_id__in=league_ids))
            wipe("decision", LeagueDecision.objects.filter(league_id__in=league_ids))

            # --- rose, squadre, iscrizioni ---------------------------------
            wipe("roster slot", FantasyRosterSlot.objects.filter(team__league_id__in=league_ids))
            wipe("team", FantasyTeam.objects.filter(league_id__in=league_ids))
            wipe("membership", LeagueMembership.objects.filter(league_id__in=league_ids))
            wipe("listone", LeaguePlayerRole.objects.filter(league_id__in=league_ids))
            wipe("office override", OfficeOverride.objects.filter(league_id__in=league_ids))

            # Le formazioni salvate non hanno una chiave esterna: tengono l'id
            # della lega come stringa, quindi nessuna cascata le porterebbe via.
            wipe("saved lineup",
                 SavedLineupSnapshot.objects.filter(league_id__in=[str(i) for i in league_ids]))

            wipe("lega", FantasyLeague.objects.filter(pk__in=league_ids))

            # Un utente di prova che gioca ancora in una lega VERA non si tocca:
            # cancellarlo porterebbe via la sua squadra, e con essa le partite
            # gia' giocate da quella lega. Meglio dirlo e lasciarlo li'.
            keep = {
                m.user_id: m.league.name
                for m in LeagueMembership.objects.select_related("league").filter(
                    user__in=users,
                )
            }
            for uid, league_name in keep.items():
                self.stdout.write(self.style.WARNING(
                    f"  utente #{uid} NON cancellato: e' ancora nella lega «{league_name}»"
                ))
            wipe("utente", User.objects.filter(
                pk__in=[u.pk for u in users if u.pk not in keep],
            ))

        for label, n in counts.items():
            self.stdout.write(f"  {n:>5}  {label}")
        self.stdout.write(self.style.SUCCESS("Fatto."))
