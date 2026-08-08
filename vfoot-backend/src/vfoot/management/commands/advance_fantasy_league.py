"""Play a fantasy league forward over a season that already has results.

The companion to ``simulate_sofascore_season``: that one invents the championship,
this one makes a league LIVE through it — a lineup from every manager for every
matchday, and the matchdays behind the front concluded, so the app opens on a
league with a table, a history of results and a round in progress.

WHAT IT DOES NOT DO, AND WHY THAT MATTERS
-----------------------------------------
It does not compute a single score itself. The lineups are written where the app
writes them (``SavedLineupSnapshot``) and the conclusion goes through
``score_and_persist_matchday`` — the same function the admin's Concludi button
calls — followed by the same stage resolution and the same review of the honours. So
substitutions, the defence modifier, senza voto, the 66/+6 goal conversion, the cups
advancing and the trophies being handed out are all the product's own behaviour, not
a re-implementation that could flatter it. A cup won in March is dated March; a title
the last round has not decided yet stays undecided.

The one thing deliberately reproduced rather than reused is the CHOICE of the
eleven, because there is no manager to ask. Each squad is ranked by market value
and fields its best legal XI, with enough rotation that the season is not eleven
identical team sheets. No look-ahead: the pick cannot see who actually played, so
regulars turn up senza voto exactly as they do for a real manager, and the ordered
bench has to cover them — which is the point, since that is the machinery most
worth seeing work.

    python manage.py advance_fantasy_league --league 62 --through 22
"""
from __future__ import annotations

import random

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from realdata.models import PlayerMarketValue
from vfoot.models import (
    CompetitionStage,
    FantasyFixture,
    FantasyFixtureDetail,
    FantasyLeague,
    FantasyMatchday,
    FantasyRosterSlot,
    FantasyTeam,
    LeaguePlayerRole,
    SavedLineupSnapshot,
)
from vfoot.services import honours, matchday_state
from vfoot.services.classic_matchday_scoring import score_and_persist_matchday
from vfoot.services.classic_scoring import Ruleset
from vfoot.services.competition_stages import resolve_pending_stages, resolve_stage
from vfoot.services.formation_rules import is_legal_classic

ROLE_TO_LINEUP = {"POR": "GK", "DIF": "DEF", "CEN": "MID", "ATT": "ATT"}

# Legal classic shapes, as (DEF, MID, ATT). Every one satisfies the constraints in
# formation_rules — three at the back minimum, under six in any role, at most three
# forwards — and the XI is validated against them anyway before being saved.
MODULES = ((3, 4, 3), (4, 4, 2), (4, 3, 3), (3, 5, 2), (5, 3, 2), (4, 5, 1))

# Width of the rotation noise on the value ranking, in places. Small enough that a
# side is recognisable from week to week, large enough that the fourth-choice
# midfielder gets his afternoons.
CHURN = {"GK": 0.30, "DEF": 1.10, "MID": 1.20, "ATT": 0.90}


