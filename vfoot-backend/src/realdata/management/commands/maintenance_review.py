"""Read what the agent proposed, and say yes or no. The human gate, from a terminal.

    python manage.py maintenance_review                  # what is waiting
    python manage.py maintenance_review --show 12        # one proposal, in full
    python manage.py maintenance_review --approve 12     # queue it for the tick
    python manage.py maintenance_review --reject 12 --why "sbagliato il nome"

This is the approval path that exists TODAY, and it is all the run-in period needs:
during the run-in nothing is approved at all — the agent only reports, and you read.
The page on the phone (with the diff and two buttons) is what replaces this when the
auto tier and `apply_patch` are switched on, and not before.

A rejection is not just a "no": the fingerprint is fed back to the agent on its next
pass, so the same idea does not come round again tomorrow morning.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from realdata.models import MaintenanceProposal, MaintenanceRun

MARK = {
    MaintenanceProposal.STATUS_PROPOSED: "attende un si'",
    MaintenanceProposal.STATUS_APPROVED: "approvata",
    MaintenanceProposal.STATUS_REJECTED: "rifiutata",
    MaintenanceProposal.STATUS_DONE: "eseguita",
    MaintenanceProposal.STATUS_FAILED: "FALLITA",
    MaintenanceProposal.STATUS_REFUSED: "RESPINTA",
}


class Command(BaseCommand):
    help = "List, approve or reject maintenance proposals."

    def add_arguments(self, parser):
        parser.add_argument("--approve", type=int, default=None, metavar="ID")
        parser.add_argument("--reject", type=int, default=None, metavar="ID")
        parser.add_argument("--show", type=int, default=None, metavar="ID")
        parser.add_argument("--why", default="", help="Reason for a rejection.")
        parser.add_argument("--all", action="store_true",
                            help="Also list proposals already decided.")

    def handle(self, *args, **opts):
        if opts["approve"] and opts["reject"]:
            raise CommandError("--approve e --reject insieme non hanno senso.")
        if opts["show"]:
            return self._show(opts["show"])
        if opts["approve"]:
            return self._decide(opts["approve"], approve=True, why="")
        if opts["reject"]:
            return self._decide(opts["reject"], approve=False, why=opts["why"])
        return self._list(opts["all"])

    # -- reading -----------------------------------------------------------

    def _get(self, pid: int) -> MaintenanceProposal:
        try:
            return MaintenanceProposal.objects.select_related("run").get(id=pid)
        except MaintenanceProposal.DoesNotExist:
            raise CommandError(f"nessuna proposta #{pid}") from None

    def _list(self, show_all: bool) -> None:
        qs = MaintenanceProposal.objects.select_related("run").order_by("-created_at")
        if not show_all:
            qs = qs.filter(status=MaintenanceProposal.STATUS_PROPOSED)
        rows = list(qs[:40])
        if not rows:
            self.stdout.write("niente in attesa." if not show_all
                              else "il registro delle proposte e' vuoto.")
            return
        for p in rows:
            self.stdout.write(
                f"#{p.id:<5} {p.created_at:%d/%m %H:%M}  {p.kind:<18} "
                f"[{MARK[p.status]}]  {p.run.summary[:60]}")
        self.stdout.write("")
        self.stdout.write("Dettaglio: --show <id>.  Decidere: --approve/--reject <id>.")

    def _show(self, pid: int) -> None:
        p = self._get(pid)
        run: MaintenanceRun = p.run
        self.stdout.write(self.style.NOTICE(
            f"#{p.id} {p.kind} [{MARK[p.status]}]"))
        self.stdout.write(f"  passata   {run.started_at:%d/%m/%Y %H:%M} "
                          f"({run.trigger}, {run.agent_cmd or 'agente ignoto'})")
        self.stdout.write(f"  payload   {p.payload}")
        if run.summary:
            self.stdout.write(f"  sintesi   {run.summary}")
        if p.rationale:
            self.stdout.write("\n  perche':")
            for line in p.rationale.splitlines():
                self.stdout.write(f"    {line}")
        if p.evidence:
            self.stdout.write("\n  prove dichiarate dall'agente (NON sono una "
                              "prova: le rigira l'esecutore):")
            for key, value in p.evidence.items():
                self.stdout.write(f"    {key}: {str(value)[:400]}")
        if p.kind == MaintenanceProposal.KIND_APPLY_PATCH:
            self._show_diff(p)
        if p.result:
            self.stdout.write(f"\n  esito     {p.result[:2000]}")

    def _show_diff(self, p: MaintenanceProposal) -> None:
        from realdata.services import maintenance

        branch = p.payload.get("branch", "")
        ok, diff = maintenance.git("diff", f"main...{branch}")
        self.stdout.write(f"\n  diff di {branch}:")
        if not ok:
            self.stdout.write(f"    (illeggibile: {diff[:200]})")
            return
        for line in diff.splitlines()[:200]:
            self.stdout.write(f"    {line}")

    # -- deciding ----------------------------------------------------------

    def _decide(self, pid: int, *, approve: bool, why: str) -> None:
        p = self._get(pid)
        if p.status != MaintenanceProposal.STATUS_PROPOSED:
            raise CommandError(
                f"#{pid} e' gia' '{MARK[p.status]}': non si decide due volte.")
        p.status = (MaintenanceProposal.STATUS_APPROVED if approve
                    else MaintenanceProposal.STATUS_REJECTED)
        p.decided_at = timezone.now()
        if why:
            p.result = f"rifiutata: {why}"[:8000]
        p.save()
        if approve:
            self.stdout.write(self.style.SUCCESS(
                f"#{pid} approvata. La esegue il prossimo maintenance_tick."))
        else:
            self.stdout.write(
                f"#{pid} rifiutata. L'agente non la riproporra': la sua impronta "
                f"entra nel contesto della prossima passata.")
