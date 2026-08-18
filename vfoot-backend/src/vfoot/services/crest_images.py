"""Da un file caricato a un'immagine nostra.

La difesa contro un'immagine ostile non è una lista di formati ammessi: è **non
conservare mai i byte caricati**. Qui l'originale viene decodificato, se ne
prendono i pixel, e si riscrive un file nuovo col nostro encoder. Di quello che è
arrivato non sopravvive niente — né EXIF, né dati appesi in coda al file, né i
poliglotti (un file che è JPEG valido *e* HTML valido, e che serve a farsi
interpretare come markup da chi sniffa il tipo). Quello che serviamo l'abbiamo
scritto noi.

Perché niente SVG, che pure sarebbe il formato ideale per uno stemma: un SVG è un
documento, può contenere script e riferimenti esterni, e "ripulirlo" vuol dire
inseguire una lista di casi che si allunga. Un formato a pixel non ha questo
problema, perché la decodifica butta via tutto ciò che non è un pixel.

Il tetto sulle DIMENSIONI conta più di quello sui byte. Due megabyte di PNG
possono essere ventimila pixel per ventimila, cioè un giga e mezzo di RAM una
volta decompressi: la bomba di decompressione non ti riempie il disco, ti riempie
la memoria di una macchina con un vCPU. Perciò si guarda ``size`` (che c'è dopo
``open()``, prima di decodificare) e si rifiuta lì.

Il client ridimensiona già a 256×256 prima di spedire, quindi in condizioni
normali qui arrivano una quindicina di kilobyte. Questi controlli sono per chi il
client non lo usa.
"""
from __future__ import annotations

import io
from hashlib import sha256

from PIL import Image, ImageOps

# Quanto accettiamo di leggere. Generoso rispetto ai ~15 KB che manda il client,
# stretto rispetto alla foto che uno sceglie dalla galleria senza pensarci.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024

# Sedici megapixel: una foto da telefono ne fa dodici, quindi il caso normale
# passa. In RGBA sono ~64 MB di picco, uno alla volta — la frequenza la limita
# la view.
MAX_PIXELS = 16_000_000

# Il lato dello stemma servito. 256 perché il posto più grande in cui compare è
# l'anteprima dell'editor a 96 px, e su schermi a densità doppia 96 sono 192.
SIDE = 256

# Solo formati a pixel, e solo quelli che un telefono produce davvero.
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}

# Pillow avverte (o solleva) da sé sulle immagini spropositate: allineiamo la sua
# soglia alla nostra, così il caso limite lo intercetta chiunque arrivi prima.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class CrestImageError(ValueError):
    """Il file caricato non è utilizzabile. Il messaggio è per l'utente."""


def normalize_crest_image(raw: bytes) -> tuple[bytes, str, str]:
    """Ricodifica ``raw`` in uno stemma quadrato. Ritorna (byte, tipo, impronta).

    Solleva ``CrestImageError`` con un messaggio in italiano per ogni file che
    non superi i controlli: sono tutte cose che l'utente può capire e correggere.
    """
    if not raw:
        raise CrestImageError("Il file è vuoto.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise CrestImageError(
            f"L'immagine supera i {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")

    # Primo giro: solo per verificare l'integrità. verify() lascia il file
    # inutilizzabile, quindi dopo si riapre da capo — è documentato in Pillow, e
    # dimenticarlo dà un errore incomprensibile alla prima operazione.
    try:
        probe = Image.open(io.BytesIO(raw))
        fmt = (probe.format or "").upper()
        size = probe.size
        probe.verify()
    except CrestImageError:
        raise
    except Exception:
        raise CrestImageError("Non riesco a leggere questo file come immagine.")

    if fmt not in ALLOWED_FORMATS:
        raise CrestImageError(
            "Formato non ammesso: servono PNG, JPEG, WebP o GIF. "
            "Gli SVG non si possono caricare.")

    w, h = size
    if w < 16 or h < 16:
        raise CrestImageError("L'immagine è troppo piccola: almeno 16×16 pixel.")
    if w * h > MAX_PIXELS:
        raise CrestImageError(
            "L'immagine ha troppi pixel: ridimensionala prima di caricarla.")

    try:
        img = Image.open(io.BytesIO(raw))
        # Per i JPEG: chiede al decoder di lavorare già a scala ridotta. Non è un
        # ottimizzazione cosmetica — è la differenza fra decodificare dodici
        # megapixel e decodificarne meno di uno, su una macchina che ne ha poca.
        if fmt == "JPEG":
            img.draft("RGB", (SIDE * 2, SIDE * 2))
        # L'orientamento delle foto da telefono sta nell'EXIF, e l'EXIF lo stiamo
        # per buttare: applicarlo adesso è l'unico modo di non ritrovarsi lo
        # stemma coricato.
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGBA")
        # Riempie il quadrato ritagliando dal centro. Il ritaglio vero l'ha già
        # fatto l'utente nel browser: questa è la rete per chi manda un
        # rettangolo comunque.
        img = ImageOps.fit(img, (SIDE, SIDE), method=Image.LANCZOS,
                           centering=(0.5, 0.5))
    except CrestImageError:
        raise
    except Exception:
        raise CrestImageError("Non riesco a elaborare questa immagine.")

    out = io.BytesIO()
    content_type = "image/webp"
    try:
        # method=4 e non 6: il massimo costa parecchia CPU per una manciata di
        # byte, e la CPU qui è una sola.
        img.save(out, format="WEBP", quality=88, method=4)
    except Exception:
        # Non ogni build di Pillow ha il WebP. Meglio uno stemma un po' più
        # pesante che un caricamento che fallisce.
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        content_type = "image/png"

    data = out.getvalue()
    return data, content_type, sha256(data).hexdigest()
