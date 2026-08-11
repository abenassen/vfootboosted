"""Routes for the maintenance page.

Registered from ``config/urls.py`` as its own include rather than appended to
``vfoot/api/urls.py``: this is a different audience (whoever runs the site, not a
league admin) and it keeps the whole feature — models, services, adapters, API — in
one app instead of straddling two.
"""
from django.urls import path

from realdata.api.views import (
    MaintenanceDecideView, MaintenanceProposalView, MaintenanceStateView,
)

urlpatterns = [
    path("state/", MaintenanceStateView.as_view(), name="maintenance-state"),
    path("proposals/<int:proposal_id>/", MaintenanceProposalView.as_view(),
         name="maintenance-proposal"),
    path("proposals/<int:proposal_id>/decide/", MaintenanceDecideView.as_view(),
         name="maintenance-decide"),
]
