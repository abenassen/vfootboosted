"""Il numero di difensori, e chi entra al posto di un difensore.

Due regole, tutte e due il prezzo della sola modalita' «sempre aperta»
(``player``) e solo dove il modificatore difesa e' acceso:

* **il numero** (R1, sul salvataggio): dal primo calcio d'inizio di un proprio
  giocatore, i difensori negli undici restano quanti erano;
* **le due passate** (sulle sostituzioni): al posto di un difensore senza voto ci
  prova prima un difensore, nel proprio ordine di panchina; se nessuno ha voto,
  si rilegge la lista daccapo con chiunque. E viceversa per gli altri ruoli.

La seconda era nata come un lucchetto che si accendeva quando l'allenatore
MODIFICAVA la formazione a giornata cominciata: un interruttore, azionato a voti
visti. Ora e' una regola di lega nel ``Ruleset`` e non ha interruttore.

In fondo il collaudo che vale per tutte e due: preso uno scenario, il
modificatore e' identico in ogni ramo che le regole ammettono, con il gate su
``starters`` e su ``effective``.
"""
from __future__ import annotations

from datetime import timedelta
from itertools import permutations

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
from vfoot.services import lineup_deadline
from vfoot.services.classic_matchday_scoring import lineup_still_owned
from vfoot.services.classic_scoring import Ruleset, defence_first_for, score_team
from vfoot.services.defense_bonus import GATE_EFFECTIVE, GATE_STARTERS
from vfoot.services.formation_rules import is_legal_classic
from vfoot.services.lineup_substitution import apply_classic_substitutions
from vfoot.tests_classic_scoring import line


