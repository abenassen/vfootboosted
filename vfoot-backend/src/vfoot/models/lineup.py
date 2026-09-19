from django.db import models
from django.utils import timezone


def _player_ids(value):
    """Gli id numerici come NUMERI, il resto intatto.

    ``"888"`` diventa ``888``; ``"P888"`` resta ``"P888"``, perche' questa
    tabella serve due mondi: la lega vera, dove un id e' la chiave di
    ``realdata.Player``, e il prototipo (``api/data_builders``), che genera id
    sintetici con la P davanti. Normalizzare solo cio' che e' un numero li tiene
    tutt'e due leggibili senza dover distinguere chi ha scritto.
    """
    if not isinstance(value, list):
        return value
    out = []
    for x in value:
        if isinstance(x, str) and x.lstrip("-").isdigit():
            out.append(int(x))
        else:
            out.append(x)
    return out


class PlayerIdListField(models.JSONField):
    """Una lista di id di giocatore, e la sua forma.

    IL MOTIVO PER CUI ESISTE. Un ``JSONField`` accetta qualunque cosa, e questi
    tre campi hanno ospitato per anni sia ``888`` che ``"888"`` senza che niente
    se ne accorgesse: il server li rilegge dappertutto con ``int(x)``, quindi
    ogni lettore perdona in silenzio. Il client no — cerca i titolari in una
    mappa con chiavi numeriche — ed e' l'unico lettore che i test non guardano.

    Il 18/09/2026 la riparazione del mercato (``lineup_repair``) ha riscritto un
    undici come stringhe: il punteggio non ha battuto ciglio, la pagina
    Formazione ha mostrato un solo giocatore su undici, e l'allenatore non
    poteva piu' schierare. Con la forma imposta QUI, nel punto per cui ogni
    scrittura passa, non c'e' piu' un modo di scriverla storta da nessun
    chiamante — presente o futuro — e i venti ``int(x)`` sparsi per il server
    smettono di essere l'unica cosa che tiene.
    """

    def pre_save(self, model_instance, add):
        value = _player_ids(getattr(model_instance, self.attname))
        # Anche sull'oggetto in memoria, non solo su cio' che va nel database:
        # chi salva e poi rilegge l'attributo deve vedere la stessa cosa che e'
        # stata scritta, o l'invariante vale solo dopo un giro di andata e ritorno.
        setattr(model_instance, self.attname, value)
        return value

    def get_prep_value(self, value):
        # La via del ``QuerySet.update()``, che non passa da ``pre_save``.
        return super().get_prep_value(_player_ids(value))


class SavedLineupSnapshot(models.Model):
    """Persisted lineup payload aligned with frontend SaveLineupRequest."""

    league_id = models.CharField(max_length=64)
    matchday_id = models.CharField(max_length=64)

    lineup_id = models.CharField(max_length=64)
    gk_player_id = models.CharField(max_length=64, null=True, blank=True)
    starter_player_ids = PlayerIdListField(default=list)
    bench_player_ids = PlayerIdListField(default=list)
    starter_backups = models.JSONField(default=list)

    saved_at = models.DateTimeField(default=timezone.now)
    # CHI L'HA SCRITTA. ``manager``: l'allenatore, dalla pagina. ``baseline``: il
    # server, quando la rosa si e' completata — l'undici suggerito per la prima
    # giornata da giocare, cosi' che «non ha mandato la formazione» non esista
    # piu' come caso (v. services/lineup_baseline). E' una formazione a tutti gli
    # effetti: il punteggio la legge, le giornate successive la ereditano, il
    # mercato la ripara. Il campo serve alla pagina, per dire «proposta dal
    # suggeritore: se non la tocchi, gioca questa» invece di «salvata».
    ORIGIN_MANAGER = "manager"
    ORIGIN_BASELINE = "baseline"
    origin = models.CharField(max_length=10, default=ORIGIN_MANAGER)

    class Meta:
        # A saved lineup is identified by league + matchday + lineup_id, where
        # lineup_id encodes the team (and competition). The constraint MUST include
        # lineup_id, else only one team per league could store a lineup per matchday.
        unique_together = [("league_id", "matchday_id", "lineup_id")]
        indexes = [models.Index(fields=["league_id", "matchday_id"])]
