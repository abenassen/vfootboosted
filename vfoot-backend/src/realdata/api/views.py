"""The maintenance page's API: how the server is, and what needs a yes or a no.

Staff only (``IsAdminUser``, i.e. ``is_staff``). This is the first API surface in the
project that is scoped to whoever runs the SITE rather than to a league admin — every
other admin area here is about one league's members.

WHY THE PAGE SHOWS THE VERDICT AND NOT JUST THE PROPOSALS. Most days there is nothing
to approve, and a page that is empty on those days teaches you not to open it. The
verdict is the thing worth looking at daily; the proposals are what occasionally
appear underneath it.

WHY IT IS NOT THE ONLY WAY IN. The same decisions are available from a terminal
(``manage.py maintenance_review``), and that is deliberate: this page is served by
the very application the agent is trying to repair. When the app is the thing that
is broken, the mail still arrives and the terminal still works.
"""
from __future__ import annotations

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from realdata.models import MaintenanceProposal, MaintenanceRun
from realdata.services import health, maintenance

PENDING = MaintenanceProposal.STATUS_PROPOSED


def _brief(p: MaintenanceProposal) -> dict:
    return {
        "id": p.id,
        "kind": p.kind,
        "payload": p.payload,
        "status": p.status,
        "needs_human": p.needs_human,
        "created_at": p.created_at.isoformat(),
        "summary": p.run.summary,
        "rationale": p.rationale,
    }


class MaintenanceStateView(APIView):
    """Everything the page needs on open: the verdict, and what is waiting."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAdminUser]

    def get(self, request):
        # skip_shape: the canary reads a handful of files off disk, and a page
        # someone might refresh out of nervousness should not do disk work per tap.
        # The full check runs on its own timer at 07:30.
        report = health.report(skip_shape=True)
        pending = (MaintenanceProposal.objects.select_related("run")
                   .filter(status=PENDING).order_by("-created_at")[:20])
        recent = MaintenanceRun.objects.order_by("-started_at")[:5]
        return Response({
            "verdict": report.verdict,
            "checks": report.as_dict()["checks"],
            "pending": [_brief(p) for p in pending],
            "runs": [{
                "id": r.id,
                "started_at": r.started_at.isoformat(),
                "trigger": r.trigger,
                "summary": r.summary,
                "ok": r.ok,
                "error": r.error[:400],
            } for r in recent],
            # Shown on the page so its state is never a guess: with the auto tier
            # off, "approved" means you approved it.
            "auto_enabled": bool(getattr(settings, "VFOOT_MAINTENANCE_AUTO", False)),
        })


class MaintenanceProposalView(APIView):
    """One proposal in full — including the diff, when there is one."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAdminUser]

    def get(self, request, proposal_id: int):
        p = get_object_or_404(
            MaintenanceProposal.objects.select_related("run"), id=proposal_id)
        data = _brief(p) | {
            "evidence": p.evidence,
            "diagnosis": p.run.diagnosis,
            "agent_cmd": p.run.agent_cmd,
            "result": p.result,
            "decided_at": p.decided_at.isoformat() if p.decided_at else None,
            "diff": None,
        }
        if p.kind == MaintenanceProposal.KIND_APPLY_PATCH:
            ok, diff = maintenance.git("diff", f"main...{p.payload.get('branch','')}")
            # Capped, and the truncation is stated: a diff silently cut at the
            # bottom is how you approve a change you did not see the end of.
            lines = diff.splitlines()
            data["diff"] = ("\n".join(lines[:400]) if ok else f"(illeggibile: {diff[:200]})")
            if ok and len(lines) > 400:
                data["diff"] += (f"\n\n… altre {len(lines) - 400} righe non mostrate: "
                                 f"leggile con `git diff main...{p.payload['branch']}`.")
        return Response(data)


class MaintenanceDecideView(APIView):
    """Yes or no. The one place a human enters the loop."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAdminUser]

    def post(self, request, proposal_id: int):
        p = get_object_or_404(MaintenanceProposal, id=proposal_id)
        decision = str(request.data.get("decision", "")).strip()
        if decision not in ("approve", "reject"):
            return Response({"detail": "decision deve essere approve o reject."},
                            status=status.HTTP_400_BAD_REQUEST)
        if p.status != PENDING:
            # Not an error worth a stack trace, but not silently idempotent either:
            # two people (or two taps) must not both think they decided it.
            return Response(
                {"detail": f"gia' decisa ({p.get_status_display()}).",
                 "status": p.status},
                status=status.HTTP_409_CONFLICT)

        p.status = (MaintenanceProposal.STATUS_APPROVED if decision == "approve"
                    else MaintenanceProposal.STATUS_REJECTED)
        p.decided_by = request.user
        p.decided_at = timezone.now()
        why = str(request.data.get("why", "")).strip()
        if why:
            p.result = f"{'approvata' if decision == 'approve' else 'rifiutata'}: {why}"[:8000]
        p.save()
        return Response({
            "id": p.id, "status": p.status,
            # Said back to the caller so the page can be honest about what happens
            # next: nothing happens on this request — the executor runs on a timer.
            "note": ("La esegue il prossimo passaggio dell'esecutore (entro 5 minuti)."
                     if decision == "approve"
                     else "L'agente non la riproporra': la sua impronta entra nel "
                          "contesto della prossima passata."),
        })
