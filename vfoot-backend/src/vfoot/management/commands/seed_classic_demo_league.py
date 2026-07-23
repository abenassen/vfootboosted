"""Seed a fully-browsable CLASSIC-mode demo league from real 2025-26 Serie A data,
so the frontend can be tested end-to-end (fixtures list, standings, formation page,
classic match detail).

What it builds (all persisted, idempotent by league name+owner):
  * a classic FantasyLeague (owner manages team #1), 10 teams with REALISTIC rosters
    snake-drafted from the real pool (3 POR / 8 DIF / 8 CEN / 6 ATT = 25), listone
    FROZEN (LeaguePlayerRole);
  * a round-robin Campionato: 10 teams -> 9-round cycle, repeated --cycles (default 4)
    -> 36 fantasy rounds on real matchdays 1..36 (last two of 38 skipped), 5 fixtures/rd;
  * each team fields a FIXED depth-chart XI (1 POR, 3-4-3) chosen by season regularity,
    so on some matchdays a regular is s.v. and the ORDERED bench substitution kicks in
    (visible substitutions). Lineups stored as FantasyLineupSubmission + SavedLineupSnapshot;
  * each fixture SCORED with the real classic fantavoto = voto puro (our heuristic) +
    bonus/malus (goal +3, assist +1, own goal -2, pen miss -3, pen save +3, GK -1/goal
    conceded), the ordered bench resolving s.v. starters; total -> classic goals via the
    66/72/78 thresholds; a CLASSIC FantasyFixtureDetail payload (per-player voto puro,
    bonus, malus, fantavoto + bench + substitutions) for the classic match-detail view.

    python manage.py seed_classic_demo_league --owner andrea
"""

from __future__ import annotations

import json
from collections import defaultdict
import random

from django.contrib.auth.models import User
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from realdata.models import (
    CompetitionSeason, Match, MatchAppearance, MatchDisciplinaryEvent, Player,
)
from vfoot.models import (
    CompetitionStage,
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
    LeagueMembership,
    LeaguePlayerRole,
    SavedLineupSnapshot,
)
from vfoot.services.classic_rating import build_reference
from vfoot.services.classic_pagella import get_role_averages, pagella_for_match
from vfoot.services.defense_bonus import compute_defense_bonus
from vfoot.services.formation_rules import is_legal_classic
from vfoot.services.lineup_substitution import apply_classic_substitutions

CACHE = str(Path(settings.VFOOT_DATA_DIR) / "historical-data" / "serie-a" / "sofascore" / "cache")
ROLE_TO_LINEUP = {"POR": "GK", "DIF": "DEF", "CEN": "MID", "ATT": "ATT"}
SQUAD = {"POR": 3, "DIF": 8, "CEN": 8, "ATT": 6}          # 25 per team
# One module per team (DEF, MID, ATT) — a mix so several teams field >=4 defenders
# and thus qualify for the defence modifier; all are legal classic shapes.
MODULES = [(4, 3, 3), (3, 4, 3), (4, 4, 2), (5, 3, 2), (3, 5, 2),
           (4, 5, 1), (4, 3, 3), (5, 4, 1), (3, 4, 3), (4, 4, 2)]
GOAL_THRESHOLDS = (66.0, 72.0, 78.0, 84.0, 90.0, 96.0)
# Knockout cup over the SECOND HALF of the season: 8 teams, (stage, real matchday).
CUP_TEAMS = 8
CUP_ROUNDS = [("Quarti di finale", 24), ("Semifinali", 30), ("Finale", 36)]
SV_BASELINE = 6.0

SIDE_HOME, SIDE_AWAY = "home", "away"
CARD_MALUS = {"yellow": 0.5, "second_yellow": 1.0, "red": 1.0}  # ammonizione/espulsione


def classic_goals(total: float) -> int:
    return sum(1 for t in GOAL_THRESHOLDS if total >= t)


