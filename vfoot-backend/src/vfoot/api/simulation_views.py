"""Read-only API for the historical Vfoot league dry-run simulation.

These endpoints expose the artifact produced by
``simulate_historical_vfoot_league`` so the frontend can browse the simulated
season (standings, fixtures, fixture detail). They never mutate persistent
state and are intentionally public read-only: the data is a development/testing
surface, not user-owned.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from vfoot.services import simulation_report


class _BaseSimulationView(APIView):
    permission_classes = [AllowAny]

    def _missing(self) -> Response:
        return Response(
            {
                "detail": "Simulation artifact not available. Generate it with "
                "'python manage.py simulate_historical_vfoot_league'.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )


class SimulationOverviewView(_BaseSimulationView):
    def get(self, request):
        try:
            return Response(simulation_report.build_overview())
        except FileNotFoundError:
            return self._missing()


class SimulationFixturesView(_BaseSimulationView):
    def get(self, request):
        try:
            return Response(simulation_report.build_fixture_list())
        except FileNotFoundError:
            return self._missing()


class SimulationFixtureDetailView(_BaseSimulationView):
    def get(self, request, fixture_id: int):
        try:
            detail = simulation_report.build_fixture_detail(fixture_id)
        except FileNotFoundError:
            return self._missing()
        if detail is None:
            return Response({"detail": "Partita non trovata."}, status=status.HTTP_404_NOT_FOUND)
        return Response(detail)
