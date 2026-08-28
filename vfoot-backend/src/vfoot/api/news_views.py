"""Le novità del prodotto: cosa mostrare, e come si smette di mostrarlo."""
from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from vfoot.models import ProductNews, UserProfile

# Quante se ne mostrano in una volta. Tre righe sono già una lista, e una lista di
# annunci non la legge nessuno: se sono di più, si vedono le più recenti.
MAX_ITEMS = 3


def _unread_for(user):
    """Le novità che questa persona non ha ancora chiuso.

    Chi non ha mai chiuso una striscia vede SOLO L'ULTIMA, non tutta la storia:
    a chi si iscrive oggi non interessa cosa è cambiato a marzo, e aprire il
    prodotto su sei annunci arretrati è un modo di far chiudere la striscia senza
    leggerla — cioè di bruciare il canale la prima volta che lo si usa.
    """
    profile, _ = UserProfile.objects.get_or_create(user=user)
    qs = ProductNews.objects.filter(active=True, published_at__lte=timezone.now())
    if profile.news_seen_at is None:
        return list(qs[:1]), profile
    return list(qs.filter(published_at__gt=profile.news_seen_at)[:MAX_ITEMS]), profile


class NewsView(APIView):
    """Cosa c'è di nuovo, per chi guarda."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        items, _ = _unread_for(request.user)
        return Response({
            "items": [{
                "id": n.id,
                "title": n.title,
                "body": n.body,
                "published_at": n.published_at.isoformat(),
            } for n in items],
        })


class NewsSeenView(APIView):
    """«Ho letto fino a questa». L'id lo manda il client, e non e' un dettaglio.

    La prima versione ricalcolava qui le non lette e stampava la piu' recente:
    ma fra il caricamento della pagina e il click puo' uscire una novita', e
    quella finiva sepolta senza che nessuno l'avesse mai vista — proprio il caso
    per cui il canale esiste. Il server non sa cosa e' stato MOSTRATO; lo sa solo
    chi l'ha mostrato, quindi lo dice lui.

    E il segnalibro non torna indietro: un id vecchio (una scheda rimasta aperta
    da ieri che manda il suo «Ho capito») non deve far riapparire annunci gia'
    chiusi altrove.
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw = request.data.get("id")
        try:
            news = ProductNews.objects.get(id=int(raw))
        except (TypeError, ValueError, ProductNews.DoesNotExist):
            return Response({"detail": "id mancante o sconosciuto."},
                            status=status.HTTP_400_BAD_REQUEST)
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        if profile.news_seen_at is None or news.published_at > profile.news_seen_at:
            profile.news_seen_at = news.published_at
            profile.save(update_fields=["news_seen_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
