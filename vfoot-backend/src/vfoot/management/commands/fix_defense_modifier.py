"""Riscrive il MODIFICATORE DIFESA nei tabellini gia' congelati, e nient'altro.

    python manage.py fix_defense_modifier                 # prova, non scrive
    python manage.py fix_defense_modifier --apply         # scrive
    python manage.py fix_defense_modifier --league 3 --apply

PERCHE' UN COMANDO DEDICATO E NON IL RICALCOLO NORMALE. Il ricalcolo di una
giornata (``score_and_persist_matchday``, il pulsante «ricalcola») rifa' il
tabellino da capo: rilegge i voti puri di OGGI e li riscrive dentro il referto.
Ma i voti si muovono anche a codice fermo, perche' si muovono i dati sotto —
misurato sulle 10 partite concluse in produzione il 01/09/2026: **60 righe su 460
avevano gia' un voto diverso da quello congelato** (Ndicka 6.5 -> 6.0, Dodo' 5.5
-> 5.0, Bonny 6.5 -> 6.0), e altre 40 non erano piu' nemmeno nell'indice. Un
ricalcolo avrebbe cambiato i risultati di lega per ragioni che con la correzione
del regolamento non c'entrano niente — ed e' esattamente cio' che il congelamento
al Concludi esiste per impedire.

Questo comando invece tocca UNA cosa: la banda del modificatore, ricalcolata dalla
media GIA' CONGELATA nel referto (``defense.avg``). Nessuna riga di giocatore
viene riletta, nessun voto cambia. I totali e i gol si ricompongono con
``resolve_fixture``, cioe' con l'aritmetica del motore e non con una sua copia
riscritta qui.

Il vantaggio in casa e' gia' dentro la lista dei modificatori congelata, quindi
si richiama ``resolve_fixture`` con ``home_advantage=False``: aggiungerlo di nuovo
lo conterebbe due volte.
"""
from __future__ import annotations

import copy

from django.core.management.base import BaseCommand
from django.db import transaction

from vfoot.models import FantasyFixture, FantasyFixtureDetail
from vfoot.services.classic_scoring import ModifierResult, Ruleset, resolve_fixture
from vfoot.services.classic_matchday_scoring import _serialize_team
from vfoot.services.defense_bonus import defense_bonus_value


class Command(BaseCommand):
    help = "Ricalcola SOLO la banda del modificatore difesa nei referti congelati."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="scrive davvero (senza, e' una prova)")
        parser.add_argument("--league", type=int, default=None)

    def handle(self, *args, **o):
        qs = (FantasyFixtureDetail.objects
              .select_related("fixture", "fixture__fantasy_matchday")
              .order_by("fixture_id"))
        if o["league"]:
            qs = qs.filter(fixture__fantasy_matchday__league_id=o["league"])

        w = self.stdout.write
        cambiati, ribaltati, tocca_voti = 0, 0, 0
        rows = []
        for d in qs:
            p = copy.deepcopy(d.payload or {})
            if not p or p.get("mode") != "classic":
                continue
            sides = {}
            delta = {}
            for s in ("home", "away"):
                team = dict(p.get(s) or {})
                mods = []
                delta[s] = 0.0
                for m in team.get("modifiers", []):
                    if m.get("key") == "defense" and m.get("eligible"):
                        det = dict(m.get("detail") or {})
                        nuovo = defense_bonus_value(det.get("avg"))
                        delta[s] = nuovo - float(m.get("value") or 0.0)
                        det["bonus"] = nuovo
                        m = {**m, "value": nuovo, "detail": det}
                        team["defense"] = det
                    mods.append(m)
                team["modifiers"] = [ModifierResult(key=m["key"], eligible=m["eligible"],
                                                    value=m["value"], scope=m["scope"],
                                                    detail=dict(m.get("detail") or {}))
                                     for m in mods]
                sides[s] = team
            if not any(delta.values()):
                continue

            rs = Ruleset(defense_mode=p.get("defense_bonus_mode") or "add_own")
            res = resolve_fixture(sides["home"], sides["away"], rs, home_advantage=False)
            nuovo_p = dict(p)
            nuovo_p["home"] = _serialize_team(sides["home"])
            nuovo_p["away"] = _serialize_team(sides["away"])
            for k in ("home_goals", "away_goals", "home_total", "away_total", "result"):
                nuovo_p[k] = res[k]

            vecchi = (p.get("home_goals"), p.get("away_goals"))
            nuovi = (res["home_goals"], res["away_goals"])
            flip = p.get("result") != res["result"]
            cambiati += 1
            ribaltati += int(flip)
            rows.append((d.fixture_id, p.get("home_team"), p.get("away_team"),
                         delta["home"], delta["away"], vecchi, nuovi, flip))

            if o["apply"]:
                with transaction.atomic():
                    d.payload = nuovo_p
                    d.vfoot_home = res["home_total"]
                    d.vfoot_away = res["away_total"]
                    d.save(update_fields=["payload", "vfoot_home", "vfoot_away"])
                    fx = d.fixture
                    fx.home_total = float(res["home_goals"])
                    fx.away_total = float(res["away_goals"])
                    fx.save(update_fields=["home_total", "away_total"])

        w(f"{'fx':>5}  {'casa':<24} {'trasferta':<24} {'delta':>9}  risultato")
        for fid, h, a, dh, da, vec, nuo, flip in rows:
            w(f"{fid:>5}  {str(h)[:23]:<24} {str(a)[:23]:<24} "
              f"{dh:+.0f}/{da:+.0f}".rjust(9) +
              f"  {vec[0]}-{vec[1]} -> {nuo[0]}-{nuo[1]}" + ("   RIBALTATO" if flip else ""))
        w("")
        w(f"partite col modificatore corretto: {cambiati}")
        w(f"risultati che cambiano: {ribaltati}")
        w("SCRITTO." if o["apply"] else "PROVA: niente e' stato scritto (usa --apply).")