class Command(BaseCommand):
    help = "Seed a browsable classic-mode demo league from real 2025-26 data."

    def add_arguments(self, parser):
        parser.add_argument("--owner", default="andrea")
        parser.add_argument("--league-name", default="Lega Classic Demo · Serie A 2025/26")
        parser.add_argument("--competition-name", default="Campionato Classic")
        parser.add_argument("--competition-season", type=int, default=2)
        parser.add_argument("--teams", type=int, default=10)
        parser.add_argument("--cycles", type=int, default=4)
        parser.add_argument("--min-appearances", type=int, default=8)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--no-cup", action="store_true",
                            help="skip the knockout cup (championship only)")

    # -- real-data precompute --------------------------------------------

    def _event_map(self, cs_id):
        """(matchday, our_player_id) -> bonus/malus events + minutes, from cache."""
        ext_to_pid = {v: k for k, v in Player.objects.filter(external_source="sofascore")
                      .values_list("id", "external_id")}
        out: dict[tuple[int, int], dict] = {}
        for m in Match.objects.filter(competition_season_id=cs_id):
            if not m.external_id or m.matchday is None:
                continue
            try:
                d = json.load(open(f"{CACHE}/api_v1_event_{m.external_id}_lineups.json"))
            except (FileNotFoundError, ValueError):
                continue
            for side in (SIDE_HOME, SIDE_AWAY):
                for pl in d.get(side, {}).get("players", []):
                    pid = ext_to_pid.get(str((pl.get("player") or {}).get("id")))
                    if pid is None:
                        continue
                    st = pl.get("statistics") or {}
                    out[(m.matchday, pid)] = {
                        "goals": int(st.get("goals", 0) or 0),
                        "assists": int(st.get("goalAssist", 0) or 0),
                        "own_goals": int(st.get("ownGoals", 0) or 0),
                        "pen_miss": int(st.get("penaltyMiss", 0) or 0),
                        "pen_save": int(st.get("penaltySave", 0) or 0),
                        "minutes": int(st.get("minutesPlayed", 0) or 0),
                    }
        return out

    def _gk_conceded(self, cs_id):
        """(matchday, gk_player_id) -> goals conceded that match (for the GK -1/goal)."""
        goals = {m.id: (int(m.home_goals or 0), int(m.away_goals or 0))
                 for m in Match.objects.filter(competition_season_id=cs_id,
                                               home_goals__isnull=False, away_goals__isnull=False)}
        md_by_match = dict(Match.objects.filter(competition_season_id=cs_id)
                           .values_list("id", "matchday"))
        gk_ids = set(Player.objects.filter(classic_role="POR").values_list("id", flat=True))
        out, played = {}, set()
        for mid, pid, side, mins in MatchAppearance.objects.filter(
            player_id__in=gk_ids, match__competition_season_id=cs_id
        ).values_list("match_id", "player_id", "side", "minutes_played"):
            md = md_by_match.get(mid)
            if md is None or mid not in goals or (mins or 0) <= 0:
                continue
            hg, ag = goals[mid]
            out[(md, pid)] = ag if str(side) == SIDE_HOME else hg
            played.add((md, pid))
        return out, played

    def _maps(self, cs_id):
        # Voto puro AND its explanation come from the shared pagella_for_match, the
        # same code the real-championship view uses — so a league fixture and the
        # Serie A match behind it agree, the keeper is scored on his own channel
        # (not a flat baseline), and every player carries the "why this vote"
        # breakdown. The seed keeps only its own bonus/malus that the DB-only
        # pagella cannot see: own goals, penalty misses and saves, read from cache.
        ref = build_reference(cs_id)
        averages = get_role_averages(cs_id)
        vp, rated, expl = {}, set(), {}
        for m in Match.objects.filter(competition_season_id=cs_id):
            if m.matchday is None:
                continue
            pag = pagella_for_match(m, ref, averages=averages)
            for side in ("home", "away"):
                for group in ("starters", "bench"):
                    for line in pag[side][group]:
                        key = (m.matchday, line["player_id"])
                        if line["sv"] or line["voto_puro"] is None:
                            continue
                        vp[key] = float(line["voto_puro"])
                        rated.add(key)
                        if line.get("explanation"):
                            expl[key] = {"explanation": line["explanation"],
                                         "explanation_text": line.get("explanation_text")}
        evt = self._event_map(cs_id)
        gk_conceded, gk_played = self._gk_conceded(cs_id)
        cards = self._cards_map(cs_id)
        ga = self._goals_assists_map(cs_id)
        return {"vp": vp, "rated": rated, "expl": expl, "evt": evt, "cards": cards,
                "ga": ga, "gk_conceded": gk_conceded, "gk_played": gk_played}

    def _goals_assists_map(self, cs_id):
        """(matchday, player_id) -> (goals, assists), from the DB (MatchAppearance)."""
        md_by_match = dict(Match.objects.filter(competition_season_id=cs_id)
                           .values_list("id", "matchday"))
        out = {}
        for mid, pid, g, a in MatchAppearance.objects.filter(
            match__competition_season_id=cs_id
        ).values_list("match_id", "player_id", "goals", "assists"):
            md = md_by_match.get(mid)
            if md is not None:
                out[(md, pid)] = (int(g or 0), int(a or 0))
        return out

    def _cards_map(self, cs_id):
        """(matchday, player_id) -> {yellow, red, second_yellow counts, malus}."""
        md_by_match = dict(Match.objects.filter(competition_season_id=cs_id)
                           .values_list("id", "matchday"))
        cards: dict[tuple[int, int], dict] = defaultdict(
            lambda: {"yellow": 0, "red": 0, "second_yellow": 0, "malus": 0.0})
        for mid, pid, ct in MatchDisciplinaryEvent.objects.filter(
            match__competition_season_id=cs_id, provider="sofascore"
        ).values_list("match_id", "player_id", "card_type"):
            md = md_by_match.get(mid)
            if md is not None and pid is not None:
                rec = cards[(md, pid)]
                if ct in rec:
                    rec[ct] += 1
                rec["malus"] += CARD_MALUS.get(ct, 0.0)
        return cards

    # -- per-player fantavoto breakdown ----------------------------------

    def _line(self, p, md, maps):
        """Per-player breakdown line. sv=True means 'senza voto' (no contribution)."""
        pid, role = p["player_id"], p["role"]
        lrole = ROLE_TO_LINEUP[role]
        e = maps["evt"].get((md, pid), {})
        cards = maps["cards"].get((md, pid), {})
        card_malus = cards.get("malus", 0.0)
        goals, assists = maps["ga"].get((md, pid), (0, 0))
        events = {"goals": goals, "assists": assists,
                  "yellow": cards.get("yellow", 0),
                  "red": cards.get("red", 0) + cards.get("second_yellow", 0),
                  "own_goals": e.get("own_goals", 0)}
        base = {"player_id": pid, "name": p["name"], "role": role, "lineup_role": lrole,
                "minutes": e.get("minutes", 0), "entered": False, "entered_for": None,
                "replaced_by": None, "events": events}
        why = maps["expl"].get((md, pid), {})
        if (md, pid) not in maps["rated"]:
            return {**base, "sv": True, "voto_puro": None, "bonus": 0.0, "malus": 0.0,
                    "fantavoto": None}
        vp = maps["vp"][(md, pid)]
        if role == "POR":
            # Keeper: voto puro from the GK channel (in vp), the -1/goal conceded in
            # the malus layer, plus own goals and penalty saves from cache.
            bonus = 3 * e.get("pen_save", 0)
            malus = 2 * e.get("own_goals", 0) + maps["gk_conceded"].get((md, pid), 0) + card_malus
        else:
            bonus = 3 * goals + 1 * assists
            malus = 2 * e.get("own_goals", 0) + 3 * e.get("pen_miss", 0) + card_malus
        return {**base, "sv": False, "voto_puro": round(vp, 1),
                "bonus": float(bonus), "malus": float(malus),
                "fantavoto": round(vp + bonus - malus, 1), **why}

    def _score_team(self, starters, bench, md, maps, max_subs):
        roles = {p["player_id"]: ROLE_TO_LINEUP[p["role"]] for p in starters + bench}
        s_lines = {p["player_id"]: self._line(p, md, maps) for p in starters}
        b_lines = {p["player_id"]: self._line(p, md, maps) for p in bench}
        s_ids = [p["player_id"] for p in starters]
        b_ids = [p["player_id"] for p in bench]
        voted = {pid for pid in s_ids + b_ids
                 if not (s_lines.get(pid) or b_lines.get(pid))["sv"]}
        res = apply_classic_substitutions(s_ids, b_ids, roles, voted, max_subs=max_subs)
        name = {p["player_id"]: p["name"] for p in starters + bench}
        for out_pid, in_pid in res.subs:
            s_lines[out_pid]["replaced_by"] = {"player_id": in_pid, "name": name[in_pid]}
            b_lines[in_pid]["entered"] = True
            b_lines[in_pid]["entered_for"] = {"player_id": out_pid, "name": name[out_pid]}
        # total = sum fantavoto of the effective XI (unresolved s.v. -> baseline 6)
        total = 0.0
        eff_lines = []
        for pid in res.effective:
            line = s_lines.get(pid) or b_lines.get(pid)
            eff_lines.append(line)
            total += line["fantavoto"] if line["fantavoto"] is not None else SV_BASELINE
        # Defence modifier: gate on STARTING defenders; value from the effective XI's
        # best 3 defender voti puri + GK voto puro (excluding bonus/malus).
        starter_lroles = [ROLE_TO_LINEUP[p["role"]] for p in starters]
        def_votes = [l["voto_puro"] for l in eff_lines
                     if l["lineup_role"] == "DEF" and l["voto_puro"] is not None]
        gk_vote = next((l["voto_puro"] for l in eff_lines if l["lineup_role"] == "GK"), None)
        defense = compute_defense_bonus(starter_lroles, def_votes, gk_vote)
        starters_out = [s_lines[p["player_id"]] for p in starters]
        bench_out = [b_lines[p["player_id"]] for p in bench]
        subs = [{"out": {"player_id": o, "name": name[o]}, "in": {"player_id": i, "name": name[i]}}
                for o, i in res.subs]
        return {"starters": starters_out, "bench": bench_out, "substitutions": subs,
                "base_total": round(total, 2), "defense": defense}

    # -- roster draft + depth chart --------------------------------------

    def _draft(self, cs_id, team_count, min_app, seed):
        apps = dict(MatchAppearance.objects.filter(match__competition_season_id=cs_id)
                    .values("player_id").annotate(n=Count("id"))
                    .values_list("player_id", "n"))
        by_role: dict[str, list[dict]] = defaultdict(list)
        for p in Player.objects.exclude(classic_role="").values(
                "id", "classic_role", "short_name", "full_name"):
            n = apps.get(p["id"], 0)
            if n < min_app:
                continue
            by_role[p["classic_role"]].append(
                {"player_id": p["id"], "role": p["classic_role"],
                 "name": p["short_name"] or p["full_name"] or str(p["id"]),
                 "apps": n, "price": max(1, n // 2)})
        for role, need in SQUAD.items():
            if len(by_role.get(role, [])) < need * team_count:
                raise CommandError(f"pool too small for {role}")
            by_role[role].sort(key=lambda d: (-d["apps"], d["player_id"]))
        squads = [[] for _ in range(team_count)]
        for role, need in SQUAD.items():
            pool, idx = by_role[role], 0
            for rnd in range(need):
                order = range(team_count) if rnd % 2 == 0 else range(team_count - 1, -1, -1)
                for t in order:
                    squads[t].append(pool[idx]); idx += 1
        return squads

    def _depth_chart(self, squad, module):
        """Fixed XI for the given (DEF, MID, ATT) module by season regularity, plus
        the ordered bench (priority)."""
        d, m, a = module
        formation = {"GK": 1, "DEF": d, "MID": m, "ATT": a}
        by_lrole: dict[str, list[dict]] = defaultdict(list)
        for p in squad:
            by_lrole[ROLE_TO_LINEUP[p["role"]]].append(p)
        for v in by_lrole.values():
            v.sort(key=lambda p: (-p["apps"], p["player_id"]))
        starters, used = [], set()
        for lrole, n in formation.items():
            for p in by_lrole.get(lrole, [])[:n]:
                starters.append(p); used.add(p["player_id"])
        # bench ordered: GK backup first, then by regularity (priority list)
        bench = sorted((p for p in squad if p["player_id"] not in used),
                       key=lambda p: (ROLE_TO_LINEUP[p["role"]] != "GK", -p["apps"], p["player_id"]))
        return starters, bench

    @staticmethod
    def _rr_rounds(team_ids, seed):
        rng = random.Random(seed)
        work = list(team_ids); rng.shuffle(work)
        if len(work) % 2:
            work.append(-1)
        rounds = []
        for r in range(len(work) - 1):
            pairs = []
            for i in range(len(work) // 2):
                a, b = work[i], work[-1 - i]
                if a != -1 and b != -1:
                    pairs.append((a, b) if r % 2 == 0 else (b, a))
            rounds.append(pairs)
            work = [work[0], work[-1], *work[1:-1]]
        return rounds

    # -- main ------------------------------------------------------------

    @transaction.atomic
    def handle(self, *args, **opts):
        cs_id = opts["competition_season"]
        season = CompetitionSeason.objects.filter(id=cs_id).first()
        if season is None:
            raise CommandError(f"CompetitionSeason {cs_id} not found")
        owner, _ = User.objects.get_or_create(username=str(opts["owner"]))
        team_count, cycles = int(opts["teams"]), int(opts["cycles"])
        league_name = str(opts["league_name"])

        self.stdout.write("Precomputing classic fantavoti from real data…")
        maps = self._maps(cs_id)
        squads = self._draft(cs_id, team_count, int(opts["min_appearances"]), int(opts["seed"]))

        for prior in FantasyLeague.objects.filter(name=league_name, owner=owner):
            FantasyFixture.objects.filter(competition__league=prior).delete()
            CompetitionTeam.objects.filter(competition__league=prior).delete()
            FantasyRosterSlot.objects.filter(team__league=prior).delete()
            LeaguePlayerRole.objects.filter(league=prior).delete()
            SavedLineupSnapshot.objects.filter(league_id=str(prior.id)).delete()
            FantasyTeam.objects.filter(league=prior).delete()
            LeagueMembership.objects.filter(league=prior).delete()
            FantasyMatchday.objects.filter(league=prior).delete()
            FantasyCompetition.objects.filter(league=prior).delete()
            prior.delete()

        league = FantasyLeague.objects.create(
            name=league_name, owner=owner, market_open=False,
            mode=FantasyLeague.MODE_CLASSIC, reference_season=season)
        competition = FantasyCompetition.objects.create(
            league=league, name=str(opts["competition_name"]),
            competition_type=FantasyCompetition.TYPE_ROUND_ROBIN,
            status=FantasyCompetition.STATUS_DONE)

        now = timezone.now()
        n_rounds = 9 * cycles
        real_matchdays = list(range(1, n_rounds + 1))
        matchday_by_real = {
            rm: FantasyMatchday.objects.create(
                league=league, real_competition_season=season, real_matchday=rm,
                status=FantasyMatchday.STATUS_CONCLUDED, concluded_at=now, concluded_by=owner)
            for rm in real_matchdays}

        teams, depth = [], {}
        for i in range(team_count):
            if i == 0:
                membership, _ = LeagueMembership.objects.get_or_create(
                    league=league, user=owner, defaults={"role": LeagueMembership.ROLE_ADMIN})
            else:
                user, created = User.objects.get_or_create(username=f"classicdemo_mgr_{i}")
                if created:
                    user.set_unusable_password(); user.save()
                membership = LeagueMembership.objects.create(
                    league=league, user=user, role=LeagueMembership.ROLE_MANAGER)
            team = FantasyTeam.objects.create(league=league, manager=membership, name=f"Demo Team {i+1}")
            teams.append(team)
            depth[team.id] = self._depth_chart(squads[i], MODULES[i % len(MODULES)])
            CompetitionTeam.objects.create(competition=competition, team=team,
                                           source=CompetitionTeam.SOURCE_MANUAL)
            FantasyRosterSlot.objects.bulk_create(
                [FantasyRosterSlot(team=team, player_id=p["player_id"], purchase_price=p["price"])
                 for p in squads[i]])
            LeaguePlayerRole.objects.bulk_create(
                [LeaguePlayerRole(league=league, player_id=p["player_id"], role=p["role"],
                                  source=LeaguePlayerRole.SOURCE_SEED) for p in squads[i]])

        # SavedLineupSnapshot once per team & matchday (fixed depth-chart XI)
        for team in teams:
            starters, bench = depth[team.id]
            gk = next((p["player_id"] for p in starters if p["role"] == "POR"), None)
            for rm in real_matchdays:
                SavedLineupSnapshot.objects.update_or_create(
                    league_id=str(league.id), matchday_id=str(rm),
                    lineup_id=f"team{team.id}:comp{competition.id}",
                    defaults={"gk_player_id": str(gk) if gk else None,
                              "starter_player_ids": [p["player_id"] for p in starters if p["role"] != "POR"],
                              "bench_player_ids": [p["player_id"] for p in bench],
                              "starter_backups": []})

        schedule = self._rr_rounds([t.id for t in teams], int(opts["seed"]))
        team_by_id = {t.id: t for t in teams}
        n_fixtures = 0
        for idx, rm in enumerate(real_matchdays, start=1):
            cycle = (idx - 1) // 9
            pairs = schedule[(idx - 1) % 9]
            if cycle % 2 == 1:
                pairs = [(b, a) for a, b in pairs]
            score = {}
            for tid in (t.id for t in teams):
                st, bn = depth[tid]
                score[tid] = self._score_team(st, bn, rm, maps, league.max_substitutions)
            for home_id, away_id in pairs:
                hs, as_ = score[home_id], score[away_id]
                self._apply_defense_bonus(hs, as_, league)
                fixture = FantasyFixture.objects.create(
                    competition=competition, fantasy_matchday=matchday_by_real[rm],
                    round_no=idx, leg_no=1,
                    home_team=team_by_id[home_id], away_team=team_by_id[away_id],
                    status=FantasyFixture.STATUS_FINISHED,
                    home_total=float(hs["goals"]), away_total=float(as_["goals"]))
                FantasyFixtureDetail.objects.create(
                    fixture=fixture, vfoot_home=hs["total"], vfoot_away=as_["total"],
                    payload=self._payload(fixture.id, idx, rm,
                                          team_by_id[home_id], team_by_id[away_id], hs, as_))
                for team, sc in ((team_by_id[home_id], hs), (team_by_id[away_id], as_)):
                    starters = [l for l in sc["starters"]]
                    gk = next((l["player_id"] for l in starters if l["role"] == "POR"), None)
                    FantasyLineupSubmission.objects.create(
                        fixture=fixture, team=team, gk_player_id=gk,
                        starter_player_ids=[l["player_id"] for l in starters],
                        bench_player_ids=[l["player_id"] for l in sc["bench"]],
                        submitted_by=owner)
                n_fixtures += 1

        self._ctx = {"depth": depth, "maps": maps, "league": league,
                     "mbr": matchday_by_real, "tbi": {t.id: t for t in teams}, "owner": owner}
        cup_msg = ""
        if not opts["no_cup"]:
            cfx, champ = self._build_cup(league, teams)
            gfx, gchamp = self._build_group_cup(league, teams)
            cup_msg = f" + Coppa Classic ({cfx} fx, {champ}) + Coppa Gironi ({gfx} fx, {gchamp})"

        sample = self._depth_chart(squads[0], MODULES[0])[0]
        assert is_legal_classic([ROLE_TO_LINEUP[p["role"]] for p in sample]), "illegal demo XI"
        self.stdout.write(self.style.SUCCESS(
            f"Seeded classic league '{league.name}' (id {league.id}) owned by {owner.username}: "
            f"{team_count} teams, {len(real_matchdays)} matchdays, {n_fixtures} fixtures{cup_msg}. "
            f"Open the frontend as '{owner.username}', team 'Demo Team 1'."))

    def _play_fixture(self, comp, stage_obj, rno, rm, home_id, away_id, stage_label=None):
        """Score one fixture (classic engine + defence bonus), persist it (+detail +
        lineups), and return the winner id (decisive: goals → total → home)."""
        c = self._ctx
        hs = self._score_team(*c["depth"][home_id], rm, c["maps"], c["league"].max_substitutions)
        as_ = self._score_team(*c["depth"][away_id], rm, c["maps"], c["league"].max_substitutions)
        self._apply_defense_bonus(hs, as_, c["league"])
        tbi = c["tbi"]
        fx = FantasyFixture.objects.create(
            competition=comp, stage=stage_obj, fantasy_matchday=c["mbr"][rm],
            round_no=rno, leg_no=1, home_team=tbi[home_id], away_team=tbi[away_id],
            status=FantasyFixture.STATUS_FINISHED,
            home_total=float(hs["goals"]), away_total=float(as_["goals"]))
        FantasyFixtureDetail.objects.create(
            fixture=fx, vfoot_home=hs["total"], vfoot_away=as_["total"],
            payload=self._payload(fx.id, rno, rm, tbi[home_id], tbi[away_id], hs, as_, stage=stage_label))
        for team, sc in ((tbi[home_id], hs), (tbi[away_id], as_)):
            gk = next((l["player_id"] for l in sc["starters"] if l["role"] == "POR"), None)
            FantasyLineupSubmission.objects.create(
                fixture=fx, team=team, gk_player_id=gk,
                starter_player_ids=[l["player_id"] for l in sc["starters"]],
                bench_player_ids=[l["player_id"] for l in sc["bench"]], submitted_by=c["owner"])
        if hs["goals"] != as_["goals"]:
            return home_id if hs["goals"] > as_["goals"] else away_id
        if hs["total"] != as_["total"]:
            return home_id if hs["total"] > as_["total"] else away_id
        return home_id

    def _build_cup(self, league, teams):
        """A FLAT single-elimination cup over the second half (no stages)."""
        tbi = self._ctx["tbi"]
        cup = FantasyCompetition.objects.create(
            league=league, name="Coppa Classic",
            competition_type=FantasyCompetition.TYPE_KNOCKOUT,
            status=FantasyCompetition.STATUS_DONE)
        current = [t.id for t in teams[:CUP_TEAMS]]
        for tid in current:
            CompetitionTeam.objects.create(competition=cup, team=tbi[tid],
                                           source=CompetitionTeam.SOURCE_MANUAL)
        n_fx = 0
        for rno, (stage, rm) in enumerate(CUP_ROUNDS, start=1):
            nxt = []
            for i in range(0, len(current), 2):
                nxt.append(self._play_fixture(cup, None, rno, rm, current[i], current[i + 1], stage_label=stage))
                n_fx += 1
            current = nxt
        return n_fx, tbi[current[0]].name

    def _build_group_cup(self, league, teams):
        """A STAGED cup: 2 round-robin groups (4 teams each) over md 19-21, then a
        knockout (semifinali md28, finale md33) seeded by the group tables. Uses real
        CompetitionStage rows so the results page renders group tables + a bracket."""
        tbi = self._ctx["tbi"]
        cup = FantasyCompetition.objects.create(
            league=league, name="Coppa Gironi",
            competition_type=FantasyCompetition.TYPE_KNOCKOUT,
            status=FantasyCompetition.STATUS_DONE)
        eight = [t.id for t in teams[:8]]
        groups = {"Girone A": eight[:4], "Girone B": eight[4:]}
        group_rmds = [19, 20, 21]
        n_fx = 0
        group_rank = {}
        for gname, gteams in groups.items():
            stage = CompetitionStage.objects.create(
                competition=cup, name=gname, stage_type=CompetitionStage.TYPE_ROUND_ROBIN,
                order_index=1, status=CompetitionStage.STATUS_DONE)
            for seed_i, tid in enumerate(gteams, start=1):
                CompetitionStageParticipant.objects.create(
                    stage=stage, team=tbi[tid], seed=seed_i,
                    source=CompetitionStageParticipant.SOURCE_MANUAL)
            pts = {tid: [0, 0, 0] for tid in gteams}  # [points, gf, ga]
            for rno, (rm, pairs) in enumerate(zip(group_rmds, self._rr_rounds(gteams, 7)), start=1):
                for home_id, away_id in pairs:
                    fx = self._fixture_goals(cup, stage, rno, rm, home_id, away_id)
                    n_fx += 1
                    hg, ag = fx
                    pts[home_id][1] += hg; pts[home_id][2] += ag
                    pts[away_id][1] += ag; pts[away_id][2] += hg
                    if hg > ag:
                        pts[home_id][0] += 3
                    elif ag > hg:
                        pts[away_id][0] += 3
                    else:
                        pts[home_id][0] += 1; pts[away_id][0] += 1
            group_rank[gname] = sorted(
                gteams, key=lambda t: (pts[t][0], pts[t][1] - pts[t][2], pts[t][1]), reverse=True)

        ko = CompetitionStage.objects.create(
            competition=cup, name="Fase finale", stage_type=CompetitionStage.TYPE_KNOCKOUT,
            order_index=2, status=CompetitionStage.STATUS_DONE)
        a, b = group_rank["Girone A"], group_rank["Girone B"]
        for tid in (a[0], a[1], b[0], b[1]):
            CompetitionStageParticipant.objects.create(
                stage=ko, team=tbi[tid], source=CompetitionStageParticipant.SOURCE_RULE)
        # semifinali (round 1): A1 v B2, B1 v A2
        w1 = self._play_fixture(cup, ko, 1, 28, a[0], b[1], stage_label="Semifinale")
        w2 = self._play_fixture(cup, ko, 1, 28, b[0], a[1], stage_label="Semifinale")
        # finale (round 2)
        champ = self._play_fixture(cup, ko, 2, 33, w1, w2, stage_label="Finale")
        n_fx += 3
        return n_fx, tbi[champ].name

    def _fixture_goals(self, comp, stage_obj, rno, rm, home_id, away_id):
        """Like _play_fixture but returns the (home_goals, away_goals) for group tables."""
        c = self._ctx
        hs = self._score_team(*c["depth"][home_id], rm, c["maps"], c["league"].max_substitutions)
        as_ = self._score_team(*c["depth"][away_id], rm, c["maps"], c["league"].max_substitutions)
        self._apply_defense_bonus(hs, as_, c["league"])
        tbi = c["tbi"]
        fx = FantasyFixture.objects.create(
            competition=comp, stage=stage_obj, fantasy_matchday=c["mbr"][rm],
            round_no=rno, leg_no=1, home_team=tbi[home_id], away_team=tbi[away_id],
            status=FantasyFixture.STATUS_FINISHED,
            home_total=float(hs["goals"]), away_total=float(as_["goals"]))
        FantasyFixtureDetail.objects.create(
            fixture=fx, vfoot_home=hs["total"], vfoot_away=as_["total"],
            payload=self._payload(fx.id, rno, rm, tbi[home_id], tbi[away_id], hs, as_, stage=stage_obj.name))
        for team, sc in ((tbi[home_id], hs), (tbi[away_id], as_)):
            gk = next((l["player_id"] for l in sc["starters"] if l["role"] == "POR"), None)
            FantasyLineupSubmission.objects.create(
                fixture=fx, team=team, gk_player_id=gk,
                starter_player_ids=[l["player_id"] for l in sc["starters"]],
                bench_player_ids=[l["player_id"] for l in sc["bench"]], submitted_by=c["owner"])
        return hs["goals"], as_["goals"]

    @staticmethod
    def _apply_defense_bonus(hs, as_, league):
        """Resolve each team's final total (base + defence modifier) and classic goals,
        mutating the two score dicts in place. The modifier is added to the team's own
        total or subtracted from the opponent's, per league config."""
        enabled = league.defense_bonus_enabled
        hb = hs["defense"]["bonus"] if enabled else 0.0
        ab = as_["defense"]["bonus"] if enabled else 0.0
        sub_opp = league.defense_bonus_mode == FantasyLeague.DEF_BONUS_SUB_OPP
        # how each team's total is adjusted (for display): own bonus added, or the
        # opponent's bonus subtracted.
        mode = league.defense_bonus_mode if enabled else None
        hs["defense"]["applied"] = -ab if sub_opp else hb
        as_["defense"]["applied"] = -hb if sub_opp else ab
        hs["defense"]["mode"] = as_["defense"]["mode"] = mode
        hs["total"] = round(hs["base_total"] + hs["defense"]["applied"], 2)
        as_["total"] = round(as_["base_total"] + as_["defense"]["applied"], 2)
        hs["goals"] = classic_goals(hs["total"])
        as_["goals"] = classic_goals(as_["total"])

    def _payload(self, fid, rnd, rm, home, away, hs, as_, stage=None):
        result = "home" if hs["goals"] > as_["goals"] else "away" if as_["goals"] > hs["goals"] else "draw"
        return {
            "mode": "classic",
            "fixture_id": fid, "fantasy_round": rnd, "real_matchday": rm, "stage": stage,
            "home_team": home.name, "away_team": away.name,
            "home_goals": hs["goals"], "away_goals": as_["goals"],
            "home_total": hs["total"], "away_total": as_["total"],
            "defense_bonus_mode": hs["defense"].get("mode"),
            "result": result,
            "home": hs, "away": as_,
        }
