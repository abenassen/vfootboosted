"""Gli stemmi caricati: ricodifica, servizio, segnalazione, revoca.

Il filo che tiene insieme quasi tutti questi test è uno solo: **quello che
serviamo l'abbiamo scritto noi**. Non basta rifiutare i file cattivi — bisogna
verificare che dei file buoni non resti niente dell'originale, perché è quella
proprietà a rendere inoffensivo tutto il resto.
"""
from __future__ import annotations

import io
import json
from hashlib import sha256

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image
from rest_framework.test import APIClient

from vfoot.models import CrestImage, CrestReport, FantasyLeague, FantasyTeam, LeagueMembership
from vfoot.services.crest_images import SIDE, CrestImageError, normalize_crest_image


def png_bytes(w: int = 400, h: int = 300, color=(200, 30, 30, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def upload_file(raw: bytes, name: str = "stemma.png", ctype: str = "image/png"):
    return SimpleUploadedFile(name, raw, content_type=ctype)


class NormalizeTests(TestCase):
    """Il servizio da solo, senza HTTP di mezzo."""

    def test_riscrive_in_un_quadrato(self):
        data, ctype, digest = normalize_crest_image(png_bytes(400, 300))
        self.assertEqual(ctype, "image/webp")
        self.assertEqual(Image.open(io.BytesIO(data)).size, (SIDE, SIDE))
        self.assertEqual(digest, sha256(data).hexdigest())

    def test_i_byte_originali_non_sopravvivono(self):
        """La proprietà su cui poggia tutta la sicurezza di questa funzione.

        Un PNG con un commento appeso dentro: il file caricato è valido, e chi
        lo conservasse così com'è servirebbe anche quel pezzo di testo. Dopo la
        ricodifica non c'è più — non perché lo cerchiamo e lo togliamo, ma
        perché di quel file abbiamo preso soltanto i pixel.
        """
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (10, 20, 30)).save(
            buf, format="PNG", pnginfo=_png_with_comment())
        payload = buf.getvalue()
        self.assertIn(b"<script>alert(1)</script>", payload)

        data, _, _ = normalize_crest_image(payload)
        self.assertNotIn(b"<script>", data)
        self.assertNotIn(b"alert", data)

    def test_stesso_contenuto_stessa_impronta(self):
        a = normalize_crest_image(png_bytes(300, 300))[2]
        b = normalize_crest_image(png_bytes(300, 300))[2]
        self.assertEqual(a, b, "l'indirizzo è il contenuto: due file uguali, un indirizzo")

    def test_rifiuta_gli_svg(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        with self.assertRaises(CrestImageError):
            normalize_crest_image(svg)

    def test_rifiuta_quello_che_non_e_un_immagine(self):
        with self.assertRaises(CrestImageError):
            normalize_crest_image(b"PK\x03\x04 non sono una figura")

    def test_rifiuta_le_immagini_spropositate(self):
        """La bomba da decompressione non riempie il disco, riempie la memoria.

        Un PNG di un colore solo a 5000×5000 pesa pochi kilobyte e ne occupa
        cento megabyte una volta decodificato. Il rifiuto arriva da `size`, che
        si legge dopo `open()` e PRIMA di decodificare.
        """
        enorme = png_bytes(5000, 5000)
        self.assertLess(len(enorme), 200_000, "il file è piccolo: è il punto")
        with self.assertRaises(CrestImageError):
            normalize_crest_image(enorme)

    def test_rifiuta_i_francobolli(self):
        with self.assertRaises(CrestImageError):
            normalize_crest_image(png_bytes(8, 8))


def _png_with_comment():
    from PIL.PngImagePlugin import PngInfo
    info = PngInfo()
    info.add_text("Comment", "<script>alert(1)</script>")
    return info


class CrestUploadApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("boss", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_carica_e_riusa_la_riga(self):
        res = self.client.post("/api/v1/crest-images",
                               {"file": upload_file(png_bytes())}, format="multipart")
        self.assertEqual(res.status_code, 201)
        digest = res.json()["hash"]
        self.assertEqual(len(digest), 64)
        self.assertEqual(CrestImage.objects.count(), 1)

        # Lo stesso file da un'altra persona non crea una seconda riga, e chi
        # l'ha portata qui per primo resta il proprietario.
        altro = User.objects.create_user("gregario", password="x")
        c2 = APIClient()
        c2.force_authenticate(user=altro)
        res2 = c2.post("/api/v1/crest-images",
                       {"file": upload_file(png_bytes())}, format="multipart")
        self.assertEqual(res2.json()["hash"], digest)
        self.assertEqual(CrestImage.objects.count(), 1)
        self.assertEqual(CrestImage.objects.get(pk=digest).uploaded_by_id, self.user.id)

    def test_serve_i_byte_con_cache_eterna(self):
        digest = self.client.post("/api/v1/crest-images",
                                  {"file": upload_file(png_bytes())},
                                  format="multipart").json()["hash"]

        # Senza token: un <image> dentro un SVG non può mandare l'Authorization.
        anon = APIClient()
        res = anon.get(f"/api/v1/crest-images/{digest}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "image/webp")
        self.assertIn("immutable", res["Cache-Control"])
        self.assertEqual(res["X-Content-Type-Options"], "nosniff")
        self.assertEqual(Image.open(io.BytesIO(res.content)).size, (SIDE, SIDE))

        res304 = anon.get(f"/api/v1/crest-images/{digest}", HTTP_IF_NONE_MATCH=res["ETag"])
        self.assertEqual(res304.status_code, 304)

    def test_impronta_sconosciuta(self):
        res = APIClient().get(f"/api/v1/crest-images/{'0' * 64}")
        self.assertEqual(res.status_code, 404)

    def test_serve_ci_vuole_il_file(self):
        res = self.client.post("/api/v1/crest-images", {}, format="multipart")
        self.assertEqual(res.status_code, 400)

    def test_un_file_qualsiasi_e_rifiutato_con_un_messaggio(self):
        res = self.client.post("/api/v1/crest-images",
                               {"file": upload_file(b"ciao", name="a.png")},
                               format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("immagine", res.json()["detail"].lower())

    def test_serve_il_token_per_caricare(self):
        res = APIClient().post("/api/v1/crest-images",
                               {"file": upload_file(png_bytes())}, format="multipart")
        self.assertIn(res.status_code, (401, 403))


class CrestModerationTests(TestCase):
    """Segnalare e revocare: chi può, su cosa, e cosa succede dopo."""

    def setUp(self):
        self.admin = User.objects.create_user("boss", password="x")
        self.member = User.objects.create_user("gregario", password="x")
        self.stranger = User.objects.create_user("estraneo", password="x")

        self.league = FantasyLeague.objects.create(name="L", owner=self.admin)
        self.admin_m = LeagueMembership.objects.create(
            league=self.league, user=self.admin, role=LeagueMembership.ROLE_ADMIN)
        self.member_m = LeagueMembership.objects.create(
            league=self.league, user=self.member, role=LeagueMembership.ROLE_MANAGER)
        self.team = FantasyTeam.objects.create(
            league=self.league, manager=self.member_m, name="Rivali FC")
        self.admin_team = FantasyTeam.objects.create(
            league=self.league, manager=self.admin_m, name="Capolista")

        self.digest = self._carica(self.member)
        self.team.crest = json.dumps({"shape": "shield", "img": self.digest})
        self.team.save(update_fields=["crest"])

    def _as(self, user) -> APIClient:
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _carica(self, user, color=(200, 30, 30, 255)) -> str:
        return self._as(user).post(
            "/api/v1/crest-images", {"file": upload_file(png_bytes(color=color))},
            format="multipart").json()["hash"]

    def _report_url(self) -> str:
        return f"/api/v1/leagues/{self.league.id}/crest-reports"

    def _revoke_url(self) -> str:
        return f"/api/v1/leagues/{self.league.id}/crest-revoke"

    # --- segnalazione -----------------------------------------------------

    def test_un_membro_segnala(self):
        res = self._as(self.admin).post(
            self._report_url(), {"hash": self.digest, "reason": "non si può vedere"},
            format="json")
        self.assertEqual(res.status_code, 201)
        report = CrestReport.objects.get()
        self.assertEqual(report.team_id, self.team.id)
        self.assertEqual(report.league_id, self.league.id)
        self.assertIsNone(report.resolved_at)

    def test_segnalare_due_volte_non_fa_due_righe(self):
        self._as(self.admin).post(self._report_url(), {"hash": self.digest}, format="json")
        res = self._as(self.admin).post(self._report_url(), {"hash": self.digest},
                                        format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["created"])
        self.assertEqual(CrestReport.objects.count(), 1)

    def test_un_estraneo_non_segnala(self):
        res = self._as(self.stranger).post(self._report_url(), {"hash": self.digest},
                                           format="json")
        self.assertEqual(res.status_code, 404)

    def test_non_si_segnala_un_immagine_che_qui_non_si_vede(self):
        """L'autorizzazione è «la sto guardando», non «ne conosco l'impronta»."""
        altrove = self._carica(self.admin, color=(10, 10, 200, 255))
        res = self._as(self.admin).post(self._report_url(), {"hash": altrove},
                                        format="json")
        self.assertEqual(res.status_code, 404)

    def test_impronta_malformata(self):
        res = self._as(self.admin).post(self._report_url(), {"hash": "non-un-hash"},
                                        format="json")
        self.assertEqual(res.status_code, 400)

    # --- revoca -----------------------------------------------------------

    def test_l_admin_revoca_e_lo_stemma_ricade_sul_composto(self):
        res = self._as(self.admin).post(self._revoke_url(),
                                        {"hash": self.digest, "reason": "offensiva"},
                                        format="json")
        self.assertEqual(res.status_code, 200)

        image = CrestImage.objects.get(pk=self.digest)
        self.assertTrue(image.is_revoked)
        self.assertEqual(bytes(image.data), b"", "i byte si liberano")
        self.assertEqual(image.revoked_by_id, self.admin.id)

        # Il descrittore della squadra NON viene toccato: i livelli composti
        # restano, ed è su quelli che il render ricade quando l'immagine tace.
        self.team.refresh_from_db()
        self.assertIn(self.digest, self.team.crest)
        self.assertEqual(json.loads(self.team.crest)["shape"], "shield")

        self.assertEqual(APIClient().get(f"/api/v1/crest-images/{self.digest}").status_code,
                         404)

    def test_la_revoca_chiude_le_segnalazioni(self):
        self._as(self.admin).post(self._report_url(), {"hash": self.digest}, format="json")
        self._as(self.admin).post(self._revoke_url(), {"hash": self.digest}, format="json")
        self.assertIsNotNone(CrestReport.objects.get().resolved_at)

    def test_un_manager_non_revoca(self):
        res = self._as(self.member).post(self._revoke_url(), {"hash": self.digest},
                                         format="json")
        self.assertEqual(res.status_code, 404)
        self.assertFalse(CrestImage.objects.get(pk=self.digest).is_revoked)

    def test_l_admin_non_revoca_quello_che_non_ha_in_lega(self):
        altrove = self._carica(self.admin, color=(10, 10, 200, 255))
        res = self._as(self.admin).post(self._revoke_url(), {"hash": altrove},
                                        format="json")
        self.assertEqual(res.status_code, 404)

    def test_ricaricare_un_immagine_revocata_non_la_riporta_online(self):
        """Il motivo per cui si revoca invece di cancellare.

        L'indirizzo è l'impronta del contenuto: cancellare la riga libererebbe
        l'indirizzo, e lo stesso file lo riprenderebbe identico. La lapide vieta
        il contenuto, non il file.
        """
        self._as(self.admin).post(self._revoke_url(), {"hash": self.digest}, format="json")
        res = self._as(self.member).post(
            "/api/v1/crest-images", {"file": upload_file(png_bytes())},
            format="multipart")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(APIClient().get(f"/api/v1/crest-images/{self.digest}").status_code,
                         404)


class CrestOpacityTests(TestCase):
    """Il server continua a non capire il descrittore.

    Il test che c'era già (`tests_team_identity.test_crest_is_opaque_to_the_server`)
    dice che qualsiasi stringa viene immagazzinata verbatim. Questo dice la cosa
    più forte che serve adesso: un'impronta INVENTATA si salva lo stesso, perché
    la validazione non sta nella scrittura — sta nel fatto che quell'indirizzo
    poi non risponde.
    """

    def setUp(self):
        self.user = User.objects.create_user("boss", password="x")
        self.league = FantasyLeague.objects.create(name="L", owner=self.user)
        m = LeagueMembership.objects.create(
            league=self.league, user=self.user, role=LeagueMembership.ROLE_ADMIN)
        self.team = FantasyTeam.objects.create(league=self.league, manager=m, name="Mia")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_un_impronta_inventata_si_salva_e_non_risponde(self):
        inventata = "f" * 64
        res = self.client.patch(
            f"/api/v1/leagues/{self.league.id}/team",
            {"crest": json.dumps({"shape": "circle", "img": inventata})}, format="json")
        self.assertEqual(res.status_code, 200)
        self.team.refresh_from_db()
        self.assertIn(inventata, self.team.crest)
        self.assertEqual(APIClient().get(f"/api/v1/crest-images/{inventata}").status_code,
                         404)