# --------------------------------------------------------------------------- #
# Le due passate.                                                              #
# --------------------------------------------------------------------------- #
class TheBenchIsReadTwiceTests(SimpleTestCase):
    """Un 4-4-2: 1 portiere, 4 difensori, 4 centrocampisti, 2 attaccanti."""

    def setUp(self):
        self.starters = list(range(1, 12))
        self.roles = {1: "GK",
                      2: "DEF", 3: "DEF", 4: "DEF", 5: "DEF",
                      6: "MID", 7: "MID", 8: "MID", 9: "MID",
                      10: "ATT", 11: "ATT"}
        # In panchina: un centrocampista, un attaccante, un difensore — in
        # quest'ordine, col difensore per ultimo.
        self.roles.update({20: "DEF", 21: "MID", 22: "ATT"})
        self.bench = [21, 22, 20]

    def _run(self, sv, **kw):
        sv = {sv} if isinstance(sv, int) else set(sv)
        voted = {p for p in self.starters + self.bench if p not in sv}
        return apply_classic_substitutions(
            self.starters, self.bench, self.roles, voted, **kw)

    def test_without_the_rule_the_bench_is_one_queue(self):
        """Le modalita' 1 e 2: quando l'ultimo salva nessun voto esiste, e la
        panchina e' la fila di sempre — il primo con voto che tiene il modulo."""
        res = self._run(5)
        self.assertEqual(res.subs, [(5, 21)])

    def test_a_defender_is_covered_by_a_defender_first(self):
        res = self._run(5, defence_first=True)
        self.assertEqual(res.subs, [(5, 20)])
        self.assertEqual(sum(1 for p in res.effective if self.roles[p] == "DEF"), 4)

    def test_a_midfielder_is_not_covered_by_a_defender_while_others_have_a_vote(self):
        """IL CRICCHETTO: un difensore in piu' fra quelli con voto fa scegliere i
        tre migliori su cinque invece che su quattro."""
        self.bench = [20, 21, 22]          # il difensore e' PRIMO in panchina
        res = self._run(6, defence_first=True)
        self.assertEqual(res.subs, [(6, 21)])
        self.assertEqual(sum(1 for p in res.effective if self.roles[p] == "DEF"), 4)

    def test_midfielder_and_attacker_stay_on_the_same_side(self):
        """Il modificatore non li guarda: fra loro vale l'ordine puro."""
        self.bench = [22, 21, 20]
        res = self._run(6, defence_first=True)
        self.assertEqual(res.subs, [(6, 22)])

    def test_the_second_pass_fills_the_defence_with_anybody_rather_than_a_hole(self):
        """Il divieto secco lasciava il buco; le due passate no. Entra il primo
        degli altri, e i difensori con voto restano TRE come col buco: il
        ripiego non tocca niente di cio' che il modificatore guarda."""
        self.bench = [21, 22]
        res = self._run(5, defence_first=True)
        self.assertEqual(res.subs, [(5, 21)])
        self.assertEqual(res.unresolved, [])
        self.assertEqual(sum(1 for p in res.effective if self.roles[p] == "DEF"), 3)

    def test_the_second_pass_brings_a_defender_onto_another_slot_only_as_last_resort(self):
        """Tutti i non difensori in panchina senza voto: allora il difensore copre
        il centrocampista. Non e' fabbricabile — i panchinari gia' a voto non si
        spostano — e quando capita completa la difesa, che e' cio' che il gate
        «formazione acquisita» promette."""
        res = self._run([6, 21, 22], defence_first=True)
        self.assertEqual(res.subs, [(6, 20)])

    def test_the_two_passes_respect_the_substitution_budget(self):
        res = self._run([5, 6], defence_first=True, max_subs=1)
        self.assertEqual(res.subs, [(5, 20)])
        self.assertEqual(res.unresolved, [6])


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
# La regola e' della lega: nel Ruleset, non in un bit per squadra.             #
# --------------------------------------------------------------------------- #
class TheRuleBelongsToTheLeagueTests(SimpleTestCase):
    class _League:
        def __init__(self, **kw):
            self.mode = "classic"
            self.defense_bonus_enabled = True
            self.enforce_lineup_deadline = True
            self.lineup_lock_mode = "player"
            self.__dict__.update(kw)

    def test_player_mode_with_the_modifier_reads_the_bench_twice(self):
        self.assertTrue(defence_first_for(self._League()))

    def test_the_other_two_modes_do_not(self):
        """Quando salvi nessun tuo voto esiste: la regola non ha il suo motivo."""
        self.assertFalse(defence_first_for(self._League(lineup_lock_mode="own")))
        self.assertFalse(defence_first_for(self._League(lineup_lock_mode="matchday")))

    def test_without_the_modifier_or_the_deadline_it_does_not_exist(self):
        self.assertFalse(defence_first_for(self._League(defense_bonus_enabled=False)))
        self.assertFalse(defence_first_for(self._League(enforce_lineup_deadline=False)))
        self.assertFalse(defence_first_for(self._League(mode="aura")))

    def test_it_travels_in_the_snapshot(self):
        """Una giornata conclusa ricorda la regola con cui e' stata calcolata: il
        ricalcolo di una vecchia giornata non cambia semantica sotto i piedi."""
        rs = Ruleset(defence_first=True)
        self.assertTrue(Ruleset.from_snapshot(rs.to_snapshot()).defence_first)
        self.assertFalse(Ruleset.from_snapshot({"defense_gate": "starters"}).defence_first)


class TheRuleReachesTheScoreTests(SimpleTestCase):
    """Provata sul PUNTEGGIO, non solo sulla funzione isolata: quattro difensori
    per il modificatore, due hanno preso 5, e un centrocampista e' senza voto."""

    def _lines(self):
        starters = [
            line(1, "GK", 6.0),
            line(2, "DEF", 5.0), line(3, "DEF", 5.0), line(4, "DEF", 6.0), line(5, "DEF", 6.0),
            line(6, "MID", 6.0, sv=True),   # il buco da coprire
            line(7, "MID", 6.0), line(8, "MID", 6.0), line(9, "MID", 6.0),
            line(10, "ATT", 6.0), line(11, "ATT", 6.0),
        ]
        bench = [line(20, "DEF", 7.5), line(21, "MID", 6.0)]
        return starters, bench

    def test_in_one_queue_the_ratchet_works(self):
        """Le modalita' 1 e 2: entra il difensore, ed e' giusto cosi' — nessuno
        ha potuto mettercelo a voti visti."""
        starters, bench = self._lines()
        r = score_team(starters, bench, Ruleset(defence_first=False))
        self.assertEqual(r["substitutions"][0]["in"]["player_id"], 20)
        self.assertEqual(r["defense"]["avg"], 6.375)
        self.assertEqual(r["defense"]["bonus"], 2.0)

    def test_read_twice_the_defence_keeps_its_number(self):
        starters, bench = self._lines()
        r = score_team(starters, bench, Ruleset(defence_first=True))
        self.assertEqual(r["substitutions"][0]["in"]["player_id"], 21)
        self.assertEqual(r["defense"]["avg"], 5.75)
        self.assertEqual(r["defense"]["bonus"], 0.0)


