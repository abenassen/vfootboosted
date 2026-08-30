"""L'impronta dei voti di una stagione, per confrontare due installazioni.

Serve a rispondere a una domanda che nessun altro strumento risponde: **la
produzione calcola gli stessi voti del portatile?** Non è una domanda oziosa —
l'11/08/2026 la risposta era no, per 350 presenze con un ruolo diverso e 218 con un
voto diverso, e nessuna delle cause era nel modello: mancavano le rose Transfermarkt
della stagione misurata (quindi sette portieri non erano marcati come tali),
l'ordine delle righe del clustering dipendeva dal motore del database, la somma in
virgola mobile di PostgreSQL non è quella di SQLite, e in produzione non erano stati
importati gli intervalli di presenza in campo.

    python manage.py vote_fingerprint --season-name "Serie A 2025-2026"
    python manage.py vote_fingerprint --season-name "Serie A 2025-2026" --out /tmp/voti.txt

La stagione si risolve per NOME e non per id: gli id sono autoincrementali, quindi
la stessa stagione ha id diversi su installazioni diverse (in produzione la 2025-26
è la 1, in locale la 2) — ed è esattamente il tipo di dettaglio che fa sbagliare il
confronto proprio quando serve.

Stampa l'impronta delle costanti del modello, quella dei voti, e su richiesta
scrive una riga per presenza. Se le impronte del modello coincidono e quella dei
voti no, la differenza è nei DATI: si diffano i due file e si guarda chi cambia.
"""
from __future__ import annotations

import hashlib

from django.core.management.base import BaseCommand, CommandError

from realdata.models import CompetitionSeason, Match
from vfoot.services import classic_rating as cr
from vfoot.services.classic_pagella import get_reference
from vfoot.services.vote_reference import (
    SCORING_CODE_VERSION, clear_cache, scoring_fingerprint, weights_fingerprint,
)


class Command(BaseCommand):
    help = "Impronta dei voti di una stagione, per confrontare due installazioni."

    def add_arguments(self, parser):
        parser.add_argument("--season-name", required=True,
                            help='Nome della CompetitionSeason, es. "Serie A 2025-2026".')
        parser.add_argument("--out", default=None,
                            help="File dove scrivere una riga per presenza.")

    def handle(self, *args, **o):
        cs = CompetitionSeason.objects.filter(name=o["season_name"]).first()
        if cs is None:
            disponibili = ", ".join(CompetitionSeason.objects.values_list("name", flat=True))
            raise CommandError(f"Nessuna stagione '{o['season_name']}'. Ci sono: {disponibili}")
        # I voti si mettono in cache sotto l'impronta del modello: se qualcuno ha
        # ricalibrato o toccato una costante nello stesso processo, la cache in
        # memoria e' vecchia e l'impronta uscirebbe di una versione che non e' questa.
        clear_cache()
        cr.clear_scales_cache()

        self.stdout.write(f"stagione   : {cs.name} (id locale {cs.id})")
        self.stdout.write(f"codice     : SCORING_CODE_VERSION {SCORING_CODE_VERSION}")
        self.stdout.write(f"pesi       : {weights_fingerprint()}")
        self.stdout.write(f"modello    : {scoring_fingerprint()}")
        self.stdout.write(f"costanti   : mitigazione vittoria max {cr.RESULT_MITIGATION_MAX_SHARE}, "
                          f"sconfitta ancora {cr.RESULT_MITIGATION_LOSS_ANCHOR} "
                          f"max {cr.RESULT_MITIGATION_LOSS_MAX_SHARE}, "
                          f"autogol-portiere {cr.OWN_GOAL_KEEPER_XGOT_DEFAULT}, "
                          f"decimali {cr.PROVIDER_SUM_DECIMALS}")

        ref = get_reference(cs.id)
        matches = (Match.objects.filter(competition_season=cs, status=Match.STATUS_FINISHED)
                   .select_related("home_team__team", "away_team__team")
                   .order_by("matchday", "id"))
        # Il NOME COMPLETO come chiave, non quello breve: in Serie A 2025-26 giocano
        # sia Lorenzo sia Luca Pellegrini, e per entrambi il nome breve e'
        # "L. Pellegrini". Con quello il diff fra due installazioni confrontava due
        # persone diverse e produceva una differenza che non esiste — o, peggio,
        # nascondeva una che esiste.
        from realdata.models import Player
        interi = dict(Player.objects.values_list("id", "full_name"))
        righe = []
        for m in matches:
            # chiave portabile: giornata + nomi delle squadre, non gli id
            etichetta = f"{m.matchday}|{m.home_team.team.name}-{m.away_team.team.name}"
            for r in cr.voto_puro_for_match(m, ref):
                voto = ("sv" if r["voto_puro"] is None
                        else format(r["voto_puro"], ".1f"))
                chi = interi.get(r["player_id"]) or r["name"]
                righe.append(f"{etichetta}|{chi}|{r['role']}|{voto}")
        righe.sort()
        impronta = hashlib.sha256("\n".join(righe).encode()).hexdigest()[:24]
        self.stdout.write(f"\npartite    : {len(matches)}")
        self.stdout.write(f"presenze   : {len(righe)}")
        self.stdout.write(self.style.SUCCESS(f"IMPRONTA VOTI: {impronta}"))
        if o["out"]:
            with open(o["out"], "w", encoding="utf-8") as fh:
                fh.write("\n".join(righe))
            self.stdout.write(f"scritto {o['out']} — confrontalo con `diff` "
                              f"contro l'altra installazione")
