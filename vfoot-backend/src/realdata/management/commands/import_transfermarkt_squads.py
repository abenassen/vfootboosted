"""Import Transfermarkt squad rosters into the DB, linked to SofaScore identities.

Transfermarkt is the authoritative, transfer-fresh roster source; SofaScore is where
our match/performance data and canonical ``Player`` rows live. This command marries
the two: for each club in a league season it reads the scraped TM roster (cache from
``scrape_transfermarkt_squads.py``) and, per player, resolves the matching SofaScore
``Player`` using name + date-of-birth, then:

  * records the squad membership as a ``PlayerTeamStint`` (player <-> team_season) —
    the roster fact, distinct from (but compatible with) match appearances;
  * stores the Transfermarkt id as a ``PlayerAlias`` so re-runs relink instantly and
    the cross-provider identity link is persisted;
  * fixes wrong SofaScore birth dates (Jan-1 placeholders / off-by dates) from TM;
  * creates a TM-sourced ``Player`` for squad members who never appeared in a match
    (new signings / unused subs) — the gap that rosters-from-matches cannot fill;
  * reports the consistency invariant: appearances whose team has NO roster stint =
    transfer signals to review.

Runs OFFLINE (no network). The scrape is the only network step. Idempotent + safe to
re-run weekly as squads change. Preview with --dry-run.

    python manage.py import_transfermarkt_squads \
        --cache-dir /…/historical-data/serie-a/transfermarkt/IT1/2025 \
        --competition-season 2 --dry-run
"""

from __future__ import annotations

import re

import glob
import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from realdata.models import (
    CompetitionSeason, MatchAppearance, Player, PlayerAlias, PlayerMarketValue,
    PlayerTeamStint,
    TeamSeason, PROVIDER_SOFASCORE,
)
from realdata.services.identity import (
    is_placeholder_dob, name_similarity, norm_name,
)

PROVIDER_TM = "transfermarkt"
# Transfermarkt's authoritative role label for keepers. This is the GK tag's
# single source of truth — it covers squad members who have never played (so no
# match data exists to infer from), which the formation's one-GK constraint needs.
_TM_GK_POSITION = "goalkeeper"
# TM position -> canonical classic fantasy role (POR/DIF/CEN/ATT). Wingers map to
# CEN by convention; admins can override (see role_source guard below).
_TM_ROLE_MAP = {
    "goalkeeper": Player.ROLE_GK,
    "centre-back": Player.ROLE_DEF,
    "left-back": Player.ROLE_DEF,
    "right-back": Player.ROLE_DEF,
    "defensive midfield": Player.ROLE_MID,
    "central midfield": Player.ROLE_MID,
    "attacking midfield": Player.ROLE_MID,
    "left midfield": Player.ROLE_MID,
    "right midfield": Player.ROLE_MID,
    "left winger": Player.ROLE_MID,
    "right winger": Player.ROLE_MID,
    "centre-forward": Player.ROLE_FWD,
    "second striker": Player.ROLE_FWD,
    # Generic labels TM uses when it has no detailed position on file. Omitting
    # them left the player with NO role at all — and a player with no role used
    # to disappear from the pagella as 'senza voto'. An unmapped position is now
    # also COUNTED and listed in the report (see stats["unmapped_position"]):
    # silence is what let this class of hole survive.
    "sweeper": Player.ROLE_DEF,
    "defender": Player.ROLE_DEF,
    "midfielder": Player.ROLE_MID,
    "striker": Player.ROLE_FWD,
    "forward": Player.ROLE_FWD,
    "attack": Player.ROLE_FWD,
}
# Filler tokens stripped before matching TM club names to SofaScore team names.
_CLUB_FILLER = {"fc", "ac", "us", "ss", "ssc", "acf", "as", "bc", "cfc", "afc",
                "calcio", "sporting", "club", "1907", "1909", "1913", "1919"}


def _club_key(name: str) -> str:
    toks = [t for t in norm_name(name).split()
            if t not in _CLUB_FILLER and not (t.isdigit() and len(t) == 4)]
    return " ".join(toks) or norm_name(name)



_MV_UNITS = {"k": 1_000, "m": 1_000_000, "bn": 1_000_000_000}