# --------------------------------------------------------------------------- #
# Il collaudo: ogni ramo ammesso da' lo stesso modificatore.                   #
# --------------------------------------------------------------------------- #
class EveryAdmittedBranchGivesTheSameModifierTests(SimpleTestCase):
    """Le porte dell'analisi del 21 agosto, rigiocate.

    Per ogni scenario si enumerano le mosse che un allenatore potrebbe fare a
    voti visti — ogni ordine di panchina, ogni scambio titolare/panchinaro — si
    tengono solo quelle che le regole ammettono (undici legale, numero di
    difensori invariato, nessuno scavalca un congelato), si calcola il punteggio
    di ciascuna e si pretende che il modificatore sia lo stesso in tutte. Sotto
    tutti e due i gate. Se esiste un ramo ammesso con un modificatore diverso,
    esiste una scelta fatta sapendo.
    """

    def _branches(self, base, roles, locked, overtaking_rule=True):
        """Ogni (undici, panchina) raggiungibile con uno scambio e un riordino,
        filtrato dalle regole del salvataggio. ``overtaking_rule=False`` toglie
        il solo controllo dei congelati: serve a mostrare che la porta c'era."""
        gk, xi, bench = base
        starts = [(xi, bench)]
        for i, s in enumerate(xi):
            for j, b in enumerate(bench):
                nxi, nb = list(xi), list(bench)
                nxi[i], nb[j] = b, s
                starts.append((nxi, nb))
        before = sum(1 for p in xi if roles[p] == "DEF")
        out = []
        for nxi, nb in starts:
            if not is_legal_classic([roles[gk]] + [roles[p] for p in nxi]):
                continue
            if sum(1 for p in nxi if roles[p] == "DEF") != before:
                continue                                    # R1
            for order in permutations(nb):
                new = {"gk_player_id": gk, "starter_player_ids": nxi,
                       "bench_player_ids": list(order)}
                old = {"gk_player_id": gk, "starter_player_ids": xi, "bench_player_ids": bench}
                if overtaking_rule and lineup_deadline.violations(old, new, locked):
                    continue                                # congelati e scavalco
                out.append((nxi, list(order)))
        return out

    def _score(self, gk, xi, bench, roles, votes, gate, defence_first):
        def L(p):
            v = votes.get(p)
            return line(p, roles[p], v if v is not None else 0.0, sv=v is None)
        rs = Ruleset(defense_gate=gate, defence_first=defence_first)
        r = score_team([L(gk)] + [L(p) for p in xi], [L(p) for p in bench], rs)
        return (r["defense"]["eligible"], r["defense"]["bonus"])

    def _modifiers(self, base, roles, votes, locked, defence_first):
        out = {}
        for gate in (GATE_STARTERS, GATE_EFFECTIVE):
            seen = set()
            for xi, bench in self._branches(base, roles, locked):
                seen.add(self._score(base[0], xi, bench, roles, votes, gate, defence_first))
            out[gate] = seen
        return out

    def test_door_one_the_phantom_defender(self):
        """Difesa a quattro col quarto che non giochera'. In panchina un
        attaccante a voto e un difensore che gioca dopo."""
        roles = {1: "GK", 2: "DEF", 3: "DEF", 4: "DEF", 5: "DEF",
                 6: "MID", 7: "MID", 8: "MID", 9: "MID", 10: "ATT", 11: "ATT",
                 20: "ATT", 21: "DEF"}
        votes = {1: 7.0, 2: 7.0, 3: 6.8, 4: 6.6, 5: None, 6: 6.0, 7: 6.0, 8: 6.0, 9: 6.0,
                 10: 6.0, 11: 6.0, 20: 6.5, 21: 6.0}
        base = (1, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11], [20, 21])
        locked = {1, 2, 3, 4, 20}
        for gate, seen in self._modifiers(base, roles, votes, locked, True).items():
            self.assertEqual(len(seen), 1, (gate, seen))

    def test_door_three_the_phantom_midfielder(self):
        """3-4-3, il fittizio e' un centrocampista; primo panchinaro un
        difensore, secondo un centrocampista. Senza la regola il riordino
        decide se i difensori a voto sono tre o quattro."""
        roles = {1: "GK", 2: "DEF", 3: "DEF", 4: "DEF",
                 5: "MID", 6: "MID", 7: "MID", 8: "MID", 9: "ATT", 10: "ATT", 11: "ATT",
                 20: "DEF", 21: "MID"}
        votes = {1: 7.0, 2: 7.0, 3: 6.8, 4: 6.6, 5: None, 6: 6.0, 7: 6.0, 8: 6.0,
                 9: 6.0, 10: 6.0, 11: 6.0, 20: 7.0, 21: 6.0}
        base = (1, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11], [20, 21])
        locked = {1, 2, 3, 4}
        with_rule = self._modifiers(base, roles, votes, locked, True)
        without = self._modifiers(base, roles, votes, locked, False)
        for gate in (GATE_STARTERS, GATE_EFFECTIVE):
            self.assertEqual(len(with_rule[gate]), 1, (gate, with_rule[gate]))
        # ...e la porta esisteva davvero: senza la regola ci sono due esiti.
        self.assertGreater(len(without[GATE_EFFECTIVE]), 1)

    def test_door_four_the_overtaking(self):
        """4-4-2 con un centrocampista senza voto. In panchina: un centrocampista
        che non prendera' voto, un attaccante gia' a 9.0, un centrocampista che
        giochera'. Scambiare primo e terzo sceglieva se prendere il 9.0. Non
        c'entra il modificatore: la cosa che deve restare uguale in ogni ramo
        ammesso e' se il 9.0 entra."""
        roles = {1: "GK", 2: "DEF", 3: "DEF", 4: "DEF", 5: "DEF",
                 6: "MID", 7: "MID", 8: "MID", 9: "MID", 10: "ATT", 11: "ATT",
                 20: "MID", 21: "ATT", 22: "MID"}
        votes = {1: 6.0, 2: 6.0, 3: 6.0, 4: 6.0, 5: 6.0, 6: None, 7: 6.0, 8: 6.0, 9: 6.0,
                 10: 6.0, 11: 6.0, 20: None, 21: 9.0, 22: 6.0}
        base = (1, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11], [20, 21, 22])
        locked = {1, 2, 3, 4, 5, 6, 21}          # i liberi: 7-11 e i due centrocampisti

        def nine_enters(xi, bench):
            def L(p):
                v = votes.get(p)
                return line(p, roles[p], v if v is not None else 0.0, sv=v is None)
            r = score_team([L(1)] + [L(p) for p in xi], [L(p) for p in bench],
                           Ruleset(defence_first=True))
            return any(sub["in"]["player_id"] == 21 for sub in r["substitutions"])

        admitted = self._branches(base, roles, locked)
        self.assertGreater(len(admitted), 1, "ci devono essere rami fra cui scegliere")
        self.assertEqual({nine_enters(xi, b) for xi, b in admitted}, {True})
        # ...e senza la regola dello scavalco si poteva scegliere.
        free_for_all = self._branches(base, roles, locked, overtaking_rule=False)
        self.assertEqual({nine_enters(xi, b) for xi, b in free_for_all}, {True, False})


    def test_door_five_the_phantom_inserted_late(self):
        """Il «grimaldello»: a giornata cominciata inserisco negli undici uno che
        sicuramente non giochera', per far scattare la sostituzione e far
        entrare l'8.0 che sta in panchina. Era dato per aperto, ma lo scavalco
        lo chiude: il titolare che esce deve restare DAVANTI all'8.0, quindi e'
        lui il primo della fila con voto — se gioca rientra lui, se non gioca
        l'8.0 entrava comunque. In ogni ramo ammesso, chi entra e' lo stesso,
        sia che il titolare poi giochi sia che no; con o senza le due passate.
        """
        roles = {1: "GK", 2: "DEF", 3: "DEF", 4: "DEF", 5: "DEF",
                 6: "MID", 7: "MID", 8: "MID", 9: "MID", 10: "ATT", 11: "ATT",
                 20: "ATT", 21: "ATT", 22: "MID", 23: "DEF"}
        # 20 = il fittizio (non giochera'); 21 = l'8.0 gia' a voto, congelato;
        # 22, 23 = panchinari dietro il muro. 9 e 11 = titolari liberi.
        base = (1, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11], [20, 21, 22, 23])
        locked = {1, 2, 3, 4, 5, 6, 7, 8, 10, 21}

        def who_scores(xi, bench, starters_play, defence_first):
            """L'undici effettivo: chi ha messo un voto nel totale."""
            votes = {p: 6.0 for p in roles}
            votes[20] = None
            votes[21] = 8.0
            if not starters_play:
                votes[9] = votes[11] = None
            def L(p):
                v = votes.get(p)
                return line(p, roles[p], v if v is not None else 0.0, sv=v is None)
            r = score_team([L(1)] + [L(p) for p in xi], [L(p) for p in bench],
                           Ruleset(defence_first=defence_first))
            outs = {sub["out"]["player_id"] for sub in r["substitutions"]}
            ins = {sub["in"]["player_id"] for sub in r["substitutions"]}
            return frozenset(({1} | set(xi)) - outs | ins), r["base_total"]

        admitted = self._branches(base, roles, locked)
        self.assertTrue(any(20 in xi for xi, _ in admitted), "il fittizio si puo' inserire")
        untouched = (base[1], base[2])
        for defence_first in (False, True):
            # Se i titolari giocano, in ogni ramo va a voto ESATTAMENTE l'undici di
            # partenza: il fittizio inserito viene coperto dal titolare che ha fatto
            # uscire, e l'8.0 non entra.
            expected = who_scores(*untouched, True, defence_first)
            self.assertNotIn(21, expected[0])
            for xi, b in admitted:
                self.assertEqual(who_scores(xi, b, True, defence_first), expected,
                                 (defence_first, xi, b))
            # Se non giocano, l'8.0 entra in ogni ramo — come sarebbe entrato senza
            # la mossa. Chi entra DOPO di lui puo' cambiare (22 o 23, dietro il
            # muro): sono due voti ignoti, e sceglierne l'ordine e' schierare.
            for xi, b in admitted:
                self.assertIn(21, who_scores(xi, b, False, defence_first)[0], (defence_first, xi, b))
            # ...e senza lo scavalco la porta c'era: un ramo in cui l'8.0 entra
            # mentre il titolare tolto gioca.
            free_for_all = self._branches(base, roles, locked, overtaking_rule=False)
            self.assertTrue(any(21 in who_scores(xi, b, True, defence_first)[0]
                                for xi, b in free_for_all))


