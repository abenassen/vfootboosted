"""Il numero di difensori, dal primo calcio d'inizio in poi.

LA FALLA. Schiero una difesa a quattro per il modificatore. Due difensori
prendono 5. A quel punto SO che il modificatore non arrivera' — e mi conviene
togliere un difensore che non ha ancora giocato per metterci un attaccante. E'
una scommessa disdetta a risultato parziale noto, e funziona anche al contrario:
aggiungere il quarto difensore dopo aver visto due bei voti.

Il vincolo e' sul NUMERO DI DIFENSORI e non sul modulo, perche' il modificatore
guarda solo quelli. Vale in due momenti — su cio' che invii (qui sotto,
``DefenderCountOnSaveTests``) e su cio' che la panchina produce
(``SubstitutionsKeepTheDefenceTests``) — perche' vietarne uno solo lascia aperta
l'altra strada per lo stesso risultato.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dttz

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from realdata.models import (
    Competition,
    CompetitionSeason,
    Match,
    Player,
    PlayerTeamStint,
    Season,
    Team,
    TeamSeason,
)
from vfoot.models import (
    FantasyLeague,
    FantasyMatchday,
    FantasyRosterSlot,
    FantasyTeam,
    LeagueMembership,
    SavedLineupSnapshot,
)
from vfoot.services.classic_matchday_scoring import lineup_still_owned
from vfoot.services.lineup_substitution import apply_classic_substitutions

SAT = datetime(2026, 2, 7, 14, 0, tzinfo=dttz.utc)    # gioca il "sabato"
MON = datetime(2026, 2, 9, 19, 45, tzinfo=dttz.utc)   # gioca il "lunedi"
SUNDAY = SAT + timedelta(days=1)                      # meta' giornata giocata


# --------------------------------------------------------------------------- #
# R2 — la panchina non sposta il numero di difensori.                          #
# --------------------------------------------------------------------------- #
class SubstitutionsKeepTheDefenceTests(SimpleTestCase):
    """Un 4-4-2: 1 portiere, 4 difensori, 4 centrocampisti, 2 attaccanti."""

    def setUp(self):
        self.starters = list(range(1, 12))
        self.roles = {1: "GK",
                      2: "DEF", 3: "DEF", 4: "DEF", 5: "DEF",
                      6: "MID", 7: "MID", 8: "MID", 9: "MID",
                      10: "ATT", 11: "ATT"}
        # In panchina: un difensore, un centrocampista, un attaccante.
        self.roles.update({20: "DEF", 21: "MID", 22: "ATT"})
        self.bench = [21, 22, 20]

    def _run(self, sv: int, **kw):
        voted = {p for p in self.starters + self.bench if p != sv}
        return apply_classic_substitutions(
            self.starters, self.bench, self.roles, voted, **kw)

    def test_without_the_lock_a_midfielder_covers_a_defender(self):
        """Il comportamento di sempre, che non deve cambiare per chi non ha
        toccato niente a giornata cominciata."""
        res = self._run(5)
        self.assertEqual(res.subs, [(5, 21)])

    def test_a_defender_is_replaced_by_a_defender(self):
        res = self._run(5, def_locked=True)
        self.assertEqual(res.subs, [(5, 20)])
        self.assertEqual(sum(1 for p in res.effective if self.roles[p] == "DEF"), 4)

    def test_a_midfielder_is_not_replaced_by_a_defender(self):
        """IL CRICCHETTO, che e' il verso meno ovvio: un difensore in piu' fra
        quelli con voto fa scegliere i tre migliori su cinque invece che su
        quattro, e i due voti brutti escono dalla media. Azionabile a voti visti,
        e a senso unico — la media puo' solo migliorare."""
        res = self._run(6, def_locked=True)
        self.assertEqual(res.subs, [(6, 21)])
        self.assertEqual(sum(1 for p in res.effective if self.roles[p] == "DEF"), 4)

    def test_midfielder_and_attacker_stay_free_to_swap(self):
        """Il modificatore non li guarda: vietarli sarebbe una regola senza il suo
        motivo."""
        self.bench = [22, 20]          # in panchina solo un attaccante e un difensore
        res = self._run(6, def_locked=True)
        self.assertEqual(res.subs, [(6, 22)])

    def test_a_hole_rather_than_a_defender_out_of_nowhere(self):
        """Il prezzo, e va conosciuto: senza difensori in panchina il buco resta.
        E' cio' che la barra del Salva dice PRIMA, non a punteggi fatti."""
        self.bench = [21, 22]
        res = self._run(5, def_locked=True)
        self.assertEqual(res.subs, [])
        self.assertEqual(res.unresolved, [5])


