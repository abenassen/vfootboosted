"""Scheduler tick — the always-on heartbeat of the semiautomatic pipeline.

Runs frequently (e.g. every minute via cron/systemd on the server). Each run it
asks the DB "what is due now?" and acts:

* stamps observed full-time on freshly-finished matches;
* gives each in-progress match a ROUND — lifecycle, score and the per-player data,
  so the votes move while it is being played, without promoting it. Every k-th
  round is HEAVY: it also pulls a heatmap per player, and with them the positional
  half of the model;
* runs the post-FT finalization — one scrape at +15min and one at +1h, and no
  more than that — promoting a match to ``data_ready`` at the confirmation.

It is also where the two ways of telling somebody are triggered, and they are not
interchangeable. The WebSocket nudge goes to pages that are OPEN, after any import
that changed something. The push goes to people who are NOT looking — a goal by one
of their players, a sending-off, full time — and never for a vote that moved, which
would be unbearable.

    python manage.py tick                     # apply, real clock
    python manage.py tick --dry-run           # report only
    python manage.py tick --now 2026-08-22T15:30:00Z --dry-run   # test a moment
"""
from __future__ import annotations

from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as djtz

from realdata.models import Match
from realdata.services import job_log, live_ingest
from realdata.services import probable_lineups as forecasts
from realdata.services.match_scheduler import (
    candidate_matches, clock_drift, human_gap, plan_tick,
)


