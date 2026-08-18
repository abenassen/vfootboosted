"""Caricare uno stemma, servirlo, segnalarlo, toglierlo.

Quattro endpoint, e una scelta che li attraversa tutti: il server non apre mai il
descrittore dello stemma. Non sa che la chiave si chiama ``img``, non verifica che
l'impronta salvata da una squadra esista davvero. Quando serve sapere se
un'immagine compare in una lega — e serve solo per autorizzare una segnalazione o
una revoca — lo chiede al database come una domanda sul testo (`crest__contains`),
non come una lettura del JSON. Su tabelle di decine di righe è una scansione da
millisecondi, ed è l'unico posto dove la si fa.

Chi non ha l'immagine non la vede rotta: il render ricade sui livelli composti,
che nel descrittore sono rimasti. Vale per un'immagine revocata, per una copia di
sviluppo senza byte, e per una richiesta fallita in mobilità.

**L'endpoint che serve i byte non chiede il token.** Non è una svista: un
``<image>`` dentro un SVG non può mandare un'intestazione ``Authorization``. A
proteggerlo è l'indirizzo stesso — sessantaquattro cifre esadecimali di sha256,
che non si indovinano e che compaiono solo nei payload delle leghe di cui si fa
parte. È una capability URL, e il contenuto (lo stemma di una squadra di
fantacalcio) è proporzionato a quella scelta.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from vfoot.models import CrestImage, CrestReport, FantasyLeague, FantasyTeam, LeagueMembership
from vfoot.services.crest_images import (
    MAX_UPLOAD_BYTES,
    CrestImageError,
    normalize_crest_image,
)

log = logging.getLogger(__name__)


def _membership_or_404(league: FantasyLeague, user_id: int) -> LeagueMembership:
    m = LeagueMembership.objects.filter(league=league, user_id=user_id).first()
    if not m:
        raise Http404("Not a member of this league")
    return m


def _team_showing(league: FantasyLeague, image_hash: str) -> FantasyTeam:
    """La squadra di questa lega che espone quell'immagine.

    È l'autorizzazione sia della segnalazione sia della revoca: si può agire su
    un'immagine solo se la si sta effettivamente vedendo. Un admin non può
    togliere di mezzo lo stemma di una lega a cui non appartiene, e nessuno può
    segnalare un'impronta pescata a caso.

    Cerca l'impronta nel testo del descrittore invece di interpretarlo: il server
    non conosce lo schema dello stemma, e questa è l'unica domanda che ha bisogno
    di fargli — «questa lega lo nomina?», non «cosa significa?».
    """
    team = (FantasyTeam.objects.filter(league=league, crest__contains=image_hash)
            .order_by("id").first())
    if team is None:
        raise Http404("No team in this league is showing that image")
    return team


class CrestImageUploadView(APIView):
    """POST /api/v1/crest-images — un file, in cambio di un'impronta.

    Non è legata a una lega né a una squadra: un'immagine è contenuto, e chi la
    usa lo dice il descrittore con un PATCH separato. Così caricare e salvare
    restano due gesti distinti, e uno annullato non lascia l'altro a metà.
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "crest_upload"

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Manca il file."},
                            status=status.HTTP_400_BAD_REQUEST)
        # Il controllo sulla taglia prima della lettura: `size` lo dichiara la
        # richiesta, e leggere due megabyte per poi scoprire che sono venti è
        # esattamente il lavoro che non vogliamo fare.
        if upload.size and upload.size > MAX_UPLOAD_BYTES:
            return Response(
                {"detail": f"L'immagine supera i {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."},
                status=status.HTTP_400_BAD_REQUEST)

        raw = upload.read(MAX_UPLOAD_BYTES + 1)
        try:
            data, content_type, digest = normalize_crest_image(raw)
        except CrestImageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        existing = CrestImage.objects.filter(pk=digest).first()
        if existing is not None and existing.is_revoked:
            # La lapide serve a questo: l'impronta è il contenuto, quindi
            # ricaricare lo stesso file rimetterebbe online la stessa immagine.
            return Response(
                {"detail": "Questa immagine è stata rimossa da un amministratore."},
                status=status.HTTP_403_FORBIDDEN)

        if existing is None:
            # Due squadre che caricano lo stesso file condividono la riga: la
            # seconda non la riscrive, così `uploaded_by` resta il primo che l'ha
            # portata qui.
            CrestImage.objects.create(
                hash=digest, data=data, content_type=content_type,
                bytes=len(data), uploaded_by=request.user)

        return Response({"hash": digest, "bytes": len(data)},
                        status=status.HTTP_201_CREATED)


