from django.urls import path

from vfoot.api.views import (
    LineupContextView,
    LoginView,
    LogoutView,
    MatchDetailView,
    MatchListView,
    MeView,
    RegisterView,
    SaveLineupView,
)

urlpatterns = [
    path("auth/register", RegisterView.as_view(), name="auth-register"),
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/me", MeView.as_view(), name="auth-me"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("lineup/context", LineupContextView.as_view(), name="lineup-context"),
    path("lineup/save", SaveLineupView.as_view(), name="lineup-save"),
    path("matches", MatchListView.as_view(), name="matches-list"),
    path("matches/<str:match_id>", MatchDetailView.as_view(), name="match-detail"),
]