# --------------------------------------------------------------------------- #
# R1 — l'invio non cambia il numero di difensori.                              #
# --------------------------------------------------------------------------- #
class _ClassicRound(TestCase):
    """Una lega classic col modificatore, in modalita' «sempre aperta», due club,
    undici piu' panchina. Il "sabato" gioca il club A, il "lunedi" il club B."""

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
        for code in ("sab", "lun", "terzo", "quarto"):
            club = Team.objects.create(name=code.title())
            self.ts[code] = TeamSeason.objects.create(competition_season=self.cs, team=club)
        from datetime import datetime, timezone as dttz
        SAT = datetime(2026, 2, 7, 14, 0, tzinfo=dttz.utc)
        MON = datetime(2026, 2, 9, 19, 45, tzinfo=dttz.utc)
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

        self.pid: dict[str, int] = {}
        def add(key, role, when):
            p = Player.objects.create(
                full_name=key, short_name=key,
                classic_role_seed=self.ROLE_SEED[role])
            PlayerTeamStint.objects.create(player=p, team_season=self.ts[when])
            FantasyRosterSlot.objects.create(team=self.team, player=p, purchase_price=10)
            self.pid[key] = p.id

        add("gk", "GK", "sab")
        for i in range(1, 5):
            add(f"d{i}", "DEF", "sab" if i < 4 else "lun")
        for i in range(1, 5):
            add(f"m{i}", "MID", "sab" if i < 4 else "lun")
        for i in range(1, 3):
            add(f"a{i}", "ATT", "sab")
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
            bench_player_ids=self._xi(*(bench or ("dbench", "abench"))))

    def _post(self, outfield, bench=("dbench", "abench")):
        return self._client().post(
            f"/api/v1/leagues/{self.league.id}/lineup/save",
            {"matchday": 22, "gk_player_id": self.pid["gk"],
             "starter_player_ids": self._xi(*outfield),
             "bench_player_ids": self._xi(*bench)},
            format="json")

    def _play_the_saturday(self):
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
        self._before_any_kickoff()
        self._save_snapshot()
        r = self._post(("d1", "d2", "d3", "m1", "m2", "m3", "m4", "abench", "a1", "a2"))
        self.assertEqual(r.status_code, 200, r.data)

    def test_after_the_teams_first_kickoff_the_count_cannot_change(self):
        self._save_snapshot()
        self._play_the_saturday()
        r = self._post(("d1", "d2", "d3", "m1", "m2", "m3", "m4", "abench", "a1", "a2"))
        self.assertEqual(r.status_code, 409, r.data)
        self.assertIn("difensori", " ".join(r.data["errors"]).lower())

    def test_it_bites_in_the_other_direction_too(self):
        self._save_snapshot(outfield=("d1", "d2", "d3", "m1", "m2", "m3", "m4",
                                      "a1", "a2", "abench"))
        self._play_the_saturday()
        r = self._post(("d1", "d2", "d3", "dbench", "m1", "m2", "m3", "m4", "a1", "a2"))
        self.assertEqual(r.status_code, 409, r.data)

    def test_a_defender_for_another_defender_is_still_allowed(self):
        self._save_snapshot()
        self._play_the_saturday()
        r = self._post(("d1", "d2", "d3", "dbench", "m1", "m2", "m3", "m4", "a1", "a2"),
                       bench=("d4", "abench"))
        self.assertEqual(r.status_code, 200, r.data)

    def test_the_clock_is_the_teams_first_player_not_the_rounds(self):
        """La giornata e' cominciata, ma nessuno dei MIEI ha giocato: non so
        niente, e il numero resta libero."""
        PlayerTeamStint.objects.filter(team_season=self.ts["sab"]).update(
            team_season=self.ts["lun"])
        self._save_snapshot()
        self._play_the_saturday()
        r = self._post(("d1", "d2", "d3", "m1", "m2", "m3", "m4", "abench", "a1", "a2"))
        self.assertEqual(r.status_code, 200, r.data)

    def test_without_the_modifier_the_rule_does_not_exist(self):
        self.league.defense_bonus_enabled = False
        self.league.save(update_fields=["defense_bonus_enabled"])
        self._save_snapshot()
        self._play_the_saturday()
        r = self._post(("d1", "d2", "d3", "m1", "m2", "m3", "m4", "abench", "a1", "a2"))
        self.assertEqual(r.status_code, 200, r.data)