class Command(BaseCommand):
    help = "Field lineups and conclude matchdays for a classic league over a played season."

    def add_arguments(self, parser):
        parser.add_argument("--league", type=int, required=True)
        parser.add_argument("--through", type=int, required=True,
                            help="Last real matchday to field a lineup for.")
        parser.add_argument("--conclude-through", type=int, default=None,
                            help="Last matchday to CONCLUDE (default: --through minus "
                                 "one, i.e. the round in progress stays open).")
        parser.add_argument("--seed", type=int, default=6262)
        parser.add_argument("--admin", type=str, default=None,
                            help="Username recorded as having concluded the "
                                 "matchdays (default: the league owner).")
        parser.add_argument("--redo", action="store_true",
                            help="Re-field and re-conclude matchdays already done.")

    def handle(self, *args, **o):
        league = self._league(o["league"])
        if league.mode != FantasyLeague.MODE_CLASSIC:
            raise CommandError(
                f"League {league.id} is in '{league.mode}' mode; this command scores "
                f"the classic chain only.")
        through = int(o["through"])
        conclude_through = (int(o["conclude_through"])
                            if o["conclude_through"] is not None else through - 1)
        admin = (User.objects.filter(username=o["admin"]).first() if o["admin"]
                 else league.owner)
        rng = random.Random(int(o["seed"]))

        teams = list(FantasyTeam.objects.filter(league=league).order_by("id"))
        if not teams:
            raise CommandError(f"League {league.id} has no teams.")
        squads = self._squads(league, teams)
        self.stdout.write(self.style.NOTICE(
            f"{league.name} (id {league.id}): {len(teams)} teams, "
            f"lineups through matchday {through}, concluding through {conclude_through}"))

        ledger = matchday_state.league_matchdays(league)
        wanted = [md for md in ledger if md.real_matchday <= through]
        self._reopen(league, ledger, conclude_through)
        self._field(league, wanted, squads, rng, redo=bool(o["redo"]))
        self._conclude(league, wanted, conclude_through, admin, redo=bool(o["redo"]))
        self._report(league)

    # -- rewinding ---------------------------------------------------------
    @transaction.atomic
    def _reopen(self, league, ledger, conclude_through: int) -> None:
        """Un-conclude the matchdays that are no longer behind the front.

        Only does anything when the scenario is being wound BACK — asking for a
        state earlier than the one the database is in. Without it a rewind leaves
        matchdays concluded with results that the real matches have not produced
        yet, which is the one inconsistency the two-clock model cannot express: a
        round scored before it was played.
        """
        late = [md for md in ledger
                if md.real_matchday > conclude_through
                and md.status == FantasyMatchday.STATUS_CONCLUDED]
        if not late:
            # Non un'uscita: le competizioni si ricontrollano comunque, perche' un
            # secondo `build` trova le giornate gia' riaperte dal primo e uscire
            # qui lascerebbe in piedi proprio le bandiere che il primo aveva tolto.
            self._reopen_competitions(league)
            return
        fixtures = FantasyFixture.objects.filter(fantasy_matchday__in=late)
        FantasyFixtureDetail.objects.filter(fixture__in=fixtures).delete()
        # 0.0, not None: the column is NOT NULL with a 0.0 default, so nulling it
        # raised an IntegrityError — and only ever when the rewind had something to
        # rewind, which is why it survived. An unplayed fixture is identified by its
        # STATUS everywhere that matters (see _serialize_fixture_row, which only
        # exposes a score when it is finished), never by a null total.
        fixtures.update(status=FantasyFixture.STATUS_SCHEDULED,
                        home_total=0.0, away_total=0.0)
        for md in late:
            md.status = FantasyMatchday.STATUS_PLANNED
            md.concluded_at = None
            md.concluded_by = None
            md.save(update_fields=["status", "concluded_at", "concluded_by"])
        self.stdout.write(f"  rewound: {len(late)} matchdays reopened")
        self._reopen_competitions(league)

    def _reopen_competitions(self, league) -> None:
        """Riporta indietro anche CIO' CHE LE GIORNATE AVEVANO CHIUSO: le fasi, le
        competizioni, i premi. La regola sta in ``honours``, accanto a quella che
        assegna: sono la stessa decisione presa nei due versi."""
        for change in honours.reopen_incomplete(league):
            self.stdout.write(f"           reopened: {change['competition'].name}"
                              + (f" ({len(change['removed'])} prizes un-awarded)"
                                 if change["removed"] else ""))

    # -- squads ------------------------------------------------------------
    def _squads(self, league, teams) -> dict[int, dict[str, list[int]]]:
        """{team_id: {lineup_role: [player_id, best first]}}.

        Ordered by market value, which is what a manager has to go on before a ball
        is kicked. The league's FROZEN role is authoritative — that is the whole
        point of freezing it — so a player's slot here is the same one the save
        endpoint would validate him in.
        """
        roles = dict(LeaguePlayerRole.objects.filter(league=league)
                     .values_list("player_id", "role"))
        values = {}
        for pid, v in (PlayerMarketValue.objects.filter(provider="transfermarkt")
                       .order_by("player_id", "-as_of").values_list("player_id", "value_eur")):
            values.setdefault(pid, v or 0)

        out: dict[int, dict[str, list[int]]] = {}
        for team in teams:
            owned = list(FantasyRosterSlot.objects
                         .filter(team=team, released_at__isnull=True)
                         .values_list("player_id", flat=True))
            buckets: dict[str, list[int]] = {"GK": [], "DEF": [], "MID": [], "ATT": []}
            for pid in owned:
                slot = ROLE_TO_LINEUP.get(roles.get(pid, ""), "MID")
                buckets[slot].append(pid)
            for slot in buckets:
                buckets[slot].sort(key=lambda p: -values.get(p, 0))
            out[team.id] = buckets
        return out

    def _pick_xi(self, squad: dict[str, list[int]], rng: random.Random):
        """(gk, outfield, bench) — the best legal eleven, rotated.

        Falls back through the module list when a squad cannot fill a shape: a team
        that sold down to two forwards must still field a legal side, and refusing
        would leave the matchday unscoreable for everyone in its fixture.
        """
        def rotated(slot: str) -> list[int]:
            churn = CHURN[slot]
            return [p for _, p in sorted(
                ((i + rng.gauss(0.0, churn), p) for i, p in enumerate(squad[slot])),
                key=lambda t: t[0])]

        ranked = {slot: rotated(slot) for slot in ("GK", "DEF", "MID", "ATT")}
        for d, m, a in sorted(MODULES, key=lambda _: rng.random()):
            if (len(ranked["GK"]) < 1 or len(ranked["DEF"]) < d
                    or len(ranked["MID"]) < m or len(ranked["ATT"]) < a):
                continue
            gk = ranked["GK"][0]
            outfield = ranked["DEF"][:d] + ranked["MID"][:m] + ranked["ATT"][:a]
            starter_roles = ["GK"] + ["DEF"] * d + ["MID"] * m + ["ATT"] * a
            if not is_legal_classic(starter_roles):
                continue
            chosen = {gk, *outfield}
            # The bench keeps its priority order, and that order IS the
            # substitution order at conclusion: best available first, so a senza
            # voto is covered by the best man left rather than by whoever sorts
            # first by id.
            bench = [p for slot in ("GK", "DEF", "MID", "ATT")
                     for p in ranked[slot] if p not in chosen]
            return gk, outfield, bench
        return None, [], []

    # -- fielding ----------------------------------------------------------
    def _field(self, league, matchdays, squads, rng: random.Random, redo: bool) -> None:
        made = kept = skipped = 0
        for md in matchdays:
            for team_id, squad in squads.items():
                key = f"team{team_id}"
                existing = SavedLineupSnapshot.objects.filter(
                    league_id=str(league.id), matchday_id=str(md.real_matchday),
                    lineup_id=key).first()
                if existing is not None and not redo:
                    kept += 1
                    continue
                gk, outfield, bench = self._pick_xi(squad, rng)
                if gk is None or len(outfield) != 10:
                    skipped += 1
                    continue
                # Competition-AGNOSTIC on purpose: this league runs a championship
                # and two cups on the same real matchdays, and a manager who sets
                # one lineup expects it to be the side he plays in all of them.
                # ``read_saved_lineup`` falls back to exactly this key.
                SavedLineupSnapshot.objects.update_or_create(
                    league_id=str(league.id), matchday_id=str(md.real_matchday),
                    lineup_id=key,
                    defaults={"gk_player_id": str(gk),
                              "starter_player_ids": outfield,
                              "bench_player_ids": bench,
                              "starter_backups": {}},
                )
                made += 1
        self.stdout.write(f"  lineups: {made} written, {kept} already there"
                          + (f", {skipped} squads could not field a legal XI" if skipped else ""))

    # -- conclusion --------------------------------------------------------
    def _conclude(self, league, matchdays, conclude_through: int, admin, redo: bool) -> None:
        ruleset = Ruleset.from_league(league)
        done = 0
        trophies: list[str] = []
        for md in matchdays:
            if md.real_matchday > conclude_through:
                continue
            if md.status == FantasyMatchday.STATUS_CONCLUDED and not redo:
                continue
            # A matchday with no fixtures is still concluded, not skipped. This
            # league's championship has no round on real matchday 7, and leaving that
            # row PLANNED parks the ledger pointer on it for good: the league would
            # report "next to score: 7" with twenty rounds played behind it, and every
            # later conclusion would be refused for being out of order. Concluding it
            # scores nothing, which is the right amount.
            fixtures = list(FantasyFixture.objects.filter(fantasy_matchday=md)
                            .select_related("source_real_match", "stage", "competition")
                            .order_by("id"))
            with transaction.atomic():
                result = score_and_persist_matchday(
                    md, league, ruleset, fixtures, {}, force=False, update_snapshot=True)
                if result["missing_teams"]:
                    # A LIST of dicts, not a dict: score_and_persist_matchday returns
                    # it that way so the API can serialise it, and reading it as a
                    # mapping turned "you have teams without a lineup" — the message
                    # that says what to do — into an AttributeError.
                    names = ", ".join(t["name"] for t in result["missing_teams"])
                    raise CommandError(
                        f"Matchday {md.real_matchday}: no lineup for {names}. "
                        f"Field them first (this command does, unless --through cut "
                        f"them off).")
                if result["pending_matches"]:
                    raise CommandError(
                        f"Matchday {md.real_matchday} has {len(result['pending_matches'])} "
                        f"real matches not played yet — concluding it would score a "
                        f"postponement as a senza voto. Lower --conclude-through.")
                self._advance_stages(league, result["stage_ids"])
                md.status = FantasyMatchday.STATUS_CONCLUDED
                md.concluded_at = timezone.now()
                md.concluded_by = admin
                md.awaiting_since = None
                md.awaiting_reason = ""
                md.nudged_at = None
                md.save(update_fields=["status", "concluded_at", "concluded_by",
                                       "awaiting_since", "awaiting_reason", "nudged_at"])
                # DOPO il salvataggio, come nell'endpoint: un premio e' datato dal
                # registro, e chiedendo prima si troverebbe la competizione finita
                # e la sua data mancante. E' l'ultimo pezzo del "questo comando non
                # calcola niente per conto suo": senza, una lega ricostruita
                # arrivava in fondo alla stagione con l'albo d'oro vuoto, e la
                # coppa vinta a marzo non risultava vinta da nessuno.
                for change in honours.review_league(league):
                    won = ", ".join(t.name for t in FantasyTeam.objects.filter(
                        id__in=change["added"]))
                    trophies.append(f"{change['prize'].icon or '🏆'} "
                                    f"{change['prize'].name}: {won}")
            done += 1
            self.stdout.write(f"  matchday {md.real_matchday:2d}: "
                              f"{result['updated']} fixtures scored")
        self.stdout.write(f"  concluded: {done} matchdays")
        for line in trophies:
            self.stdout.write(f"    assegnato  {line}")

    def _advance_stages(self, league, stage_ids) -> None:
        """Close finished stages and fill whatever they unlock — the same two steps
        the conclusion endpoint runs, so a cup's semi-final appears when its group
        ends instead of at the next manual poke."""
        targets: set[int] = set()
        for sid in stage_ids:
            stage = CompetitionStage.objects.filter(id=sid).first()
            if stage is None or not self._stage_done(stage):
                continue
            if stage.status != CompetitionStage.STATUS_DONE:
                stage.status = CompetitionStage.STATUS_DONE
                stage.save(update_fields=["status"])
            targets.update(int(t) for t in stage.rules_out.values_list("target_stage_id", flat=True))
        for tid in sorted(targets):
            target = CompetitionStage.objects.filter(id=tid).first()
            if target is not None:
                resolve_stage(target, seed=42)
        # A cup fed by "the table after round 7" hangs off a stage that is NOT done,
        # so asking every competition what it was waiting for is not redundant.
        for competition in league.competitions.all():
            resolve_pending_stages(competition, seed=42)

    @staticmethod
    def _stage_done(stage: CompetitionStage) -> bool:
        total = stage.fixtures.count()
        return bool(total) and stage.fixtures.filter(
            status=FantasyFixture.STATUS_FINISHED).count() == total

    # -- report ------------------------------------------------------------
    def _report(self, league) -> None:
        ledger = matchday_state.league_matchdays(league)
        concluded = [md for md in ledger if md.status == FantasyMatchday.STATUS_CONCLUDED]
        pointer = matchday_state.ledger_matchday(league)
        self.stdout.write(self.style.SUCCESS(
            f"ledger: {len(concluded)}/{len(ledger)} matchdays concluded; "
            f"next to score: "
            f"{pointer.real_matchday if pointer else 'none, up to date'}; "
            f"next fieldable: {matchday_state.next_fieldable_matchday(league)}; "
            f"being played: {matchday_state.playing_matchday(league)}"))

    def _league(self, league_id: int) -> FantasyLeague:
        try:
            return FantasyLeague.objects.get(id=league_id)
        except FantasyLeague.DoesNotExist as exc:
            raise CommandError(f"No league with id {league_id}.") from exc
