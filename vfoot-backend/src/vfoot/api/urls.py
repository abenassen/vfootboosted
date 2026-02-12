from django.urls import path

from vfoot.api.views import LineupContextView, MatchDetailView, MatchListView, SaveLineupView

urlpatterns = [
    path("lineup/context", LineupContextView.as_view(), name="lineup-context"),
    path("lineup/save", SaveLineupView.as_view(), name="lineup-save"),
    path("matches", MatchListView.as_view(), name="matches-list"),
    path("matches/<str:match_id>", MatchDetailView.as_view(), name="match-detail"),
]
