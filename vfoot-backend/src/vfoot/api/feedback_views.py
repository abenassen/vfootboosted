"""Ricevere una segnalazione, e farla arrivare a chi la deve leggere.

Un endpoint solo, e nessuna lettura: chi scrive non rilegge — non è una casella
di posta, è un foglietto infilato sotto la porta. Le segnalazioni si leggono
dall'admin di Django, dove si smistano con lo stato.

La mail è un'aggiunta, mai una condizione: se il relay è giù la segnalazione è
comunque salvata e l'utente vede «ricevuto», perché il suo gesto è riuscito
davvero. È la stessa regola delle notifiche di lega (v. league_notifications).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from vfoot.models import Feedback

log = logging.getLogger(__name__)

# Quante se ne accettano da una stessa persona in un'ora. Non è una difesa da un
# attacco — chi vuole inondarci ha modi migliori — è la rete che impedisce a un
# pulsante impazzito, o a un dito nervoso, di riempire la tabella prima che
# qualcuno se ne accorga.
MAX_PER_HOUR = 20


class FeedbackSerializer(serializers.ModelSerializer):
    """Quello che il client PUÒ dire. Lo user agent non è qui: il browser lo
    dichiara da sé in ogni richiesta, e chiederne una copia al client significa
    fidarsi della copia mentre l'originale è già nell'intestazione."""

    class Meta:
        model = Feedback
        fields = ("kind", "message", "page", "viewport")

    def validate_message(self, value: str) -> str:
        text = (value or "").strip()
        if len(text) < 3:
            raise serializers.ValidationError("Scrivi qualcosa in più: così non si capisce.")
        # Il modello non ha un tetto (è una TextField) ma il campo di testo sì, e
        # un corpo enorme è quasi sempre un incidente, non una segnalazione.
        if len(text) > 4000:
            raise serializers.ValidationError(
                "Messaggio troppo lungo: raccontacelo in meno di 4000 caratteri.")
        return text


def _notify(feedback: Feedback) -> None:
    """La segnalazione a chi gestisce il sito. Fallire qui non deve fallire là."""
    to = str(getattr(settings, "VFOOT_FEEDBACK_EMAIL", "") or "").strip()
    if not to:
        return
    who = feedback.user.username if feedback.user else "anonimo"
    try:
        send_mail(
            subject=f"[Vfoot] {feedback.get_kind_display()} da {who}",
            message=(
                f"{feedback.message}\n\n"
                f"— {who}"
                f"{f' · {feedback.user.email}' if feedback.user and feedback.user.email else ''}\n"
                f"Pagina: {feedback.page or 'n/d'}\n"
                f"Schermo: {feedback.viewport or 'n/d'}\n"
                f"Browser: {feedback.user_agent or 'n/d'}\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[a.strip() for a in to.split(",") if a.strip()],
            fail_silently=False,
        )
    except Exception:  # pragma: no cover - dipende dal relay
        log.exception("Segnalazione %s salvata ma non spedita", feedback.pk)


class FeedbackCreateView(APIView):
    """POST /api/v1/feedback — una segnalazione dell'utente che ha fatto l'accesso."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = FeedbackSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        recent = Feedback.objects.filter(
            user=request.user,
            created_at__gte=timezone.now() - timedelta(hours=1)).count()
        if recent >= MAX_PER_HOUR:
            return Response(
                {"detail": "Hai già mandato parecchie segnalazioni nell'ultima ora. "
                           "Riprova più tardi — le stiamo leggendo."},
                status=status.HTTP_429_TOO_MANY_REQUESTS)

        feedback = ser.save(
            user=request.user,
            # Lo user agent lo dice il browser da sé in ogni richiesta: chiederlo
            # al client sarebbe fidarsi di una copia quando l'originale è qui.
            user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:300])
        _notify(feedback)
        return Response({"id": feedback.id, "detail": "Grazie: l'abbiamo ricevuta."},
                        status=status.HTTP_201_CREATED)
