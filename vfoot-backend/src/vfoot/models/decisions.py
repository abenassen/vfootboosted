"""Decisions a league has to take, and the members' opinion on them.

Deliberately generic. The first use is settling the role of players our data
cannot classify, but the same shape fits everything a league argues about during
a season — a postponed match's voto d'ufficio, a rule change, an exceptional
transfer, a disputed rectification. Adding one is a new ``kind`` plus a service
that knows how to apply the outcome, not another model and another screen.

Two properties carry the design:

* **blocking**. Some decisions cannot wait: a listone with unresolved roles must
  not go to auction, because a role settled after the bidding changes what people
  paid for. ``blocks_market`` is what the market and roster endpoints check.
* **consultative voting**. The admin may ask the members what they think. The vote
  is an opinion, never binding — leagues are run by their admin, and a binding
  vote would need quorum and tie rules that only add ways to get stuck. What the
  members get is a voice and visibility; what the admin gets is cover.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from realdata.models import Player
from vfoot.models.fantasy import FantasyLeague


class LeagueDecision(models.Model):
    KIND_PLAYER_ROLE = "player_role"
    KIND_OTHER = "other"
    KIND_CHOICES = [(KIND_PLAYER_ROLE, "Ruolo di un giocatore"),
                    (KIND_OTHER, "Altro")]

    STATUS_OPEN = "open"
    STATUS_RESOLVED = "resolved"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [(STATUS_OPEN, "Aperta"), (STATUS_RESOLVED, "Risolta"),
                      (STATUS_CANCELLED, "Annullata")]

    league = models.ForeignKey(FantasyLeague, on_delete=models.CASCADE,
                              related_name="decisions")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES,
                            default=KIND_PLAYER_ROLE)
    # Subject of a player_role decision. Null for kinds that aren't about a player.
    player = models.ForeignKey(Player, on_delete=models.CASCADE, null=True,
                               blank=True, related_name="league_decisions")

    title = models.CharField(max_length=160)
    question = models.TextField(blank=True, default="")
    # [{"value": "CEN", "label": "Centrocampista"}, ...] — the admissible answers.
    options = models.JSONField(default=list)
    # What the system suggests. Never applied silently for a blocking decision:
    # the admin must accept it, one by one or in bulk.
    proposed = models.CharField(max_length=32, blank=True, default="")
    # Why we could not decide ("nessun dato sulla stagione precedente").
    rationale = models.TextField(blank=True, default="")

    blocks_market = models.BooleanField(default=False)
    # Set when the admin asks the members for an opinion; this is what makes the
    # decision appear to everyone rather than only in the admin's queue.
    consultation_open = models.BooleanField(default=False)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES,
                              default=STATUS_OPEN)
    outcome = models.CharField(max_length=32, blank=True, default="")
    opened_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                  blank=True, related_name="+")
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["league", "status"]),
                   models.Index(fields=["league", "blocks_market", "status"])]
        constraints = [
            # One open decision per player per league: re-running the listone
            # seeding must not pile up duplicates for the same question.
            models.UniqueConstraint(
                fields=["league", "kind", "player"],
                condition=models.Q(status="open"),
                name="uniq_open_decision_per_subject"),
        ]

    def tally(self) -> dict:
        """Votes per option. Consultative, so this informs the admin — it does not
        decide anything on its own."""
        out = {o.get("value"): 0 for o in self.options}
        for v in self.votes.values_list("option", flat=True):
            out[v] = out.get(v, 0) + 1
        return out

    def __str__(self) -> str:
        return f"[{self.league_id}] {self.title} ({self.status})"


class LeagueDecisionVote(models.Model):
    decision = models.ForeignKey(LeagueDecision, on_delete=models.CASCADE,
                                 related_name="votes")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    option = models.CharField(max_length=32)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["decision", "user"],
                                               name="uniq_vote_per_user")]

    def __str__(self) -> str:
        return f"{self.user_id} -> {self.option} on {self.decision_id}"
