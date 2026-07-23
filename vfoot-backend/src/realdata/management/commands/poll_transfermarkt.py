"""Poll Transfermarkt rosters and fold the changes into the DB — one unattended run.

This is the automatable wrapper around the two manual steps (scrape then import):
it exists so a systemd timer can run the whole thing once or twice a day on the
server. Transfermarkt reaches fine from the Linode datacenter IP (unlike SofaScore,
see ROADMAP §1), so this can live entirely server-side.

It does end to end, safely for an unattended context:

  1. Fresh scrape of every club in the competition into a throwaway temp dir. The
     standalone scraper SKIPS clubs whose cache file already exists — right for a
     resumable manual pass, wrong for a daily poll, which must see today's squads.
     So we always scrape into a clean dir and delete it afterwards.

  2. A completeness guard the manual path leaves to the human's eyes: departures
     (stint closures) are only allowed when EVERY club was scraped successfully.
     The import's own ``--min-squad`` guard checks squad *size*, not whether all
     ~20 clubs are present — so a single club page 500ing would make its whole
     roster look "departed" and close every one of their stints. Unattended, that
     silently corrupts the listone; here we pass --no-close-departures and warn.

  3. The existing ``import_transfermarkt_squads`` does the rest (identity matching,
     stints, roles, market values) and additively refreshes each classic league's
     frozen listone — new signings get seeded, frozen roles never drift.

    python manage.py poll_transfermarkt                    # apply
    python manage.py poll_transfermarkt --dry-run          # scrape + report only
    python manage.py poll_transfermarkt --competition IT1 --season 2025
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from realdata.management.commands.import_transfermarkt_squads import PROVIDER_SOFASCORE
from realdata.models import CompetitionSeason, TeamSeason
from realdata.services.scrape_transfermarkt_squads import TM


class Command(BaseCommand):
    help = "Scrape Transfermarkt rosters and import them (one unattended poll)."

    def add_arguments(self, parser):
        parser.add_argument("--competition", default="IT1",
                            help="TM competition code (Serie A=IT1).")
        parser.add_argument("--season", type=int, default=None,
                            help="Override the TM season start year (2026 = 26/27). "
                                 "By default it is DERIVED from the resolved "
                                 "CompetitionSeason so the two can never diverge.")
        parser.add_argument("--competition-season", type=int, default=None,
                            help="CompetitionSeason id to import into (default: "
                                 "latest sofascore Serie A).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Scrape for real but import in report-only mode.")
        parser.add_argument("--delay", type=float, default=2.0)
        parser.add_argument("--jitter", type=float, default=1.5)
        parser.add_argument("--min-map-score", type=float, default=0.5,
                            help="Abort if any club maps below this name score "
                                 "(unattended safety; default 0.5).")
        parser.add_argument("--keep-cache", action="store_true",
                            help="Don't delete the temp scrape dir (debugging).")

    def _resolve_season(self, cs_id) -> CompetitionSeason:
        # Same resolution the import uses, duplicated here only to size the
        # completeness guard (how many clubs we MUST scrape).
        if cs_id is not None:
            try:
                return CompetitionSeason.objects.get(id=cs_id)
            except CompetitionSeason.DoesNotExist:
                raise CommandError(f"No CompetitionSeason id={cs_id}")
        cs = (CompetitionSeason.objects
              .filter(competition__external_source=PROVIDER_SOFASCORE,
                      competition__name__icontains="Serie A")
              .order_by("-id").first())
        if not cs:
            raise CommandError("No sofascore Serie A CompetitionSeason; pass "
                               "--competition-season.")
        return cs

    def _tm_season(self, cs: CompetitionSeason, override) -> int:
        """Start year TM expects (2026 = 26/27). Derived from the CompetitionSeason
        so the scrape and the import target can never drift onto different real
        seasons — the mistake that turns a whole squad into phantom departures."""
        derived = None
        code = (cs.season.code or "").strip()
        if len(code) >= 4 and code[:4].isdigit():
            derived = int(code[:4])
        if override is not None:
            if derived is not None and override != derived:
                self.stdout.write(self.style.WARNING(
                    f"--season {override} overrides the season derived from {cs} "
                    f"({derived}); scrape and import target DIFFERENT seasons."))
            return override
        if derived is None:
            raise CommandError(
                f"Cannot derive TM season from {cs} (season code {code!r}); "
                f"pass --season explicitly.")
        return derived

    def handle(self, *args, **opts):
        cs = self._resolve_season(opts["competition_season"])
        tm_season = self._tm_season(cs, opts["season"])
        expected = TeamSeason.objects.filter(competition_season=cs).count()
        self.stdout.write(self.style.NOTICE(
            f"poll_transfermarkt: {opts['competition']} {tm_season} "
            f"-> {cs} (id={cs.id}), {expected} teams expected"))

        tmp = Path(tempfile.mkdtemp(prefix="tm_poll_"))
        out = tmp / opts["competition"] / str(tm_season)
        out.mkdir(parents=True, exist_ok=True)
        try:
            scraped, failed = self._scrape(out, opts["competition"], tm_season, opts)
            if scraped == 0:
                raise CommandError("Scraped 0 clubs — TM unreachable or blocked. "
                                   "Nothing imported.")

            # The guard the manual path leaves to human judgement: only trust a
            # departure signal when the roster picture is COMPLETE. A missing club
            # (transient failure) would otherwise mass-close its players' stints.
            all_present = (failed == 0 and expected and scraped == expected)
            if not all_present:
                self.stdout.write(self.style.WARNING(
                    f"Incomplete scrape ({scraped}/{expected} clubs, {failed} "
                    f"failed): closing departures is DISABLED this run to avoid "
                    f"false transfers-out. Arrivals/updates still applied."))

            call_command(
                "import_transfermarkt_squads",
                cache_dir=str(out),
                competition_season=cs.id,
                dry_run=opts["dry_run"],
                no_close_departures=not all_present,
                # Unattended: refuse a club that maps to the wrong TeamSeason at a
                # low name score rather than importing a wrong roster silently.
                min_map_score=opts["min_map_score"],
            )
        finally:
            if opts["keep_cache"]:
                self.stdout.write(f"(kept scrape cache at {out})")
            else:
                shutil.rmtree(tmp, ignore_errors=True)

    def _scrape(self, out: Path, competition: str, season: int, opts) -> tuple[int, int]:
        """Fresh scrape into `out`. Returns (clubs_scraped, clubs_failed)."""
        tm = TM(out, min_delay=opts["delay"], jitter=opts["jitter"],
                logger=self.stdout.write)
        scraped = failed = 0
        try:
            clubs = tm.clubs(competition, season)
            self.stdout.write(f"{len(clubs)} clubs listed.")
            for i, club in enumerate(clubs, 1):
                try:
                    roster = tm.squad(club)
                except Exception as exc:  # noqa: BLE001 — one bad club, keep going
                    failed += 1
                    self.stdout.write(self.style.WARNING(
                        f"  [{i}/{len(clubs)}] {club['name']}: FAILED "
                        f"{type(exc).__name__}: {exc}"))
                    continue
                f = out / f"club_{club['id']}.json"
                tmp = f.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(
                    {"club": club, "players": roster}, ensure_ascii=False, indent=2))
                tmp.replace(f)
                scraped += 1
                self.stdout.write(f"  [{i}/{len(clubs)}] {club['name']}: "
                                  f"{len(roster)} players")
        finally:
            tm.close()
        return scraped, failed
