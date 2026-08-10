"""Is the unattended half of the system still working? The daily answer.

Reads the run register (``JobRun``) and the warm cache, runs the deterministic
checks in ``services/health``, and says so — in Italian for a human, in JSON for
whatever reads it next.

    python manage.py health_report                 # the verdict, for a person
    python manage.py health_report --json          # the same, for a program
    python manage.py health_report --quiet         # only what is wrong
    python manage.py health_report --mail          # ...and send it, if wrong
    python manage.py health_report --strict        # exit 1 when something is wrong
    python manage.py health_report --prune         # drop the old rows

WHY ``--strict`` IS NOT THE DEFAULT. A non-zero exit makes systemd mark the unit
failed, and a unit that is permanently failed because the egress pool is low stops
being read as "something is wrong" within two days. The report says what is wrong;
whether that should also colour the unit red is the caller's decision, and on the
server it is the mail that carries the news.

WHY ``--mail`` ONLY SENDS ON A PROBLEM. A daily "everything is fine" trains the eye
to delete the message unread, which is exactly the state we are trying to leave.
Silence is the good news; use ``--mail --always`` if you want the reassurance.
"""
from __future__ import annotations

import json

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from realdata.models import JobRun
from realdata.services import health

LEVEL_STYLE = {"alarm": "ERROR", "warn": "WARNING", "info": "SUCCESS"}
LEVEL_MARK = {"alarm": "!!", "warn": " !", "info": "  "}
VERDICT_LINE = {
    "alarm": "QUALCOSA E' ROTTO",
    "warn": "regge, ma qualcosa va guardato",
    "ok": "tutto a posto",
}


class Command(BaseCommand):
    help = "Health of the scheduled jobs, the scraped data and its shape."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true",
                            help="Machine-readable output (for the maintenance "
                                 "agent, or for jq).")
        parser.add_argument("--quiet", action="store_true",
                            help="Only alarms and warnings.")
        parser.add_argument("--strict", action="store_true",
                            help="Exit 1 if anything is wrong (see the docstring "
                                 "before wiring this to a timer).")
        parser.add_argument("--mail", action="store_true",
                            help="Email the report to VFOOT_HEALTH_EMAIL when "
                                 "something is wrong.")
        parser.add_argument("--always", action="store_true",
                            help="With --mail: send even when all is well.")
        parser.add_argument("--skip-shape", action="store_true",
                            help="Skip the data-shape canary (it reads the cache "
                                 "from disk; this makes the run pure DB).")
        parser.add_argument("--prune", action="store_true",
                            help="Also drop run rows past their retention.")

    def handle(self, *args, **opts):
        report = health.report(skip_shape=opts["skip_shape"])

        pruned = None
        if opts["prune"]:
            pruned = JobRun.prune()

        if opts["json"]:
            payload = report.as_dict()
            if pruned is not None:
                payload["pruned"] = pruned
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for line in self._lines(report, quiet=opts["quiet"], pruned=pruned):
                self.stdout.write(line)

        if opts["mail"]:
            self._mail(report, opts["always"])

        if opts["strict"] and report.verdict != "ok":
            raise SystemExit(1)

    # -- rendering ---------------------------------------------------------

    def _lines(self, report, *, quiet: bool, pruned: int | None):
        head = f"{report.at:%d/%m/%Y %H:%M} — {VERDICT_LINE[report.verdict]}"
        paint = getattr(self.style, LEVEL_STYLE[
            report.verdict if report.verdict != "ok" else "info"])
        yield paint(head)
        yield ""
        shown = 0
        for check in report.checks:
            if quiet and check.level == "info":
                continue
            shown += 1
            yield f"{LEVEL_MARK[check.level]} {check.message}"
        if not shown:
            yield "   niente da segnalare."
        if pruned is not None:
            yield ""
            yield f"   registro: {pruned} righe vecchie eliminate."

    def _plain(self, report) -> str:
        out = [f"{report.at:%d/%m/%Y %H:%M} — {VERDICT_LINE[report.verdict]}", ""]
        for check in report.checks:
            out.append(f"{LEVEL_MARK[check.level]} {check.message}")
        return "\n".join(out)

    # -- mail --------------------------------------------------------------

    def _mail(self, report, always: bool) -> None:
        to = getattr(settings, "VFOOT_HEALTH_EMAIL", "") or ""
        if not to:
            self.stderr.write(self.style.WARNING(
                "--mail ma VFOOT_HEALTH_EMAIL non e' impostata nel .env: "
                "nessuna mail inviata."))
            return
        if report.verdict == "ok" and not always:
            return
        subject = {"alarm": "[vfoot] qualcosa e' rotto",
                   "warn": "[vfoot] da guardare",
                   "ok": "[vfoot] tutto a posto"}[report.verdict]
        try:
            send_mail(subject, self._plain(report),
                      settings.DEFAULT_FROM_EMAIL, [t.strip() for t in to.split(",")],
                      fail_silently=False)
        except Exception as exc:  # noqa: BLE001
            # Reported and swallowed: a mail server having a bad morning must not
            # turn the health check itself into the day's failure.
            self.stderr.write(self.style.ERROR(
                f"invio della mail fallito ({type(exc).__name__}: {exc}); "
                f"il rapporto resta nel journal."))
