"""Le novità del prodotto: chi le vede, e quando smettono di vedersi."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from vfoot.models import ProductNews, UserProfile


class NewsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("mario", password="x")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}")
        self.now = timezone.now()

    def _news(self, title, days_ago, **kw):
        return ProductNews.objects.create(
            title=title, published_at=self.now - timedelta(days=days_ago), **kw)

    def _get(self):
        return self.client.get(reverse("news")).data["items"]

    def test_chi_non_ha_mai_letto_vede_solo_lultima(self):
        """Non tutta la storia: a chi si iscrive oggi non interessa cosa e'
        cambiato a marzo, e aprire il prodotto su sei annunci arretrati e' un modo
        di far chiudere la striscia senza leggerla."""
        self._news("Vecchia", 90)
        self._news("Meno vecchia", 30)
        self._news("Probabili formazioni", 0)
        got = self._get()
        self.assertEqual([n["title"] for n in got], ["Probabili formazioni"])

    def test_chiusa_una_volta_non_torna(self):
        self._news("Probabili formazioni", 0)
        self.assertEqual(len(self._get()), 1)
        self.client.post(reverse("news-seen"), {"id": self._get()[0]["id"]})
        self.assertEqual(self._get(), [])

    def test_una_novita_nuova_ricompare(self):
        n = self._news("Probabili formazioni", 1)
        self.client.post(reverse("news-seen"), {"id": n.id})
        self._news("Mercato a offerte", 0)
        self.assertEqual([n["title"] for n in self._get()], ["Mercato a offerte"])

    def test_una_novita_uscita_fra_il_caricamento_e_il_click_non_si_perde(self):
        """Il segnalibro va sull'ultima MOSTRATA, non su ``now``. Stamparci sopra
        l'ora corrente seppellirebbe senza appello una novita' pubblicata nei
        secondi fra l'apertura della pagina e il «Ho capito»."""
        prima = self._news("Probabili formazioni", 1)
        mostrate = self._get()                         # la vede
        self.assertEqual([n["id"] for n in mostrate], [prima.id])
        appena_uscita = ProductNews.objects.create(
            title="Uscita adesso", published_at=timezone.now())
        # Chiude cio' che AVEVA davanti, non cio' che c'e' adesso.
        self.client.post(reverse("news-seen"), {"id": mostrate[0]["id"]})
        self.assertEqual([n["title"] for n in self._get()], ["Uscita adesso"])
        self.assertLess(
            UserProfile.objects.get(user=self.user).news_seen_at,
            appena_uscita.published_at)

    def test_non_attiva_o_futura_non_si_vede(self):
        """Si scrive il testo con calma e lo si accende quando il deploy e'
        andato, invece di scriverlo di fretta dopo."""
        self._news("Bozza", 0, active=False)
        ProductNews.objects.create(
            title="Programmata", published_at=self.now + timedelta(days=2))
        self.assertEqual(self._get(), [])

    def test_al_massimo_tre(self):
        zero = self._news("Zero", 10)
        self.client.post(reverse("news-seen"), {"id": zero.id})
        for i in range(5):
            self._news(f"Numero {i}", 5 - i)
        self.assertEqual(len(self._get()), 3)

    def test_senza_token_non_si_leggono(self):
        self.client.credentials()
        self.assertEqual(self.client.get(reverse("news")).status_code, 401)

    def test_un_id_mancante_o_ignoto_e_un_errore_non_un_silenzio(self):
        self.assertEqual(self.client.post(reverse("news-seen")).status_code, 400)
        self.assertEqual(
            self.client.post(reverse("news-seen"), {"id": 999999}).status_code, 400)
        # E non scrive NIENTE: una richiesta malformata non deve nemmeno creare
        # il profilo che avrebbe dovuto aggiornare.
        self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

    def test_il_segnalibro_non_torna_indietro(self):
        """Una scheda rimasta aperta da ieri che manda il suo «Ho capito» non deve
        far riapparire annunci gia' chiusi altrove."""
        vecchia = self._news("Vecchia", 10)
        nuova = self._news("Nuova", 0)
        self.client.post(reverse("news-seen"), {"id": nuova.id})
        self.client.post(reverse("news-seen"), {"id": vecchia.id})
        self.assertEqual(self._get(), [])
