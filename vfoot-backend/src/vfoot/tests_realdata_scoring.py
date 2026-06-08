from django.test import TestCase

from realdata.models import Match, PlayerZoneFeature, SIDE_AWAY, SIDE_HOME
from vfoot.services.realdata_scoring import (
    build_player_real_zone_profile,
    compute_real_match_zone_duels,
    contract_zone_to_statsbomb,
    starting_player_ids_for_real_match,
    statsbomb_zone_to_contract,
)


class RealDataScoringTests(TestCase):
    databases = {"default"}

    @classmethod
    def setUpTestData(cls):
        cls.match = Match.objects.filter(player_zone_features__feature_key="touches").distinct().first()

    def test_zone_key_round_trip(self):
        self.assertEqual(statsbomb_zone_to_contract("Z_3_2"), "z0203")
        self.assertEqual(contract_zone_to_statsbomb("z0203"), "Z_3_2")

    def test_player_presence_is_normalized_when_data_exists(self):
        if self.match is None:
            self.skipTest("No realdata match with touches is available.")
        player_id = (
            PlayerZoneFeature.objects.filter(match=self.match, feature_key="touches")
            .values_list("player_id", flat=True)
            .first()
        )
        profile = build_player_real_zone_profile(match=self.match, player_id=player_id)

        self.assertIsNotNone(profile)
        self.assertAlmostEqual(sum(profile.presence.values()), 1.0, places=8)
        self.assertGreater(profile.total_presence_volume, 0)
        self.assertGreaterEqual(profile.pure_vote, 4.0)
        self.assertLessEqual(profile.pure_vote, 8.5)

    def test_real_match_duels_return_contract_shape(self):
        if self.match is None:
            self.skipTest("No realdata match with touches is available.")
        home_player_ids = starting_player_ids_for_real_match(self.match, SIDE_HOME)
        away_player_ids = starting_player_ids_for_real_match(self.match, SIDE_AWAY)
        if not home_player_ids or not away_player_ids:
            self.skipTest("No home/away player ids are available for realdata match.")

        payload = compute_real_match_zone_duels(
            match=self.match,
            home_player_ids=home_player_ids,
            away_player_ids=away_player_ids,
        )

        self.assertEqual(len(payload["zone_results"]), 20)
        self.assertEqual(len(payload["zone_maps"]["winner_map"]["values"]), 20)
        self.assertGreater(payload["score"]["home_total"], 0)
        self.assertGreater(payload["score"]["away_total"], 0)
        self.assertEqual(payload["provenance"]["formula_version"], "realdata_scoring_v1")