class CrestImageView(APIView):
    """GET /api/v1/crest-images/<hash> — i byte, con una cache eterna.

    Immutabile davvero, non per ottimismo: a quell'indirizzo c'è quel contenuto
    per definizione, perché l'indirizzo È l'impronta del contenuto. Quindi il
    browser può tenersela per sempre, e un cambio di stemma è un indirizzo nuovo.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, image_hash: str):
        row = (CrestImage.objects
               .filter(pk=image_hash, revoked_at__isnull=True)
               .only("hash", "data", "content_type").first())
        if row is None or not row.data:
            raise Http404("Unknown crest image")

        etag = f'"{row.hash}"'
        if request.headers.get("If-None-Match") == etag:
            response = HttpResponse(status=status.HTTP_304_NOT_MODIFIED)
        else:
            response = HttpResponse(bytes(row.data), content_type=row.content_type)
        response["ETag"] = etag
        response["Cache-Control"] = "public, max-age=31536000, immutable"
        # Il tipo lo diciamo noi e non si discute: senza questo un browser che
        # indovina il contenuto potrebbe interpretare come markup un file che
        # abbiamo dichiarato immagine.
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Disposition"] = "inline"
        return response


class _HashSerializer(serializers.Serializer):
    hash = serializers.RegexField(r"^[0-9a-f]{64}$")
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True,
                                   trim_whitespace=True)


class LeagueCrestReportView(APIView):
    """POST /api/v1/leagues/<id>/crest-reports — «questo stemma non va bene».

    Aperto a ogni membro della lega, compreso chi lo espone (capita di
    accorgersene da soli). Idempotente: la stessa persona che segnala due volte
    la stessa immagine non produce due righe, e non riceve un errore — ha già
    fatto quello che voleva fare.
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        _membership_or_404(league, request.user.id)

        s = _HashSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        image_hash = s.validated_data["hash"]
        reason = s.validated_data.get("reason", "")

        image = get_object_or_404(CrestImage, pk=image_hash)
        team = _team_showing(league, image_hash)

        report, created = CrestReport.objects.get_or_create(
            image=image, league=league, reporter=request.user,
            defaults={"reason": reason, "team": team})
        if created:
            _notify_report(report)
        return Response({"id": report.id, "created": created,
                         "detail": "Segnalazione ricevuta: la vedrà l'admin della lega."},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class LeagueCrestRevokeView(APIView):
    """POST /api/v1/leagues/<id>/crest-revoke — l'admin toglie un'immagine.

    Toglie il contenuto, non il campo: il descrittore della squadra resta com'è,
    e siccome l'immagine non risponde più, il suo stemma torna da solo a quello
    composto che c'era sotto. Nessuna passata di pulizia, nessun riquadro rotto,
    e il proprietario può rifarselo quando vuole.

    L'effetto è globale, perché l'identità dell'immagine è il suo contenuto: se
    quella figura non va bene, non va bene neanche nella lega accanto. A limitare
    il gesto è chi può farlo — l'admin di una lega in cui quell'immagine si vede.
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, league_id: int):
        league = get_object_or_404(FantasyLeague, id=league_id)
        membership = _membership_or_404(league, request.user.id)
        if membership.role != LeagueMembership.ROLE_ADMIN:
            raise Http404("Admin privileges required")

        s = _HashSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        image_hash = s.validated_data["hash"]

        image = get_object_or_404(CrestImage, pk=image_hash)
        _team_showing(league, image_hash)

        if not image.is_revoked:
            image.revoke(by=request.user, reason=s.validated_data.get("reason", ""))
        return Response({"hash": image_hash, "revoked": True})


def _notify_report(report: CrestReport) -> None:
    """Una riga a chi gestisce il sito. Fallire qui non deve far fallire là.

    Stessa regola delle segnalazioni generali (v. feedback_views): il gesto
    dell'utente è riuscito quando la riga è salvata, non quando parte la mail.
    """
    to = str(getattr(settings, "VFOOT_FEEDBACK_EMAIL", "") or "").strip()
    if not to:
        return
    chi = report.reporter.username if report.reporter else "anonimo"
    squadra = report.team.name if report.team else "n/d"
    try:
        send_mail(
            subject=f"[Vfoot] Stemma segnalato in {report.league.name}",
            message=(
                f"Segnalato da: {chi}\n"
                f"Lega: {report.league.name} (id {report.league_id})\n"
                f"Squadra: {squadra}\n"
                f"Immagine: {report.image_id}\n"
                f"Motivo: {report.reason or 'non indicato'}\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[a.strip() for a in to.split(",") if a.strip()],
            fail_silently=False,
        )
    except Exception:  # pragma: no cover - dipende dal relay
        log.exception("Segnalazione stemma %s salvata ma non spedita", report.pk)