def _parse_market_value(raw: str) -> int | None:
    """Transfermarkt market value -> whole EUR. '€3.50m' -> 3500000, '€800k' ->
    800000, '-' / '' -> None. Unknown shapes return None rather than guessing."""
    s = (raw or "").strip().lower().replace("\u20ac", "").replace(",", "").strip()
    if not s or s == "-":
        return None
    m = re.match(r"^([0-9]*\.?[0-9]+)\s*(bn|m|k)?$", s)
    if not m:
        return None
    amount = float(m.group(1))
    return int(round(amount * _MV_UNITS.get(m.group(2) or "", 1)))

def _parse_iso(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


class Command(BaseCommand):
    help = "Import Transfermarkt rosters, link to SofaScore players, populate stints."

    def add_arguments(self, parser):
        parser.add_argument("--cache-dir", required=True,
                            help="Dir with club_*.json from the TM scraper.")
        parser.add_argument("--competition-season", type=int, default=None,
                            help="CompetitionSeason id to attach rosters to "
                                 "(default: the sofascore Serie A edition).")
        parser.add_argument("--name-threshold", type=float, default=0.6,
                            help="Min name similarity to accept a match (default 0.6).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report only; write nothing.")
        parser.add_argument("--no-fix-dob", action="store_true",
                            help="Don't correct SofaScore birth dates from TM.")
        parser.add_argument("--no-create-missing", action="store_true",
                            help="Don't create Player rows for unmatched TM players.")
        parser.add_argument("--no-close-departures", action="store_true",
                            help="Don't close roster stints of players no longer in "
                                 "any TM squad (transfers out / abroad).")
        parser.add_argument("--as-of", default=None,
                            help="ISO date for new stints' start and departures' end "
                                 "(default: today).")
        parser.add_argument("--min-squad", type=int, default=15,
                            help="Completeness guard: if any mapped club has fewer "
                                 "than this many players, skip closing departures "
                                 "(likely a partial scrape).")

    # -- setup -----------------------------------------------------------

    def _resolve_season(self, cs_id):
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

    def _map_clubs(self, tm_clubs, team_seasons):
        """Greedy one-to-one TM-club -> TeamSeason by filler-stripped name."""
        pairs = []
        for tc in tm_clubs:
            tk = _club_key(tc["name"])
            for ts in team_seasons:
                pairs.append((name_similarity(tk, _club_key(ts.team.name)),
                              tc["id"], ts.id))
        pairs.sort(key=lambda p: p[0], reverse=True)
        ts_by_id = {ts.id: ts for ts in team_seasons}
        used_tm, used_ts, mapping = set(), set(), {}
        for score, tm_id, ts_id in pairs:
            if tm_id in used_tm or ts_id in used_ts:
                continue
            used_tm.add(tm_id); used_ts.add(ts_id)
            mapping[tm_id] = (ts_by_id[ts_id], score)
        return mapping

    # -- matching --------------------------------------------------------

    def _build_indices(self, players):
        # Index ALL real DOBs, placeholders included: some players are genuinely
        # born on Jan 1, and the name-confirmation in pass 1 already rejects any
        # placeholder collision with a different player.
        by_dob, by_name = {}, {}
        for p in players:
            if p.date_of_birth:
                by_dob.setdefault(p.date_of_birth, []).append(p)
            for nm in (p.full_name, p.short_name):
                k = norm_name(nm)
                if k:
                    by_name.setdefault(k, []).append(p)
        return by_dob, by_name

    def _match(self, tp_name, tp_dob, by_dob, by_name, all_players, threshold):
        """Return (player, method) or (None, reason). method in dob|name|fuzzy."""
        # Pass 1 — exact DOB, confirmed by name (catches transliterations).
        if tp_dob:
            cands = by_dob.get(tp_dob, [])
            if cands:
                best = max(cands, key=lambda c: max(
                    name_similarity(tp_name, c.full_name),
                    name_similarity(tp_name, c.short_name)))
                if max(name_similarity(tp_name, best.full_name),
                       name_similarity(tp_name, best.short_name)) >= threshold:
                    return best, "dob"
                # else: DOB collided with a different player -> fall through.
        # Pass 2 — exact normalised name (recovers wrong/placeholder DOBs).
        nm = norm_name(tp_name)
        named = by_name.get(nm, [])
        if named:
            if len(named) == 1 or not tp_dob:
                return named[0], "name"
            # multiple same name -> closest DOB wins
            best = min(named, key=lambda c: abs((c.date_of_birth or date.min) - tp_dob))
            return best, "name"
        # Pass 3 — fuzzy name fallback (high bar) over everyone. DOB-aware: a
        # candidate with a known, non-placeholder DOB that DIFFERS from the TM
        # player's is a different person (e.g. Di Renzo 2002 vs Di Lorenzo 1993),
        # so it must never be fuzzy-merged — that would corrupt the real player.
        best, best_s = None, 0.0
        for p in all_players:
            if (tp_dob and p.date_of_birth and p.date_of_birth != tp_dob
                    and not is_placeholder_dob(p.date_of_birth)):
                continue
            s = max(name_similarity(tp_name, p.full_name),
                    name_similarity(tp_name, p.short_name))
            if s > best_s:
                best, best_s = p, s
        if best is not None and best_s >= 0.85:
            return best, "fuzzy"
        return None, "unmatched"

    # -- main ------------------------------------------------------------

    def handle(self, *args, **opts):
        cache = Path(opts["cache_dir"])
        files = sorted(glob.glob(str(cache / "club_*.json")))
        if not files:
            raise CommandError(f"No club_*.json in {cache}")
        dry = opts["dry_run"]
        fix_dob = not opts["no_fix_dob"]
        create_missing = not opts["no_create_missing"]
        close_departures = not opts["no_close_departures"]
        threshold = opts["name_threshold"]
        if opts["as_of"]:
            as_of = _parse_iso(opts["as_of"])
            if as_of is None:
                raise CommandError(f"Bad --as-of date: {opts['as_of']!r} (use ISO).")
        else:
            as_of = date.today()

        cs = self._resolve_season(opts["competition_season"])
        team_seasons = list(TeamSeason.objects.filter(competition_season=cs)
                            .select_related("team"))
        self.stdout.write(f"Season: {cs} (id={cs.id}), {len(team_seasons)} teams.")

        tm_clubs = []
        for f in files:
            d = json.loads(Path(f).read_text())
            tm_clubs.append({**d["club"], "players": d["players"]})
        mapping = self._map_clubs(tm_clubs, team_seasons)

        unmapped = [c["name"] for c in tm_clubs if c["id"] not in mapping]
        if unmapped:
            raise CommandError(f"Could not map TM clubs: {unmapped}")
        self.stdout.write("Club mapping:")
        for c in sorted(tm_clubs, key=lambda c: mapping[c["id"]][1]):
            ts, sc = mapping[c["id"]]
            flag = "  <-- low" if sc < 0.6 else ""
            self.stdout.write(f"  TM '{c['name']}' -> '{ts.team.name}' "
                              f"[{sc:.2f}]{flag}")

        ss_players = list(Player.objects.filter(external_source=PROVIDER_SOFASCORE))
        by_dob, by_name = self._build_indices(ss_players)
        # TM-id -> already-linked player (fast idempotent relink)
        tm_alias = {a.alias: a.player for a in
                    PlayerAlias.objects.filter(source=PROVIDER_TM)
                    .select_related("player")}

        stats = {"relinked": 0, "dob": 0, "name": 0, "fuzzy": 0, "created": 0,
                 "unmatched_skipped": 0, "market_values": 0, "dob_fixed": 0, "stints": 0, "gk_tagged": 0,
                 "role_set": 0, "departures_closed": 0, "unmapped_position": 0}
        dob_changes, created_players, fuzzy_pairs, unmatched = [], [], [], []
        unmapped_positions = set()
        # (player_id, team_season_id) pairs present in THIS scrape — drives the
        # departure check below. Players never seen here whose stint is still open
        # have left every Serie A squad (transfer out / abroad).
        seen_pairs = set()
        departed = []

        @transaction.atomic
        def run():
            for club in tm_clubs:
                ts, _ = mapping[club["id"]]
                for pl in club["players"]:
                    tp_name, tp_dob = pl["name"], _parse_iso(pl["dob"])
                    tm_id = str(pl["tm_id"])
                    pos_norm = (pl.get("position") or "").strip().lower()
                    is_gk = pos_norm == _TM_GK_POSITION
                    tm_role = _TM_ROLE_MAP.get(pos_norm, "")
                    # A position we don't know maps to NO role, and a player with
                    # no role used to vanish from the pagella as 'senza voto'.
                    # Never let that happen quietly: surface it in the report.
                    if pos_norm and not tm_role:
                        stats["unmapped_position"] += 1
                        unmapped_positions.add(pos_norm)
                    player = tm_alias.get(tm_id)
                    method = "relink"
                    if player is None:
                        player, method = self._match(
                            tp_name, tp_dob, by_dob, by_name, ss_players, threshold)
                    if player is None:
                        if not create_missing:
                            stats["unmatched_skipped"] += 1
                            unmatched.append((tp_name, pl["dob"], club["name"]))
                            continue
                        player = Player(external_source=PROVIDER_TM, external_id=tm_id,
                                        full_name=tp_name, short_name="",
                                        date_of_birth=tp_dob, is_goalkeeper=is_gk,
                                        classic_role=tm_role,
                                        role_source=(Player.ROLE_SOURCE_TM if tm_role else ""))
                        if not dry:
                            player.save()
                        created_players.append((tp_name, pl["dob"], club["name"]))
                        stats["created"] += 1
                    else:
                        stats[method if method in ("dob", "name", "fuzzy")
                              else "relinked"] += 1
                        if method == "fuzzy":
                            fuzzy_pairs.append((tp_name, player.full_name))
                        # DOB correction from the authoritative source
                        if (fix_dob and tp_dob and player.date_of_birth != tp_dob
                                and (player.date_of_birth is None
                                     or is_placeholder_dob(player.date_of_birth)
                                     or method in ("name", "fuzzy", "relink"))):
                            dob_changes.append(
                                (player.full_name, player.date_of_birth, tp_dob))
                            player.date_of_birth = tp_dob
                            if not dry:
                                player.save(update_fields=["date_of_birth"])
                            stats["dob_fixed"] += 1

                    # GK tag from the authoritative TM position (covers matched,
                    # relinked AND created players; idempotent on re-runs).
                    if player.is_goalkeeper != is_gk:
                        player.is_goalkeeper = is_gk
                        if not dry:
                            player.save(update_fields=["is_goalkeeper"])
                        stats["gk_tagged"] += 1

                    # Canonical classic role from TM, but NEVER clobber an admin
                    # override (role_source == "admin"). POR stays consistent with
                    # is_goalkeeper since both derive from the same TM position.
                    if (tm_role and player.role_source != Player.ROLE_SOURCE_ADMIN
                            and player.classic_role != tm_role):
                        player.classic_role = tm_role
                        player.role_source = Player.ROLE_SOURCE_TM
                        if not dry:
                            player.save(update_fields=["classic_role", "role_source"])
                        stats["role_set"] += 1

                    # Market value: provenanced external datum (provider + as_of),
                    # a secondary signal for players with no on-pitch history.
                    if not dry:
                        raw_mv = (pl.get("market_value") or "").strip()
                        if raw_mv:
                            _, mv_made = PlayerMarketValue.objects.update_or_create(
                                player=player, provider=PROVIDER_TM, as_of=as_of,
                                defaults={
                                    "value_eur": _parse_market_value(raw_mv),
                                    "raw_value": raw_mv,
                                    "provider_player_id": tm_id,
                                })
                            if mv_made:
                                stats["market_values"] += 1

                    # link (alias) + roster membership (stint)
                    if not dry:
                        PlayerAlias.objects.get_or_create(
                            player=player, source=PROVIDER_TM, alias=tm_id)
                        stint, made = PlayerTeamStint.objects.get_or_create(
                            player=player, team_season=ts,
                            defaults={"start_date": as_of,
                                      "tm_position": pos_norm})
                        if made:
                            stats["stints"] += 1
                        else:
                            fields = []
                            if stint.end_date is not None:
                                # a previously-departed player is back in this squad
                                stint.end_date = None
                                fields.append("end_date")
                            # Keep the season's position current: the role inference
                            # reads it from here rather than from the scrape cache.
                            if stint.tm_position != pos_norm:
                                stint.tm_position = pos_norm
                                fields.append("tm_position")
                            if fields:
                                stint.save(update_fields=fields)
                    if player.id is not None:  # unsaved (dry-run create) -> skip
                        seen_pairs.add((player.id, ts.id))
                    tm_alias[tm_id] = player

            # Close roster stints of players no longer in ANY scraped squad —
            # transfers out / abroad. Guarded: a partial scrape (some club with an
            # implausibly small roster) would wrongly flag a whole squad as departed,
            # so we only close when every mapped club looks fully scraped.
            min_squad = min((len(c["players"]) for c in tm_clubs), default=0)
            complete = min_squad >= opts["min_squad"]
            if close_departures:
                open_stints = (PlayerTeamStint.objects
                               .filter(team_season__competition_season=cs,
                                       end_date__isnull=True)
                               .values_list("id", "player_id", "team_season_id"))
                to_close = [(sid, pid) for sid, pid, tsid in open_stints
                            if (pid, tsid) not in seen_pairs]
                if to_close and complete:
                    if not dry:
                        PlayerTeamStint.objects.filter(
                            id__in=[s for s, _ in to_close]).update(end_date=as_of)
                    stats["departures_closed"] = len(to_close)
                    departed.extend(pid for _, pid in to_close)
                elif to_close and not complete:
                    self.stdout.write(self.style.WARNING(
                        f"Skipping departure-close: smallest squad has {min_squad} "
                        f"players (< --min-squad {opts['min_squad']}); scrape looks "
                        f"partial. {len(to_close)} stints would have been closed."))
            if dry:
                transaction.set_rollback(True)

        run()

        # Consistency invariant: appearances with no roster stint for that (player, team).
        stint_pairs = set(PlayerTeamStint.objects
                          .filter(team_season__competition_season=cs)
                          .values_list("player_id", "team_season_id"))
        appearance_pairs = set(MatchAppearance.objects
                               .filter(match__competition_season=cs)
                               .values_list("player_id", "team_season_id"))
        orphans = appearance_pairs - stint_pairs

        s = stats
        self.stdout.write(self.style.SUCCESS(
            f"\n=== {'DRY-RUN ' if dry else ''}IMPORT REPORT ==="))
        self.stdout.write(
            f"Matched to existing SofaScore players: "
            f"{s['relinked'] + s['dob'] + s['name'] + s['fuzzy']}")
        self.stdout.write(f"  relinked via TM alias : {s['relinked']}")
        self.stdout.write(f"  by DOB (+name)        : {s['dob']}")
        self.stdout.write(f"  by name (DOB differed): {s['name']}")
        self.stdout.write(f"  by fuzzy name         : {s['fuzzy']}")
        self.stdout.write(f"New TM-only players created : {s['created']}"
                          f"{' (would create)' if dry else ''}")
        if opts["no_create_missing"]:
            self.stdout.write(f"Unmatched (skipped)         : {s['unmatched_skipped']}")
        self.stdout.write(f"DOB corrections from TM      : {s['dob_fixed']}")
        self.stdout.write(f"Goalkeeper tags set/changed  : {s['gk_tagged']}")
        self.stdout.write(f"Classic roles set/changed    : {s['role_set']}")
        if s["unmapped_position"]:
            self.stdout.write(self.style.WARNING(
                f"POSIZIONI TM NON MAPPATE      : {s['unmapped_position']} giocatori "
                f"restano SENZA ruolo -> {sorted(unmapped_positions)}"))
        if not close_departures:
            self.stdout.write("Departures (transfers out)   : not checked "
                              "(--no-close-departures)")
        else:
            self.stdout.write(f"Departures closed (out/abroad): {s['departures_closed']}"
                              f"{' (would close)' if dry else ''}")
        ensured = s['relinked'] + s['dob'] + s['name'] + s['fuzzy'] + s['created']
        self.stdout.write(
            f"Roster memberships (stints)  : {ensured} ensured"
            + (f", {s['stints']} newly created" if not dry else " (dry-run)"))
        if dry:
            self.stdout.write(
                "Consistency check: skipped in dry-run (no stints written; "
                "re-run without --dry-run for the real transfer-signal count).")
        else:
            self.stdout.write(
                f"Consistency: appearances with NO roster stint: {len(orphans)} "
                f"(transfer-out / youth-cameo signals)")

        def _show(title, rows, fmt, n=20):
            if not rows:
                return
            self.stdout.write(self.style.WARNING(
                f"-- {title} ({min(n, len(rows))}/{len(rows)}):"))
            for r in rows[:n]:
                self.stdout.write("   " + fmt(r))

        _show("DOB corrected", dob_changes,
              lambda r: f"{r[0]}: {r[1]} -> {r[2]}")
        _show("created (in TM squad, never played)", created_players,
              lambda r: f"{r[0]} ({r[1]}, {r[2]})")
        _show("matched by fuzzy name (review)", fuzzy_pairs,
              lambda r: f"TM '{r[0]}' == SS '{r[1]}'")
        _show("unmatched & skipped", unmatched,
              lambda r: f"{r[0]} ({r[1]}, {r[2]})")
        if departed:
            names = dict(Player.objects.filter(id__in=departed)
                         .values_list("id", "full_name"))
            _show("departed (stint closed, no longer in any squad)",
                  [names.get(pid, pid) for pid in departed], lambda r: str(r))
