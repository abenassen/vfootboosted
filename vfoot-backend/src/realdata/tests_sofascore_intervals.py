"""Gli intervalli in campo dagli incidents, con la coppia uscito/entrato.

Tre cose da tenere ferme: la coppia si salva ESATTA (non per minuto, che con tre
cambi insieme sarebbe un'invenzione); una partita in corso lascia la fine aperta
con ``unknown_end`` e non con un fischio finale che non c'e' stato; e l'importatore
li scrive da solo a ogni giro — prima li scriveva soltanto un comando a mano, e la
stagione in corso in produzione non ne aveva nessuno.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import TestCase

from realdata.models import (
    INTERVAL_FINAL_WHISTLE, INTERVAL_RED_CARD, INTERVAL_STARTING_XI,
    INTERVAL_SUBSTITUTION_OFF, INTERVAL_SUBSTITUTION_ON, INTERVAL_UNKNOWN_END,
    Competition, CompetitionSeason, Match, MatchAppearance, Player,
    PlayerOnPitchInterval, PROVIDER_SOFASCORE, Season, Team, TeamSeason,
)
from realdata.services.sofascore_adapter import ingest_sofascore_matches
from realdata.services.sofascore_client import SofaScoreClient
from realdata.services.sofascore_intervals import (
    appearances_of, build_intervals, replace_intervals, substitution_pairs,
)


def _sub(minute, pin, pout):
    return {"incidentType": "substitution", "time": minute,
            "playerIn": {"id": pin}, "playerOut": {"id": pout}}


class _Fixture(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.home_ts = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Como"))
        self.away_ts = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Sassuolo"))
        self.match = Match.objects.create(
            competition_season=self.cs, matchday=1, home_team=self.home_ts,
            away_team=self.away_ts, status=Match.STATUS_FINISHED,
            external_source="sofascore", external_id="1")
        self.players = {}
        for ext, name, starter, mins in [
            (101, "Paz", True, 58), (102, "Diao", True, 50), (103, "Perrone", True, 69),
            (111, "Lahdo", False, 32), (112, "Kuhn", False, 40), (113, "Addai", False, 21),
            (114, "Panchinaro", False, 0),
        ]:
            p = Player.objects.create(full_name=name, short_name=name, external_id=str(ext))
            self.players[ext] = p
            MatchAppearance.objects.create(
                match=self.match, player=p, team_season=self.home_ts, side="home",
                minutes_played=mins, is_starter=starter)
        self.ext_to_local = {str(ext): p.id for ext, p in self.players.items()}

    def _build(self, incidents, **kw):
        rows, skipped = build_intervals(self.match, incidents, appearances_of(self.match),
                                        self.ext_to_local, **kw)
        return {r.player_id: r for r in rows}, skipped


class BuildIntervalsTests(_Fixture):
    def test_pair_is_saved_on_both_ends(self):
        by, _ = self._build([_sub(58, 111, 101), _sub(50, 112, 102)])
        paz, lahdo = by[self.players[101].id], by[self.players[111].id]
        self.assertEqual((paz.start_minute, paz.end_minute, paz.end_reason),
                         (0, 58, INTERVAL_SUBSTITUTION_OFF))
        self.assertEqual((lahdo.start_minute, lahdo.start_reason, lahdo.end_minute),
                         (58, INTERVAL_SUBSTITUTION_ON, 90))
        pair = {"in": lahdo.player_id, "out": paz.player_id, "minute": 58}
        self.assertEqual(paz.payload, {"exit": pair})
        self.assertEqual(lahdo.payload, {"entry": pair})
        # chi non e' entrato non ha intervalli
        self.assertNotIn(self.players[114].id, by)

    def test_same_minute_substitutions_stay_exact(self):
        # Due cambi al 58': l'accoppiamento per minuto non saprebbe chi e' entrato
        # per chi. La coppia salvata si'.
        by, _ = self._build([_sub(58, 111, 101), _sub(58, 112, 102)])
        self.assertEqual(by[self.players[111].id].payload["entry"]["out"], self.players[101].id)
        self.assertEqual(by[self.players[112].id].payload["entry"]["out"], self.players[102].id)

    def test_substitute_later_substituted_carries_both(self):
        by, _ = self._build([_sub(50, 112, 102), _sub(80, 113, 112)])
        kuhn = by[self.players[112].id]
        self.assertEqual((kuhn.start_minute, kuhn.end_minute), (50, 80))
        self.assertEqual(kuhn.payload["entry"]["out"], self.players[102].id)
        self.assertEqual(kuhn.payload["exit"]["in"], self.players[113].id)

    def test_live_match_leaves_the_end_open(self):
        by, _ = self._build([_sub(58, 111, 101)], finished=False)
        perrone = by[self.players[103].id]
        self.assertEqual((perrone.end_minute, perrone.end_reason), (90, INTERVAL_UNKNOWN_END))
        self.assertEqual(by[self.players[101].id].end_reason, INTERVAL_SUBSTITUTION_OFF)
        by, _ = self._build([_sub(58, 111, 101)], finished=True)
        self.assertEqual(by[self.players[103].id].end_reason, INTERVAL_FINAL_WHISTLE)

    def test_red_card_ends_the_interval(self):
        by, _ = self._build([{"incidentType": "card", "incidentClass": "red", "time": 70,
                              "player": {"id": 103}}])
        self.assertEqual((by[self.players[103].id].end_minute,
                          by[self.players[103].id].end_reason), (70, INTERVAL_RED_CARD))

    def test_self_substitution_is_ignored(self):
        # «X entra per X» sta nei dati: presa alla lettera cancellava il suo
        # intervallo da titolare. Deve restare quello che si sapeva prima.
        by, skipped = self._build([_sub(85, 101, 101)])
        paz = by[self.players[101].id]
        self.assertEqual((paz.start_minute, paz.start_reason, paz.end_minute, paz.end_reason),
                         (0, INTERVAL_STARTING_XI, 90, INTERVAL_FINAL_WHISTLE))
        self.assertEqual(paz.payload, {})
        self.assertEqual(skipped, 0)

    def test_unknown_ids_are_skipped_not_invented(self):
        by, _ = self._build([_sub(58, 999, 101)])
        paz = by[self.players[101].id]
        self.assertEqual(paz.end_minute, 58)
        self.assertEqual(paz.payload, {})   # niente coppia con un id che non traduce


class SubstitutionPairsTests(_Fixture):
    def test_reads_saved_pairs(self):
        rows, _ = build_intervals(self.match, [_sub(58, 111, 101), _sub(58, 112, 102),
                                               _sub(80, 113, 112)],
                                  appearances_of(self.match), self.ext_to_local)
        replace_intervals(self.match, rows)
        pairs = substitution_pairs(self.match.id)
        self.assertEqual(
            {(p["out"], p["in"], p["minute"]) for p in pairs},
            {(self.players[101].id, self.players[111].id, 58),
             (self.players[102].id, self.players[112].id, 58),
             (self.players[112].id, self.players[113].id, 80)})
        self.assertTrue(all(p["side"] == "home" for p in pairs))

    def _legacy(self, minute_pairs):
        """Righe come le scriveva il comando prima: minuti e ragioni, payload vuoto."""
        rows = []
        for minute, pin, pout in minute_pairs:
            rows.append(PlayerOnPitchInterval(
                match=self.match, player_id=self.players[pout].id, team_season=self.home_ts,
                team_side="home", start_minute=0, end_minute=minute,
                start_reason=INTERVAL_STARTING_XI, end_reason=INTERVAL_SUBSTITUTION_OFF,
                provider=PROVIDER_SOFASCORE))
            rows.append(PlayerOnPitchInterval(
                match=self.match, player_id=self.players[pin].id, team_season=self.home_ts,
                team_side="home", start_minute=minute, end_minute=90,
                start_reason=INTERVAL_SUBSTITUTION_ON, end_reason=INTERVAL_FINAL_WHISTLE,
                provider=PROVIDER_SOFASCORE))
        PlayerOnPitchInterval.objects.bulk_create(rows)

    def test_legacy_rows_pair_by_minute_only_when_unambiguous(self):
        self._legacy([(50, 112, 102), (58, 111, 101), (58, 113, 103)])
        pairs = {(p["out"], p["in"]) for p in substitution_pairs(self.match.id)}
        # al 50' uno e' uscito e uno e' entrato: la coppia si deduce
        self.assertIn((self.players[102].id, self.players[112].id), pairs)
        # al 58' due e due: inventare l'accoppiamento sbaglierebbe una volta su due
        self.assertEqual(len(pairs), 1)


class _Wire(SofaScoreClient):
    def __init__(self, cache_dir, payloads):
        super().__init__(cache_dir, min_delay=0.0, jitter=0.0, max_retries=1,
                         logger=lambda _m: None)
        self.payloads = payloads

    def _raw_get(self, path: str):
        return self.payloads.get(path)


class ImporterWritesIntervalsTests(TestCase):
    """L'importatore scrive gli intervalli a ogni giro, dagli stessi incidents dei
    cartellini — e a partita in corso lascia la fine aperta."""

    MATCH = 16283209

    def _payloads(self, status: str, subs: list[dict]):
        def entry(pid, name, starter, minutes):
            return {"player": {"id": pid, "name": name, "shortName": name},
                    "substitute": not starter, "position": "M",
                    "statistics": {"minutesPlayed": minutes, "touches": 40}}
        event = {"id": self.MATCH, "status": {"type": status},
                 "startTimestamp": 1801424700, "roundInfo": {"round": 7},
                 "homeScore": {"current": 1}, "awayScore": {"current": 0},
                 "homeTeam": {"id": 2696, "name": "Torino", "shortName": "Torino"},
                 "awayTeam": {"id": 2697, "name": "Inter", "shortName": "Inter"}}
        heat = {"heatmap": [{"x": 50, "y": 50}]}
        return {
            f"/api/v1/event/{self.MATCH}": {"event": event},
            f"/api/v1/event/{self.MATCH}/lineups": {
                "home": {"players": [entry(1, "Primo", True, 60), entry(2, "Secondo", False, 30)]},
                "away": {"players": [entry(3, "Terzo", True, 90)]}},
            f"/api/v1/event/{self.MATCH}/shotmap": {"shotmap": []},
            f"/api/v1/event/{self.MATCH}/incidents": {"incidents": subs},
            **{f"/api/v1/event/{self.MATCH}/player/{p}/heatmap": heat for p in (1, 2, 3)},
        }

    def _ingest(self, status, subs, only_finished):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        client = _Wire(Path(tmp.name), self._payloads(status, subs))
        return ingest_sofascore_matches(
            scraper=client, year="26/27", match_ids=[self.MATCH],
            only_finished=only_finished, skip_existing=False, logger=lambda _m: None)

    def test_finished_import_writes_paired_intervals(self):
        result = self._ingest("finished", [_sub(60, 2, 1)], only_finished=True)
        self.assertEqual(result.on_pitch_intervals, 3)
        match = Match.objects.get(external_id=str(self.MATCH))
        by = {iv.player.external_id: iv for iv in
              PlayerOnPitchInterval.objects.filter(match=match).select_related("player")}
        self.assertEqual((by["1"].end_minute, by["1"].end_reason), (60, INTERVAL_SUBSTITUTION_OFF))
        self.assertEqual(by["1"].payload["exit"]["in"], by["2"].player_id)
        self.assertEqual(by["2"].payload["entry"]["out"], by["1"].player_id)
        self.assertEqual(by["3"].end_reason, INTERVAL_FINAL_WHISTLE)
        # e la pagella li legge come coppia
        pairs = substitution_pairs(match.id)
        self.assertEqual([(p["out"], p["in"], p["minute"]) for p in pairs],
                         [(by["1"].player_id, by["2"].player_id, 60)])

    def test_live_import_leaves_the_end_open_and_is_idempotent(self):
        self._ingest("inprogress", [], only_finished=False)
        match = Match.objects.get(external_id=str(self.MATCH))
        ends = set(PlayerOnPitchInterval.objects.filter(match=match)
                   .values_list("end_reason", flat=True))
        self.assertEqual(ends, {INTERVAL_UNKNOWN_END})
        # il giro dopo porta il cambio: le righe si riscrivono, non si sommano
        self._ingest("inprogress", [_sub(60, 2, 1)], only_finished=False)
        self.assertEqual(PlayerOnPitchInterval.objects.filter(match=match).count(), 3)
        self.assertEqual(PlayerOnPitchInterval.objects.filter(
            match=match, end_reason=INTERVAL_SUBSTITUTION_OFF).count(), 1)


class AliasResolutionTests(_Fixture):
    """Un giocatore che SofaScore chiama con un id che da noi sta SOLO in
    PlayerAlias — in produzione uno su quattro nella 26-27 — deve avere il suo
    cambio riconosciuto come tutti gli altri."""

    def test_alias_only_player_is_resolved(self):
        from realdata.models import PlayerAlias
        from realdata.services.sofascore_intervals import ext_to_local_for
        paz = self.players[101]
        paz.external_id = "tm-777"          # l'id in Player e' quello di un'altra fonte
        paz.save()
        PlayerAlias.objects.create(player=paz, source=PROVIDER_SOFASCORE, alias="101")
        mapping = ext_to_local_for(appearances_of(self.match))
        self.assertEqual(mapping["101"], paz.id)
        self.assertEqual(mapping["tm-777"], paz.id)
        rows, _ = build_intervals(self.match, [_sub(58, 111, 101)],
                                  appearances_of(self.match), mapping)
        by = {r.player_id: r for r in rows}
        self.assertEqual((by[paz.id].end_minute, by[paz.id].end_reason),
                         (58, INTERVAL_SUBSTITUTION_OFF))
        self.assertEqual(by[paz.id].payload["exit"]["in"], self.players[111].id)

    def test_real_id_beats_synthetic_alias(self):
        from realdata.models import PlayerAlias
        from realdata.services.sofascore_intervals import ext_to_local_for
        paz = self.players[101]
        PlayerAlias.objects.create(player=paz, source=PROVIDER_SOFASCORE, alias="900000101")
        mapping = ext_to_local_for(appearances_of(self.match))
        self.assertEqual(mapping["101"], paz.id)
        self.assertEqual(mapping["900000101"], paz.id)
