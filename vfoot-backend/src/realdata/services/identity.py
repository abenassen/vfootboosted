"""Cross-provider identity helpers: name normalisation, DOB sanity, and the
repair of the short names a provider abbreviates badly.

Shared by the Transfermarkt roster importer and the SofaScore adapter so both use
ONE definition of "same name" and "obviously-bogus birth date". Matching players
across providers (SofaScore <-> Transfermarkt) leans on (name, date-of-birth): the
name disambiguates DOB collisions, the DOB disambiguates transliterated/nicknamed
names — but neither is clean on its own (SofaScore ships Jan-1 placeholders and the
odd off-by-a-few-days date), so these helpers encode the rules that let each field
back up the other.
"""

from __future__ import annotations

import unicodedata
from datetime import date
from difflib import SequenceMatcher


def norm_name(name: str | None) -> str:
    """Lowercase, strip accents/punctuation, collapse spaces.

    'Milan Đurić' -> 'milan duric'; 'Łukasz Skorupski' -> 'lukasz skorupski'.
    """
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    no_marks = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = "".join(c if c.isalnum() else " " for c in no_marks.lower())
    return " ".join(cleaned.split())


def name_similarity(a: str | None, b: str | None) -> float:
    """Similarity in [0,1], robust to token reordering (surname-first vs -last)."""
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return 0.0
    direct = SequenceMatcher(None, na, nb).ratio()
    sa, sb = set(na.split()), set(nb.split())
    token = len(sa & sb) / len(sa | sb) if (sa | sb) else 0.0
    return max(direct, token)


def is_placeholder_dob(d: date | None) -> bool:
    """SofaScore uses Jan 1 when the real birth date is unknown — treat as missing."""
    return bool(d) and d.month == 1 and d.day == 1


# Parole che appartengono al cognome che precedono: abbreviarle spezza in due un
# cognome composto. Confrontate normalizzate, quindi minuscole e senza accenti.
# GEMELLO di ``SURNAME_PARTICLES`` in ``vfoot-frontend/src/utils/text.ts``, che le
# usa per ordinare per cognome: le due liste vanno tenute allineate.
SURNAME_PARTICLES = frozenset({
    "de", "del", "della", "delle", "delli", "dello", "dei", "degli", "di",
    "da", "dal", "dalla", "dalle", "dallo", "do", "dos", "das", "du",
    "van", "von", "der", "den", "ten", "ter", "la", "le", "lo",
    "af", "av", "bin", "ibn", "al", "el", "mac", "mc", "st", "san", "santa", "ait",
})


def _is_initial(token: str) -> bool:
    """'G.' si', 'De' no, 'G' no (l'abbreviazione del fornitore ha sempre il punto)."""
    return len(token) == 2 and token[1] == "." and token[0].isalpha()


def spell_out_particles(short_name: str | None, full_name: str | None) -> str:
    """Il nome breve del fornitore con le particelle del cognome scritte per esteso.

    SofaScore abbrevia TUTTE le parole tranne l'ultima, e su un cognome composto
    produce 'G. D. Marzi': quel 'D.' si legge come un secondo nome, mentre 'De'
    fa parte del cognome. Sbaglia anche il nostro ordinamento per cognome, che si
    ferma alle iniziali e finisce per elencarlo sotto 'Marzi G. D.'.

    Le parole si allineano da DESTRA — il lato del cognome e' l'unico che combacia
    quando il fornitore lascia cadere un secondo nome — e un'iniziale si apre solo
    se il nome completo ha, in quella posizione, una particella che comincia con
    la stessa lettera. Cosi' un nome breve che e' in realta' un soprannome
    ('G. Jesus' per 'Gabriel Silva de Jesus') resta intatto, e nel dubbio non si
    tocca niente: qui si ripara un'abbreviazione, non si ricostruisce un nome.
    """
    short_words = (short_name or "").split()
    full_words = (full_name or "").split()
    if not short_words or not full_words:
        return short_name or ""

    out = list(short_words)
    changed = False
    for i in range(1, min(len(short_words), len(full_words)) + 1):
        token, full_word = short_words[-i], full_words[-i]
        if not _is_initial(token):
            continue
        norm_full = norm_name(full_word)
        if norm_full in SURNAME_PARTICLES and norm_full[:1] == norm_name(token[0]):
            out[-i] = full_word
            changed = True
    # Invariato se non c'e' niente da aprire: il rientro delle parole toglierebbe
    # anche spazi anomali del fornitore, che non e' quello che ci hanno chiesto.
    return " ".join(out) if changed else (short_name or "")


# --- id di fornitore che nessun fornitore ha mai emesso ----------------------
#
# Circa duecento dei giocatori tesserati per una stagione arrivano da
# Transfermarkt e un'identita' SofaScore non ce l'hanno affatto: giovanili, e
# acquisti non ancora scesi in campo quando le rose sono state raccolte. Il
# simulatore di stagione deve poterli schierare, quindi conia per loro un id in
# una decade che nessun id vero occupa e lo registra come ``PlayerAlias``.
#
# CONIARE E RICONOSCERE QUELL'ID SONO LO STESSO FATTO, e stanno qui insieme per
# questo. Per un anno non lo sono stati — il formato viveva solo dentro
# ``season_simulator`` — e ogni lettore di ``PlayerAlias`` ha preso un id simulato
# per uno vero: in silenzio, perche' ne ha esattamente la forma. Un id simulato
# non fallisce, si aggancia a nulla. Chiunque porti un id FUORI dalla nostra banca
# dati — un incrocio con un altro fornitore, un artefatto spedito — deve chiedere
# prima ``is_synthetic_sofascore_id``.
#
# La forma e' 9 cifre che aprono con un 9 (``9`` + player_id su 8). Gli id veri di
# SofaScore stanno oggi fra le 5 e le 7 cifre (Maignan 191210, Fini 1164381): la
# decade e' libera con un ordine di grandezza di margine, ma non per sempre, e il
# giorno che non lo fosse questa e' l'unica funzione da cambiare.
_SYNTHETIC_SOFASCORE_DIGITS = 9


def synthetic_sofascore_id(player_id: int) -> str:
    """L'id di comodo per un giocatore che SofaScore non ha mai visto."""
    return f"9{int(player_id):08d}"


def is_synthetic_sofascore_id(value: str | int | None) -> bool:
    """Questo id l'abbiamo coniato noi? Allora non nomina nulla fuori di qui."""
    if value is None:
        return False
    text = str(value).strip()
    return (len(text) == _SYNTHETIC_SOFASCORE_DIGITS
            and text.isdigit() and text.startswith("9"))