# --------------------------------------------------------------------------- #
# L'INVARIANTE FRA LE MODALITA': la 3 non e' mai piu' stretta della 2.         #
#                                                                             #
# Le due modalita' guardano lo stesso orologio — il primo calcio d'inizio fra i #
# club dei propri venticinque (``team_first_kickoff``) — e ne fanno due cose    #
# diverse: la `own` CHIUDE tutto, la `player` si limita a fissare il numero dei #
# difensori. Ne segue che ogni invio che la `own` accetterebbe la `player` deve #
# accettarlo: un anticipo in cui non gioca nessuno dei miei non mi dice niente, #
# e quindi non puo' togliermi niente — modulo e numero di difensori compresi.   #
#                                                                             #
# E' l'invariante, non un caso: se un domani l'orologio di R1 diventasse il     #
# primo calcio d'inizio della GIORNATA, la 3 sarebbe piu' severa della 2 senza  #
# nessuna ragione, e questi test lo direbbero.                                 #
# --------------------------------------------------------------------------- #
class ModeThreeIsNeverStricterThanModeTwoTests(_ClassicRound):
    # Tre difensori invece dei quattro di OUTFIELD: l'invio che R1 rifiuta.
    FEWER_DEFENDERS = ("d1", "d2", "d3", "m1", "m2", "m3", "m4", "abench", "a1", "a2")

    def _mine_all_play_on_monday(self):
        """L'anticipo si gioca, ma nessuno dei miei venticinque e' in campo."""
        PlayerTeamStint.objects.filter(team_season=self.ts["sab"]).update(
            team_season=self.ts["lun"])

    def _in_mode(self, mode, outfield):
        """L'invio, in una modalita' o nell'altra, sempre dalla stessa base."""
        SavedLineupSnapshot.objects.filter(league_id=str(self.league.id)).delete()
        self._save_snapshot()
        self.league.lineup_lock_mode = mode
        self.league.save(update_fields=["lineup_lock_mode"])
        return self._post(outfield).status_code

    def _both_modes(self, outfield):
        return (self._in_mode(FantasyLeague.LOCK_OWN, outfield),
                self._in_mode(FantasyLeague.LOCK_PLAYER, outfield))

    def test_an_anticipo_without_my_players_leaves_the_module_free(self):
        """Il caso: si e' giocato venerdi', io gioco lunedi'. In modalita' 2 sono
        aperto, e in modalita' 3 devo esserlo altrettanto."""
        self._mine_all_play_on_monday()
        self._play_the_saturday()
        own, player = self._both_modes(self.FEWER_DEFENDERS)
        self.assertEqual(own, 200)
        self.assertEqual(player, 200)

    def test_before_any_kickoff_both_modes_are_open(self):
        self._before_any_kickoff()
        own, player = self._both_modes(self.FEWER_DEFENDERS)
        self.assertEqual(own, 200)
        self.assertEqual(player, 200)

    def test_where_mode_two_closes_mode_three_may_bite_but_not_before(self):
        """L'invariante su tutti gli istanti che contano: dove la 2 accetta, la 3
        accetta. Dove la 2 chiude, la 3 puo' fare quello che vuole — e infatti
        fissa il numero dei difensori, che e' il suo mestiere."""
        where = dict(PlayerTeamStint.objects.filter(player_id__in=self.pid.values())
                     .values_list("player_id", "team_season_id"))
        for name, arrange in (
            ("prima di tutto", self._before_any_kickoff),
            ("anticipo senza i miei", lambda: (self._mine_all_play_on_monday(),
                                               self._play_the_saturday())),
            ("anticipo con i miei", self._play_the_saturday),
        ):
            with self.subTest(name):
                for pid, ts_id in where.items():   # la rosa com'era, senza rifare il fixture
                    PlayerTeamStint.objects.filter(player_id=pid).update(team_season_id=ts_id)
                arrange()
                own, player = self._both_modes(self.FEWER_DEFENDERS)
                if own == 200:
                    self.assertEqual(player, 200,
                                     f"{name}: la 2 accetta e la 3 no")

    def test_the_page_shows_nothing_frozen_during_a_foreign_anticipo(self):
        """Lo specchio a schermo: la pagina spegne le pastiglie del modulo su
        ``defence_locked`` e i chiodi su ``locked_player_ids``. Se qui e' tutto
        libero, la formazione e' interamente modificabile anche a video."""
        self._mine_all_play_on_monday()
        self._play_the_saturday()
        self._save_snapshot()
        r = self._client().get(f"/api/v1/leagues/{self.league.id}/lineup?matchday=22")
        self.assertEqual(r.status_code, 200)
        lock = r.data["lineup_lock"]
        self.assertFalse(lock["closed"])
        self.assertFalse(lock["defence_locked"])
        self.assertIsNone(lock["defence_count"])
        self.assertEqual(lock["locked_player_ids"], [])

    def test_with_my_own_player_on_the_pitch_the_page_says_so(self):
        """Il contrario, perche' il test sopra non passi anche da rotto: appena
        uno dei miei scende in campo, la pagina fissa il numero."""
        self._play_the_saturday()
        self._save_snapshot()
        r = self._client().get(f"/api/v1/leagues/{self.league.id}/lineup?matchday=22")
        lock = r.data["lineup_lock"]
        self.assertTrue(lock["defence_locked"])
        self.assertEqual(lock["defence_count"], 4)


class ConclusionInheritsInsteadOfAskingTests(_ClassicRound):
    """Chi non schiera non blocca piu' la conclusione della giornata: vale
    l'ultima, e il forfait resta come scavalco esplicito dell'admin."""

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
        """Una rosa incompleta che non ha mai schierato: nessuna baseline e'
        stata scritta, e allora la domanda e' legittima."""
        _, _, meta = self._lines()
        self.assertEqual(meta["source"], "missing")
        self.assertFalse(meta["has_previous_lineup"])
