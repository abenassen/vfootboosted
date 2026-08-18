"""Il "De" non e' un secondo nome.

Il nome breve non lo componiamo noi: arriva da SofaScore gia' abbreviato, e il
fornitore accorcia OGNI parola tranne l'ultima — compresa la particella di un
cognome composto. "Giorgio De Marzi" diventa "G. D. Marzi", che si legge come un
tale di cognome Marzi con due nomi, e che il nostro ordinamento cognome-prima
elenca sotto "Marzi G. D.".

Le particelle le conoscevamo gia' (``SURNAME_PARTICLES`` di ``utils/text.ts``),
ma quella lista sta a valle e serve solo a riordinare: da "D." non si torna a
"De". L'unico posto dove la particella esiste ancora e' il nome completo, e da
li' la si rimette a posto.

Il confine e' l'altra meta' della decisione: un nome breve che e' un soprannome
("G. Jesus" per "Gabriel Silva de Jesus") NON e' una versione abbreviata del
nome completo, e va lasciato stare. Per questo le parole si allineano da destra
e un'iniziale si apre solo se il nome completo, in quella stessa posizione, ha
una particella che comincia con la sua lettera.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from realdata.models import Player
from realdata.services.identity import spell_out_particles


class SpellOutParticlesTests(SimpleTestCase):

    def test_particella_italiana(self):
        self.assertEqual(spell_out_particles("G. D. Marzi", "Giorgio De Marzi"),
                         "G. De Marzi")

    def test_particella_lunga(self):
        self.assertEqual(spell_out_particles("M. D. Rocca", "Mattia Della Rocca"),
                         "M. Della Rocca")

    def test_due_particelle_di_fila(self):
        self.assertEqual(
            spell_out_particles("I. V. d. Brempt", "Ignace Van der Brempt"),
            "I. Van der Brempt")

    def test_maiuscole_del_nome_completo(self):
        """Si copia la parola come sta nel nome completo: 'de Roon' resta minuscolo."""
        self.assertEqual(spell_out_particles("M. d. Roon", "Marten de Roon"),
                         "M. de Roon")

    def test_gia_corretto_resta_identico(self):
        for short, full in [("C. De Ketelaere", "Charles De Ketelaere"),
                            ("M. de Roon", "Marten de Roon"),
                            ("K. De Bruyne", "Kevin De Bruyne")]:
            self.assertEqual(spell_out_particles(short, full), short)

    def test_soprannome_non_e_un_abbreviazione(self):
        """'G.' sta per 'Gabriel', non per il 'de' che gli capita di fronte:
        l'iniziale si apre solo se la lettera combacia."""
        self.assertEqual(
            spell_out_particles("G. Jesus", "Gabriel Silva de Jesus"), "G. Jesus")

    def test_nome_completo_piu_lungo_del_breve(self):
        """Allineamento da destra: il secondo nome che il fornitore lascia cadere
        non deve sfasare la particella."""
        self.assertEqual(
            spell_out_particles("D. D. Battisti", "Davide Emanuele De Battisti"),
            "D. De Battisti")

    def test_nessuna_particella(self):
        self.assertEqual(spell_out_particles("L. Martinez", "Lautaro Martinez"),
                         "L. Martinez")

    def test_una_parola_sola(self):
        self.assertEqual(spell_out_particles("Dodo", "Dodo"), "Dodo")

    def test_campi_vuoti(self):
        self.assertEqual(spell_out_particles("", "Giorgio De Marzi"), "")
        self.assertEqual(spell_out_particles("G. D. Marzi", ""), "G. D. Marzi")
        self.assertEqual(spell_out_particles(None, None), "")

    def test_spazi_anomali_non_toccati(self):
        """Il rientro delle parole ripulirebbe anche gli spazi strani del
        fornitore: non e' compito di questa funzione, e cambiare piu' del dovuto
        renderebbe illeggibile il travaso."""
        self.assertEqual(spell_out_particles("D. Drobnic\xa0", "Dominik Drobnic\xa0"),
                         "D. Drobnic\xa0")

    def test_iniziale_senza_punto_non_e_un_iniziale(self):
        """Un cognome di due lettere non e' un'abbreviazione: 'Al Musrati' resta."""
        self.assertEqual(spell_out_particles("M. Al Musrati", "Mohammed Al Musrati"),
                         "M. Al Musrati")


class ShortNameAdminTests(TestCase):
    """La correzione a mano, e il segno che resta.

    Certe abbreviazioni non sono ricavabili: "Carlos Augusto" e' un nome doppio e
    nella riga non c'e' niente che lo dica. La decide una persona — chi gestisce
    il sito, dall'admin di Django — e da quel momento la riga va sottratta alle
    riparazioni automatiche, altrimenti la prossima passata rimette "C. Augusto"
    in silenzio. Il segno e' ``short_name_source``.
    """

    def setUp(self):
        self.admin = User.objects.create_superuser("capo", "capo@vfoot.it", "x")
        self.client.force_login(self.admin)
        self.player = Player.objects.create(full_name="Carlos Augusto",
                                            short_name="C. Augusto",
                                            external_source="sofascore",
                                            external_id="1")

    def _change(self, short_name):
        return self.client.post(
            f"/admin/realdata/player/{self.player.id}/change/",
            {"short_name": short_name}, follow=True)

    def test_la_correzione_si_scrive_e_resta_firmata(self):
        self.assertEqual(self._change("Carlos Augusto").status_code, 200)
        self.player.refresh_from_db()
        self.assertEqual(self.player.short_name, "Carlos Augusto")
        self.assertEqual(self.player.short_name_source, Player.SHORT_NAME_ADMIN)

    def test_salvare_senza_cambiare_niente_non_e_una_decisione(self):
        """Aprire una scheda e richiuderla non deve sottrarre la riga
        all'automatismo: firmarla per sbaglio la congelerebbe per sempre."""
        self._change("C. Augusto")
        self.player.refresh_from_db()
        self.assertEqual(self.player.short_name_source, "")

    def test_la_porta_di_ritorno(self):
        self._change("Carlos Augusto")
        r = self.client.post("/admin/realdata/player/",
                             {"action": "riaffida_all_automatismo",
                              "_selected_action": [str(self.player.id)]}, follow=True)
        self.assertEqual(r.status_code, 200)
        self.player.refresh_from_db()
        # Il valore scelto resta: si restituisce la riga, non il nome.
        self.assertEqual(self.player.short_name, "Carlos Augusto")
        self.assertEqual(self.player.short_name_source, "")

    def test_il_ruolo_non_si_tocca_da_qui(self):
        """Il ruolo ha una risoluzione a tre livelli tutta sua: cambiarlo di qui
        si vedrebbe in un posto solo. Il modulo dell'admin espone UN campo."""
        r = self.client.get(f"/admin/realdata/player/{self.player.id}/change/")
        self.assertEqual(list(r.context["adminform"].form.fields), ["short_name"])

    def test_non_si_creano_ne_si_cancellano_giocatori(self):
        """Li creano le importazioni: uno fatto a mano non avrebbe l'id del
        fornitore, e cancellarne uno porterebbe via presenze, voti e contratti."""
        self.assertEqual(self.client.get("/admin/realdata/player/add/").status_code, 403)
        self.assertEqual(
            self.client.get(f"/admin/realdata/player/{self.player.id}/delete/").status_code,
            403)
