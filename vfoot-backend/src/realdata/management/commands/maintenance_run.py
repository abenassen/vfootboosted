"""One pass of the maintenance agent: ask, validate, record. Never execute.

    python manage.py maintenance_run                 # only if the verdict is red
    python manage.py maintenance_run --force         # ask anyway (weekly pass)
    python manage.py maintenance_run --trigger weekly

WHY THE RED VERDICT IS THE TRIGGER AND NOT A CLOCK. Waking the agent on a schedule
means it spends most of its passes reading healthy data — and a model asked every
morning whether everything is fine will, sooner or later, reassure you about a
morning when it is not. The deterministic layer is the eye that watches; the agent
is what you call once that eye has seen something.

This command writes proposals and stops. Executing them is ``maintenance_tick``, and
between the two sits either a human or the auto tier — which ships off.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from realdata.models import MaintenanceProposal, MaintenanceRun
from realdata.services import agent_client, health, job_log, maintenance

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Ask the maintenance agent about the current health verdict."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Ask even if the verdict is green.")
        parser.add_argument("--trigger", default=None,
                            choices=[t for t, _ in MaintenanceRun.TRIGGER_CHOICES],
                            help="What is asking (default: alarm, or manual with "
                                 "--force).")
        parser.add_argument("--json", action="store_true",
                            help="Machine-readable summary of the pass.")

    def handle(self, *args, **opts):
        with job_log.record("maintenance_run") as job:
            self._run(job, **opts)

    def _run(self, job, **opts):
        report = health.report()
        trigger = opts["trigger"] or (
            MaintenanceRun.TRIGGER_MANUAL if opts["force"]
            else MaintenanceRun.TRIGGER_ALARM)

        if report.verdict == "ok" and not opts["force"]:
            self.stdout.write("verdetto verde: l'agente non viene svegliato.")
            return

        job.due(agent_pass=1)
        # The same report the gate used, reused: the shape canary reads files off
        # disk and there is no reason to ask it twice in one pass.
        context = agent_client.build_context(trigger=trigger, report=report)
        # Which adapter answered is provenance, not trivia: "which model wrote
        # this?" is the first question anyone asks of a bad proposal.
        who = ("[simulato]" if settings.VFOOT_AGENT_SIMULATED
               else str(settings.VFOOT_AGENT_CMD or ""))
        run = MaintenanceRun.objects.create(
            trigger=trigger, context=context, agent_cmd=who[:200])

        try:
            answer = agent_client.ask(context)
        except agent_client.AgentError as exc:
            run.ok = False
            run.error = str(exc)[:8000]
            run.finished_at = timezone.now()
            run.save()
            job.note(f"agente fallito: {exc}")
            job.did(failed=1)
            self.stderr.write(self.style.ERROR(f"agente fallito: {exc}"))
            self.stdout.write("La sorveglianza deterministica continua comunque: "
                              "l'agente non e' portante.")
            return

        run.summary = str(answer.get("summary", ""))[:300]
        run.diagnosis = str(answer.get("diagnosis", ""))[:20000]

        max_actions = context["max_actions"]
        raw_proposals = answer.get("proposals") or []
        kept, dropped = raw_proposals[:max_actions], raw_proposals[max_actions:]
        if dropped:
            # Said out loud rather than silently truncated: a cap nobody is told
            # about reads as "the agent proposed exactly this much".
            run.diagnosis += (f"\n\n[{len(dropped)} proposte oltre il tetto di "
                              f"{max_actions} sono state scartate senza guardarle.]")

        recorded = [maintenance.record(run, raw) for raw in kept]
        run.ok = True
        run.finished_at = timezone.now()
        run.save()

        job.did(proposals=len(recorded),
                refused=sum(1 for p in recorded
                            if p.status == MaintenanceProposal.STATUS_REFUSED))
        job.note(run.summary)

        if opts["json"]:
            self.stdout.write(json.dumps({
                "run": run.id, "summary": run.summary,
                "proposals": [{"id": p.id, "kind": p.kind, "status": p.status,
                               "result": p.result} for p in recorded],
            }, ensure_ascii=False, indent=2))
            return

        self.stdout.write(self.style.NOTICE(f"[{run.trigger}] {run.summary}"))
        if run.diagnosis:
            self.stdout.write(run.diagnosis[:2000])
        if not recorded:
            self.stdout.write("  nessuna proposta.")
        for p in recorded:
            mark = {MaintenanceProposal.STATUS_REFUSED: "RESPINTA",
                    MaintenanceProposal.STATUS_APPROVED: "auto",
                    MaintenanceProposal.STATUS_DONE: "-"}.get(p.status, "attende un si'")
            self.stdout.write(f"  #{p.id} {p.kind} [{mark}] {p.payload}")
            if p.result:
                self.stdout.write(f"      {p.result[:300]}")
        pending = [p for p in recorded
                   if p.status == MaintenanceProposal.STATUS_PROPOSED]
        if pending:
            sent = self._nudge(run, pending)
            self.stdout.write("")
            self.stdout.write(f"Per decidere: la pagina /manutenzione"
                              + (f" (push inviate: {sent})" if sent else "")
                              + ", oppure manage.py maintenance_review "
                                "--approve <id> | --reject <id>")
            job.did(pushes=sent)

    def _nudge(self, run, pending) -> int:
        """Push to the people who run the site — the ones who can actually decide.

        Sent only when something WAITS for a human. An auto-tier action that already
        happened is tomorrow's digest, not a reason to wake somebody: a notification
        about a problem already solved is how the next one gets swiped away.
        """
        from django.contrib.auth.models import User

        # Imported here and not at module scope: push belongs to vfoot, the agent to
        # realdata, and only this step needs to cross. Same seam as the tick's.
        from vfoot.services import push_channel

        if not push_channel.configured():
            return 0
        what = (f"{len(pending)} proposte aspettano un sì" if len(pending) > 1
                else "Una proposta aspetta un sì")
        sent = 0
        for user in User.objects.filter(is_staff=True, is_active=True):
            try:
                sent += push_channel.send_to_user(
                    user, title="Manutenzione vfoot",
                    body=f"{run.summary or 'Anomalia rilevata'} — {what}.",
                    url="/manutenzione")
            except Exception:  # noqa: BLE001 — a mute phone must not fail the pass
                log.exception("push di manutenzione fallita per %s", user)
        return sent
