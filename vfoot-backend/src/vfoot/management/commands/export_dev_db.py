"""Produce a slim copy of the dev SQLite database, small enough to hand to a
collaborator who works on the UI.

Why this exists: `db.sqlite3` is ~865 MB and **93% of it** is
`PlayerZoneFeature` + `TeamZoneFeature` (2.7M rows plus their indexes) — the
per-zone raw inputs from which `classic_rating` recomputes voto puro on every
read. Nothing outside the scoring/role-inference code reads them, and no
foreign key points at them, so emptying the two tables and VACUUMing leaves a
database around 60 MB that still contains everything the interface needs:
players, matches, appearances, leagues, rosters, calendars, standings, and the
already-computed `FantasyFixtureDetail` payloads that the classic match-detail
view renders.

What is DELIBERATELY broken in the slim copy — say so when handing it over:
  * recomputing/concluding a matchday (voto puro comes out empty),
  * the Serie A pagelle view (`classic_pagella`),
  * voto-puro tuning and `compute_classic_roles` (role inference reads zones).
Matchdays already concluded keep their stored detail and display normally.

The copy is ALSO anonymised by default, because the obvious place to put it is
a GitHub release and this repository is public — a release asset there is a
world-readable download, not a private channel. Emails are rewritten, every
password becomes DEV_PASSWORD, and API tokens are dropped. Pass
--no-anonymize only when the destination really is private.

Usage:
    manage.py export_dev_db                  # -> dist/vfoot-dev-db.sqlite3
    manage.py export_dev_db --gzip           # also writes .gz (what you upload)
    manage.py export_dev_db --keep-zones     # full copy, for scoring-model work
    manage.py export_dev_db --no-anonymize   # keep real emails/passwords/tokens
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from realdata.models import PlayerZoneFeature, TeamZoneFeature

# Emptied unless --keep-zones. Read from the models so a table rename can't
# silently turn this command into a no-op that ships an 865 MB "slim" file.
ZONE_TABLES = (PlayerZoneFeature._meta.db_table, TeamZoneFeature._meta.db_table)

# Never useful in a copy: sessions belong to the machine that created them, and
# API tokens are live credentials for the accounts they belong to.
ALWAYS_EMPTIED = ("django_session", "authtoken_token")

# Every account in the shared copy gets this password, so whoever receives it
# can log in as `andrea` (owner of the demo league) without a shell dance.
# Documented in CONTRIBUTING.md — it protects nothing and is meant to be known.
DEV_PASSWORD = "vfoot-dev"


def _mb(path: Path) -> float:
    return path.stat().st_size / 1048576


class Command(BaseCommand):
    help = "Export a slim copy of the dev database for a collaborator (UI work)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output", "-o", default=None,
            help="Destination file (default: <repo>/dist/vfoot-dev-db.sqlite3).")
        parser.add_argument(
            "--gzip", action="store_true",
            help="Also write a .gz next to it — that is what you upload.")
        parser.add_argument(
            "--keep-zones", action="store_true",
            help="Keep the zone-feature tables: a full copy, for scoring work.")
        parser.add_argument(
            "--no-anonymize", action="store_true",
            help="Keep real emails/password hashes/tokens (private destinations only).")

    def handle(self, *args, **opts):
        db = settings.DATABASES["default"]
        if "sqlite3" not in db["ENGINE"]:
            raise CommandError(
                f"only SQLite is supported here, this project is on {db['ENGINE']}")
        source = Path(db["NAME"])
        if not source.exists():
            raise CommandError(f"database not found: {source}")

        out = Path(opts["output"]) if opts["output"] else (
            Path(settings.BASE_DIR).parent.parent / "dist" / "vfoot-dev-db.sqlite3")
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.resolve() == source.resolve():
            raise CommandError("refusing to write over the live database")

        self.stdout.write(f"sorgente : {source}  ({_mb(source):.0f} MB)")

        # sqlite3's backup API, not shutil.copy: it takes a consistent snapshot
        # even while the dev server holds the database open and writes to it.
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        dst = sqlite3.connect(out)
        try:
            src.backup(dst)
        finally:
            src.close()

        try:
            tables = list(ALWAYS_EMPTIED)
            if not opts["keep_zones"]:
                tables += list(ZONE_TABLES)
            for table in tables:
                before = dst.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                dst.execute(f"DELETE FROM {table}")
                self.stdout.write(f"  svuotata {table}: {before:,} righe")

            if not opts["no_anonymize"]:
                # Un solo hash calcolato e riusato per tutti: farne 81 con PBKDF2
                # costerebbe secondi e non aggiungerebbe nulla, la password e'
                # pubblica per definizione.
                from django.contrib.auth.hashers import make_password
                hashed = make_password(DEV_PASSWORD)
                n = dst.execute(
                    "UPDATE auth_user SET password = ?, "
                    "email = username || '@example.invalid'", (hashed,)).rowcount
                self.stdout.write(
                    f"  anonimizzati {n} utenti (email + password '{DEV_PASSWORD}')")
            dst.commit()
            # Without VACUUM the pages are merely marked free and the file stays
            # the size it was — the whole point of the export would be lost.
            self.stdout.write("  VACUUM…")
            dst.execute("VACUUM")
            dst.commit()
        finally:
            dst.close()

        self.stdout.write(self.style.SUCCESS(
            f"scritto  : {out}  ({_mb(out):.0f} MB)"))

        if opts["gzip"]:
            gz = out.with_suffix(out.suffix + ".gz")
            with open(out, "rb") as fh, gzip.open(gz, "wb", compresslevel=9) as zfh:
                shutil.copyfileobj(fh, zfh, length=1024 * 1024)
            self.stdout.write(self.style.SUCCESS(
                f"compresso: {gz}  ({_mb(gz):.0f} MB)"))

        if not opts["keep_zones"]:
            self.stdout.write(
                "\nDa dire a chi lo riceve: in questa copia il voto puro non e'\n"
                "ricalcolabile (mancano le zone feature). Le giornate gia'\n"
                "concluse si vedono, ricalcolarne una no.")
