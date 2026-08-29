"""Scrivere su ogni gol CHI l'ha servito, dagli incidenti gia' scaricati.

``MatchAppearance.assists`` dice quanti assist ha fatto un giocatore, non quali
gol ha servito — e senza quel legame l'assist non si puo' graduare per impatto
come il gol (v. vfoot.services.goal_impact), perche' il ΔxP e' una proprieta'
del gol. Su una partita con piu' gol la deduzione non basta: sulla 25-26 solo il
28,6% degli assist sarebbe ricostruibile senza ambiguita'.

Il fornitore il dato ce l'ha e i file sono gia' sul disco: l'incidente di tipo
``goal`` porta ``assist1``. Nessuno scrape, si legge la cache.

    manage.py backfill_shot_assists
    manage.py backfill_shot_assists --dry-run

APPAIAMENTO PER TEMPO E SQUADRA, non per identita' del marcatore: il gol nella
mappa dei tiri e quello negli incidenti sono due righe di due endpoint diversi, e
l'unica chiave che condividono e' il minuto piu' il lato. Un minuto puo' portare
piu' di un gol solo se due squadre segnano nello stesso minuto (mai visto sulla
25-26), quindi la coppia (minuto, lato) e' univoca in pratica; quando non lo e' la
riga si salta invece di indovinare.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from realdata.models import Match, MatchShot, Player

DEFAULT_CACHE = str(Path(settings.VFOOT_DATA_DIR) / "historical-data" / "serie-a"
                    / "sofascore" / "cache")


class Command(BaseCommand):
    help = "Scrive MatchShot.assist_player dai file incidents gia' in cache."

    def add_arguments(self, parser):
        parser.add_argument("--cache-dir", default=DEFAULT_CACHE)
        parser.add_argument("--competition-season", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        qs = Match.objects.exclude(external_id="")
        if o["competition_season"]:
            qs = qs.filter(competition_season_id=o["competition_season"])
        by_ext = dict(Player.objects.exclude(external_id="")
                      .values_list("external_id", "id"))
        written = no_file = no_assist = unmatched = ambiguous = 0
        for m in qs.iterator():
            path = Path(o["cache_dir"]) / f"api_v1_event_{m.external_id}_incidents.json"
            if not path.exists():
                no_file += 1
                continue
            incidents = json.loads(path.read_text()).get("incidents", [])
            # (minuto, lato) -> id del passatore
            assists = {}
            for inc in incidents:
                if inc.get("incidentType") != "goal":
                    continue
                a = inc.get("assist1") or {}
                pid = by_ext.get(str(a.get("id"))) if a.get("id") else None
                key = (inc.get("time"), "home" if inc.get("isHome") else "away")
                if key in assists:
                    ambiguous += 1
                    assists[key] = None      # due gol stesso minuto e lato: si salta
                else:
                    assists[key] = pid
                if a.get("id") and pid is None:
                    unmatched += 1
            if not assists:
                continue
            for shot in MatchShot.objects.filter(match=m, is_goal=True):
                pid = assists.get((shot.minute, shot.team_side))
                if pid is None:
                    no_assist += 1
                    continue
                if not o["dry_run"]:
                    MatchShot.objects.filter(pk=shot.pk).update(assist_player_id=pid)
                written += 1
        self.stdout.write(
            f"assist scritti: {written}   gol senza assist (o non appaiati): "
            f"{no_assist}   partite senza file di cache: {no_file}")
        if unmatched:
            self.stdout.write(self.style.WARNING(
                f"passatori del fornitore non trovati fra i nostri giocatori: {unmatched}"))
        if ambiguous:
            self.stdout.write(self.style.WARNING(
                f"minuti con due gol dello stesso lato, saltati: {ambiguous}"))
        if o["dry_run"]:
            self.stdout.write("[dry-run] niente scritto")