class Command(BaseCommand):
    help = "One scheduler tick: advance live/finalization state for due matches."

    def add_arguments(self, parser):
        parser.add_argument("--now", type=str, default=None,
                            help="Override the clock (ISO 8601, e.g. "
                                 "'2026-08-22T15:30:00Z'); for testing.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report due actions without mutating anything.")

    def _resolve_now(self, raw) -> datetime:
        if not raw:
            return djtz.now()
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CommandError(f"Invalid --now {raw!r}: {exc}") from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    # -- main --------------------------------------------------------------

    def handle(self, *args, **options):
        now = self._resolve_now(options["now"])
        dry = options["dry_run"]
        # The run is recorded whatever it does, including nothing: "the tick was
        # alive and had nothing to do" and "the tick has not run since Friday" read
        # identically in the journal and are opposite facts. See services/job_log.
        with job_log.record("tick", dry_run=dry) as run:
            self._tick(now, dry, run)

    def _tick(self, now, dry, run) -> None:
        matches = list(candidate_matches())
        plan = plan_tick(now, matches)

        # Stated from the PLAN, before acting: what follows is only readable next
        # to it. Zero imports with zero due is a quiet Tuesday; zero imports with
        # four live matches is the egress on the floor.
        run.due(stamp_ft=len(plan.stamp_ft), live_round=len(plan.live_round),
                live_heavy=len(plan.live_heavy),
                final_check=len(plan.final_check),
                final_confirm=len(plan.final_confirm))
        run.did(candidates=len(matches))

        mode = "DRY-RUN" if dry else "APPLY"
        self.stdout.write(self.style.NOTICE(
            f"tick @ {now.isoformat()} [{mode}] — "
            f"{len(matches)} candidate matches — {plan.summary()}"))

        # Said BEFORE the plan is acted on and whatever the plan turns out to be:
        # a clock behind its data usually empties the plan, but a half-drifted
        # database still acts on the part that is due, and that is worth flagging
        # too. See ``clock_drift`` for why the symptom is otherwise unreadable.
        drift = clock_drift(now)
        if drift is not None:
            run.did(clock_drift_hours=round(drift.total_seconds() / 3600, 1))
            run.note("la banca dati e' avanti all'orologio")
            self.stdout.write(self.style.WARNING(
                f"  la banca dati e' AVANTI all'orologio di {human_gap(drift)}: "
                f"porta timbri da un istante che deve ancora venire, e finche' "
                f"l'orologio non li avra' raggiunti nessun round sara' dovuto. "
                f"Se e' una simulazione: ./vfoot-sim reset|build <scenario>."))

        # 0) LE PROBABILI, e stanno qui per una ragione precisa: girano SOLO se il
        #    piano e' vuoto, cioe' se non c'e' una partita in corso ne' una da
        #    finalizzare. E' cosi' che si esprime "ultima priorita'" senza inventare
        #    una coda: il namespace di uscita e' uno solo (v. egress_lock), e una
        #    formazione prevista non deve poter far aspettare un voto.
        #
        #    Il nostro motore non chiede niente alla rete e potrebbe girare sempre;
        #    gira qui lo stesso, perche' la sua previsione e quella di SofaScore
        #    vanno lette insieme e non ha senso averne una fresca e una vecchia.
        if plan.is_empty():
            if dry:
                self.stdout.write("  nothing due (le probabili non girano in dry-run)")
                return
            report = forecasts.refresh_all(now)
            run.did(**{f"forecast_{k}": v for k, v in report.items()
                       if isinstance(v, int)})
            if report.get("due") or report.get("built"):
                self.stdout.write(
                    f"  [probabili] nostre={report.get('built', 0)} "
                    f"sofascore: dovute={report.get('due', 0)} "
                    f"importate={report.get('imported', 0)} "
                    f"vuote={report.get('empty', 0)}"
                    + (" — EGRESS OCCUPATO, si riprova" if report.get("blocked") else ""))
            else:
                self.stdout.write("  nothing due")
            return

        # Imported here and not at module scope: the tick belongs to realdata, the
        # leagues to vfoot, and only this step needs to cross.
        from vfoot.services import live_updates

        # Collected across every step and sent ONCE at the end. A Sunday evening
        # tick imports three matches; nudging inside the loop had every open page
        # re-read the whole calendar three times in eight seconds, for a round that
        # changed once.
        nudge: set[int] = set()

        # 1) Stamp observed full-time (state we own). This is the ONE instant at
        #    which a match is first seen to be over, so it is where the full-time
        #    notification belongs — not in the import, which runs again afterwards.
        for m in plan.stamp_ft:
            self.stdout.write(f"  [stamp-ft] {m} — full-time observed")
            if not dry:
                m.finished_at = now
                m.save(update_fields=["finished_at"])
                sent = live_updates.announce_full_time(m)
                nudge |= live_updates.leagues_to_nudge(m)
                run.did(stamped_ft=1, pushes=sent or 0)
                if sent:
                    self.stdout.write(f"    push fine partita: {sent}")

        # 2) The live round: status, score and the per-player data, on ONE clock.
        #    Every k-th round is also heavy (a heatmap per player) and is the only
        #    one that stamps data_imported_at, so the two stamps no longer race.
        #    data_ready is never touched here — the votes a round produces are
        #    provisional by construction, and that is what the league marks them as.
        #    Nothing is stamped unless the round really went through, so a blocked
        #    egress simply retries next tick.
        for m in plan.live_round:
            heavy = m in plan.live_heavy
            label = "live-heavy" if heavy else "live-round"
            if dry:
                self.stdout.write(f"  [{label}] {m} — would warm+import")
                continue
            before = live_updates.snapshot_events(m)
            if not live_ingest.live_round(m, heavy=heavy):
                run.did(egress_blocked=1)
                self.stdout.write(f"  [{label}] {m} — egress blocked; will retry")
                continue
            m.data_checked_at = now
            fields = ["data_checked_at"]
            if heavy:
                m.data_imported_at = now
                fields.append("data_imported_at")
            m.save(update_fields=fields)
            events = live_updates.announce_events(m, before)
            nudge |= live_updates.leagues_to_nudge(m)
            run.did(imported=1, heavy=1 if heavy else 0, pushes=events or 0)
            self.stdout.write(
                f"  [{label}] {m} — {m.status} {m.home_goals}-{m.away_goals}"
                + (f", push: {events}" if events else ""))

        # 5) Finalization: +15min provisional-final import.
        for m in plan.final_check:
            if dry:
                self.stdout.write(f"  [final-check] {m} — would warm+import")
                continue
            if live_ingest.finalize(m):
                m.data_checked_at = now
                m.data_imported_at = now
                m.save(update_fields=["data_checked_at", "data_imported_at"])
                nudge |= live_updates.leagues_to_nudge(m)
                run.did(imported=1, finalized=1)
                self.stdout.write(f"  [final-check] {m} — imported (provisional)")
            else:
                run.did(egress_blocked=1)
                self.stdout.write(f"  [final-check] {m} — egress blocked; will retry")

        # 6) Finalization: +1h confirmation -> data_ready (official). The nudge here
        #    is the one that clears the "provvisorio" mark on every open page.
        for m in plan.final_confirm:
            if dry:
                self.stdout.write(f"  [final-confirm] {m} — would warm+import -> data_ready")
                continue
            if live_ingest.finalize(m):
                m.data_checked_at = now
                m.data_imported_at = now
                m.data_ready = True
                m.save(update_fields=["data_checked_at", "data_imported_at",
                                      "data_ready"])
                nudge |= live_updates.leagues_to_nudge(m)
                run.did(imported=1, promoted=1)
                self.stdout.write(f"  [final-confirm] {m} — data_ready")
            else:
                run.did(egress_blocked=1)
                self.stdout.write(f"  [final-confirm] {m} — egress blocked; will retry")

        if nudge:
            live_updates.broadcast_leagues(nudge)
            run.did(leagues_nudged=len(nudge))
            self.stdout.write(f"  {len(nudge)} leghe avvisate")

        if not dry:
            self.stdout.write(self.style.SUCCESS("  applied"))