# --------------------------------------------------------------------------- #
# La formazione ereditata, ripulita.                                           #
# --------------------------------------------------------------------------- #
class InheritedLineupTests(SimpleTestCase):
    class _Snap:
        def __init__(self, gk, xi, bench):
            self.gk_player_id = gk
            self.starter_player_ids = xi
            self.bench_player_ids = bench

    def test_who_was_sold_leaves_a_hole_instead_of_a_substitute(self):
        snap = self._Snap("1", [2, 3, 4], [5, 6])
        gk, xi, bench, gone = lineup_still_owned(snap, {1, 2, 4, 5})
        self.assertEqual((gk, xi, bench), (1, [2, 4], [5]))
        self.assertEqual(sorted(gone), [3, 6])

    def test_even_the_keeper_can_be_gone(self):
        snap = self._Snap("1", [2], [3])
        gk, xi, _, gone = lineup_still_owned(snap, {2, 3})
        self.assertIsNone(gk)
        self.assertEqual(gone, [1])


# --------------------------------------------------------------------------- #
# R1 — l'invio non cambia il numero di difensori.                              #
# --------------------------------------------------------------------------- #
class _ClassicRound(TestCase):
    """Una lega classic col modificatore, due club, e undici piu' panchina.

    Il "sabato" gioca il club A, il "lunedi" il club B: a meta' giornata i
    giocatori di A sono congelati e quelli di B no. E' l'unica situazione in cui
    la falla esiste — se fosse tutto bloccato non ci sarebbe niente da modificare.
    """

    ROLE_SEED = {"GK": "POR", "DEF": "DIF", "MID": "CEN", "ATT": "ATT"}

    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        season = Season.objects.create(code="2025-2026")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=season, name="Serie A 2025-2026")
        self.owner = User.objects.create_user("owner", "o@x.it", "pw")
        self.league = FantasyLeague.objects.create(
            name="Lega", owner=self.owner, mode=FantasyLeague.MODE_CLASSIC,
            reference_season=self.cs, lineup_lock_mode=FantasyLeague.LOCK_PLAYER,
            defense_bonus_enabled=True)
        self.membership = LeagueMembership.objects.create(
            league=self.league, user=self.owner, role=LeagueMembership.ROLE_ADMIN)
        self.team = FantasyTeam.objects.create(
            league=self.league, manager=self.membership, name="Squadra")

        self.ts = {}
        for code in ("sab", "lun"):
            club = Team.objects.create(name=code.title())
            self.ts[code] = TeamSeason.objects.create(competition_season=self.cs, team=club)
        # I due club della rosa NON si incontrano fra loro: se il club del lunedi
        # comparisse anche nella partita del sabato, i suoi giocatori si
        # congelerebbero li' e non resterebbe niente su cui decidere — cioe' il
        # caso che questo file esiste per provare.
        for code in ("terzo", "quarto"):
            club = Team.objects.create(name=code.title())
            self.ts[code] = TeamSeason.objects.create(competition_season=self.cs, team=club)
        Match.objects.create(
            competition_season=self.cs, matchday=22, kickoff=SAT, kickoff_provisional=False,
            home_team=self.ts["sab"], away_team=self.ts["terzo"],
            status=Match.STATUS_SCHEDULED, external_source="sofascore", external_id="sat22")
        Match.objects.create(
            competition_season=self.cs, matchday=22, kickoff=MON, kickoff_provisional=False,
            home_team=self.ts["lun"], away_team=self.ts["quarto"],
            status=Match.STATUS_SCHEDULED, external_source="sofascore", external_id="mon22")
        FantasyMatchday.objects.create(
            league=self.league, real_competition_season=self.cs, real_matchday=22)

        # La rosa: chi gioca il lunedi e' quello su cui si puo' ancora decidere.
        self.pid: dict[str, int] = {}
        def add(key, role, when):
            p = Player.objects.create(
                full_name=key, short_name=key,
                classic_role_seed=self.ROLE_SEED[role])
            PlayerTeamStint.objects.create(player=p, team_season=self.ts[when])
            FantasyRosterSlot.objects.create(team=self.team, player=p, purchase_price=10)
            self.pid[key] = p.id

        add("gk", "GK", "sab")
        for i in range(1, 5):                       # 4 difensori: 3 sabato, 1 lunedi
            add(f"d{i}", "DEF", "sab" if i < 4 else "lun")
        for i in range(1, 5):                       # 4 centrocampisti
            add(f"m{i}", "MID", "sab" if i < 4 else "lun")
        for i in range(1, 3):                       # 2 attaccanti
            add(f"a{i}", "ATT", "sab")
        # Panchina: un difensore e un attaccante, tutti e due del lunedi.
        add("dbench", "DEF", "lun")
        add("abench", "ATT", "lun")

    def _client(self):
        token, _ = Token.objects.get_or_create(user=self.owner)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return c

    def _xi(self, *names):
        return [self.pid[n] for n in names]

    OUTFIELD = ("d1", "d2", "d3", "d4", "m1", "m2", "m3", "m4", "a1", "a2")

    def _save_snapshot(self, outfield=None, bench=None):
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{self.team.id}",
            gk_player_id=str(self.pid["gk"]),
            starter_player_ids=self._xi(*(outfield or self.OUTFIELD)),
            bench_player_ids=self._xi(*(bench or ("dbench", "abench"))),
        )

    def _post(self, outfield, bench=("dbench", "abench")):
        return self._client().post(
            f"/api/v1/leagues/{self.league.id}/lineup/save",
            {"matchday": 22, "gk_player_id": self.pid["gk"],
             "starter_player_ids": self._xi(*outfield),
             "bench_player_ids": self._xi(*bench)},
            format="json")

    def _play_the_saturday(self):
        """Il sabato e' passato, il lunedi no.

        Le date del fixture (una giornata di febbraio) non si possono usare come
        stanno: l'endpoint legge l'orologio vero, e a stagione conclusa ogni caso
        collasserebbe in «la giornata e' finita». Si sposta il calendario attorno
        all'adesso, non l'adesso attorno al calendario."""
        from django.utils import timezone

        now = timezone.now()
        Match.objects.filter(external_id="sat22").update(
            kickoff=now - timedelta(hours=2), status=Match.STATUS_FINISHED)
        Match.objects.filter(external_id="mon22").update(kickoff=now + timedelta(days=1))

    def _before_any_kickoff(self):
        from django.utils import timezone

        now = timezone.now()
        Match.objects.filter(external_id="sat22").update(kickoff=now + timedelta(hours=2))
        Match.objects.filter(external_id="mon22").update(kickoff=now + timedelta(days=1))

    def _snap(self):
        return SavedLineupSnapshot.objects.get(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{self.team.id}")


class DefenderCountOnSaveTests(_ClassicRound):
    def test_before_the_first_kickoff_the_count_is_free(self):
        """Prima non c'e' nessuna informazione da sfruttare: si sceglie."""
        self._before_any_kickoff()
        self._save_snapshot()
        r = self._post(("d1", "d2", "d3", "m1", "m2", "m3", "m4", "abench", "a1", "a2"))
        self.assertEqual(r.status_code, 200, r.data)

    def test_after_the_first_kickoff_the_count_cannot_change(self):
        self._save_snapshot()
        self._play_the_saturday()
        # Fuori il difensore del lunedi, dentro un attaccante: 4 difensori -> 3.
        r = self._post(("d1", "d2", "d3", "m1", "m2", "m3", "m4", "abench", "a1", "a2"))
        self.assertEqual(r.status_code, 409, r.data)
        self.assertIn("difensori", " ".join(r.data["errors"]).lower())

    def test_it_bites_in_the_other_direction_too(self):
        """Aggiungere il quarto difensore dopo aver visto due bei voti e' la
        stessa mossa letta al contrario."""
        self._save_snapshot(outfield=("d1", "d2", "d3", "m1", "m2", "m3", "m4",
                                      "a1", "a2", "abench"))
        self._play_the_saturday()
        r = self._post(("d1", "d2", "d3", "dbench", "m1", "m2", "m3", "m4", "a1", "a2"))
        self.assertEqual(r.status_code, 409, r.data)

    def test_a_defender_for_another_defender_is_still_allowed(self):
        """Il vincolo e' sul NUMERO, non sulle persone: cambiare idea su chi
        schierare in difesa resta una scelta legittima."""
        self._save_snapshot()
        self._play_the_saturday()
        r = self._post(("d1", "d2", "d3", "dbench", "m1", "m2", "m3", "m4", "a1", "a2"),
                       bench=("d4", "abench"))
        self.assertEqual(r.status_code, 200, r.data)

    def test_without_the_modifier_the_rule_does_not_exist(self):
        """Una regola senza il suo motivo e' peggio di una che varia."""
        self.league.defense_bonus_enabled = False
        self.league.save(update_fields=["defense_bonus_enabled"])
        self._save_snapshot()
        self._play_the_saturday()
        r = self._post(("d1", "d2", "d3", "m1", "m2", "m3", "m4", "abench", "a1", "a2"))
        self.assertEqual(r.status_code, 200, r.data)


class EditedAfterKickoffFlagTests(_ClassicRound):
    def test_saving_before_the_kickoff_does_not_raise_it(self):
        self._before_any_kickoff()
        self._save_snapshot()
        self.assertEqual(self._post(self.OUTFIELD).status_code, 200)
        self.assertFalse(self._snap().edited_after_kickoff)

    def test_saving_without_changing_anything_does_not_raise_it(self):
        """La trappola: chi apre la pagina alle 20:30, non tocca niente e preme
        Salva non deve perdere i cambi di ruolo per nulla."""
        self._save_snapshot()
        self._play_the_saturday()
        self.assertEqual(self._post(self.OUTFIELD).status_code, 200)
        self.assertFalse(self._snap().edited_after_kickoff)

    def test_reordering_the_bench_raises_it(self):
        """Mettere il proprio miglior difensore in cima a voti visti non tocca ne'
        gli undici ne' chi siede in panchina: e' esattamente la leva del secondo
        verso del vincolo, e conta come modifica."""
        self._save_snapshot()
        self._play_the_saturday()
        r = self._post(self.OUTFIELD, bench=("abench", "dbench"))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(self._snap().edited_after_kickoff)

    def test_swapping_a_defender_raises_it(self):
        self._save_snapshot()
        self._play_the_saturday()
        r = self._post(("d1", "d2", "d3", "dbench", "m1", "m2", "m3", "m4", "a1", "a2"),
                       bench=("d4", "abench"))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(self._snap().edited_after_kickoff)


class ConclusionInheritsInsteadOfAskingTests(_ClassicRound):
    """Chi non schiera non blocca piu' la conclusione della giornata.

    Prima ``team_lines_for_conclusion`` tornava «missing» e il punteggio si
    fermava finche' l'admin non sceglieva a mano, squadra per squadra, fra forfait
    e formazione precedente: una decisione presa a voti gia' noti. Ora la regola e'
    annunciata prima — vale l'ultima — e il forfait resta come scavalco esplicito.
    """

    def _lines(self, resolution=None):
        from vfoot.services.classic_matchday_scoring import team_lines_for_conclusion

        return team_lines_for_conclusion(
            self.league, self.team, None, 22, {}, resolution)

    def _previous_round_lineup(self):
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="21",
            lineup_id=f"team{self.team.id}",
            gk_player_id=str(self.pid["gk"]),
            starter_player_ids=self._xi(*self.OUTFIELD),
            bench_player_ids=self._xi("dbench", "abench"))

    def test_no_lineup_but_a_previous_one_needs_no_admin(self):
        self._previous_round_lineup()
        starters, _, meta = self._lines()
        self.assertEqual(meta["source"], "previous")
        self.assertEqual(len(starters), 11)

    def test_forfait_stays_available_as_an_explicit_override(self):
        self._previous_round_lineup()
        starters, _, meta = self._lines(resolution="forfait")
        self.assertEqual(meta["source"], "forfait")
        self.assertEqual(starters, [])

    def test_with_nothing_to_inherit_the_admin_is_still_asked(self):
        """La prima giornata di chi non ha mai schierato: non c'e' nessuna
        formazione precedente, e allora la domanda e' legittima."""
        _, _, meta = self._lines()
        self.assertEqual(meta["source"], "missing")
        self.assertFalse(meta["has_previous_lineup"])

    def test_the_inherited_lineup_does_not_lock_the_defence(self):
        """Il flag riguarda la giornata da cui la formazione viene: per QUESTA il
        suo allenatore non ha mosso niente, quindi non ha usato informazioni."""
        self._previous_round_lineup()
        SavedLineupSnapshot.objects.filter(matchday_id="21").update(edited_after_kickoff=True)
        _, _, meta = self._lines()
        self.assertFalse(meta["def_locked"])
