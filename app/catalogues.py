"""Catalogues Carrefour publiés sur promocatalogues.fr (pages du catalogue en images)."""
import io
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import httpx
from PIL import Image
from pydantic import BaseModel

from .models import Extraction, Offre

SITE = "https://www.promocatalogues.fr"
CDN = "https://img.offers-cdn.net"
LISTE = f"{SITE}/magasins/carrefour/catalogues-promotions"
# Catalogues hors courses alimentaires ou d'autres régions, inutiles pour le Carrefour de Givors (hyper, Rhône).
# promocatalogues.fr ne filtre pas par magasin : la page de Givors liste les mêmes catalogues que la liste nationale.
EXCLUS = ("bretagne", "alsace", "bredele", "jouets", "voyages", "energies", "tex ", "culture", "sorties")
CACHE = Path(__file__).parent.parent / "data" / "catalogues"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}


class Catalogue(BaseModel):
    id: int
    titre: str
    debut: date | None
    fin: date | None
    couverture: str


def _get(url: str) -> httpx.Response:
    r = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
    r.raise_for_status()
    return r


def parser_liste(html: str) -> list[Catalogue]:
    graphe = []
    for bloc in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        graphe += json.loads(bloc).get("@graph", [])
    images = {n["@id"]: n for n in graphe if n.get("@type") == "ImageObject"}
    catalogues = []
    for liste in (n for n in graphe if n.get("@type") == "ItemList"):
        for item in liste.get("itemListElement", []):
            m = re.search(r"-(\d+)$", item.get("url", ""))
            if not m:
                continue
            image_id = item.get("image", {}).get("@id", "")
            nom = images.get(image_id, {}).get("name", "")
            dates = re.findall(r"\d{2}/\d{2}/\d{4}", nom)
            # Le slug de l'image porte le sous-titre : catalogue-carrefour-vos-promos-du-quotidien-h400WebP-...
            slug = re.search(r"/catalogue-carrefour-?(.*?)-h400", image_id)
            sous_titre = slug.group(1).replace("-", " ").strip() if slug else ""
            catalogues.append(Catalogue(
                id=int(m.group(1)),
                titre=item.get("name", "Catalogue Carrefour") + (f" : {sous_titre}" if sous_titre else ""),
                debut=datetime.strptime(dates[0], "%d/%m/%Y").date() if dates else None,
                fin=datetime.strptime(dates[1], "%d/%m/%Y").date() if len(dates) > 1 else None,
                couverture=image_id,
            ))
    return catalogues


def parser_pages(html: str) -> list[str]:
    m = re.search(r"let flyerPages = (\[.*?\]);", html, re.S)
    if not m:
        raise ValueError("Pages du catalogue introuvables")
    # "%s" est la taille d'image ; "large" ≈ 1200x2000, lisible par l'IA
    return [CDN + p["page"].replace("%s", "large") for p in json.loads(m.group(1))]


_liste: tuple[float, list[Catalogue]] = (0, [])


def catalogues_en_cours(aujourdhui: date | None = None) -> list[Catalogue]:
    global _liste
    aujourdhui = aujourdhui or date.today()
    # La liste change au plus une fois par jour : on évite de la retélécharger à chaque appel
    if time.time() - _liste[0] > 3600 or aujourdhui != date.today():
        _liste = (time.time(), parser_liste(_get(LISTE).text))
    return [
        c for c in _liste[1]
        if (not c.fin or c.fin >= aujourdhui) and not any(mot in c.titre.lower() + " " for mot in EXCLUS)
    ]


def pages(catalogue_id: int) -> list[tuple[bytes, str]]:
    html = _get(f"{SITE}/regardez/offres/catalogue-carrefour-{catalogue_id}").text
    with ThreadPoolExecutor(max_workers=8) as pool:
        images = list(pool.map(lambda url: alleger(_get(url).content), parser_pages(html)))
    return [(image, "image/jpeg") for image in images]


def alleger(image: bytes) -> bytes:
    # Pages plus légères pour en envoyer des dizaines dans une seule requête Gemini (limite ~20 Mo)
    im = Image.open(io.BytesIO(image)).convert("RGB")
    im.thumbnail((900, 1500))
    sortie = io.BytesIO()
    im.save(sortie, "JPEG", quality=70)
    return sortie.getvalue()


_verrou = threading.Lock()


def est_en_cache(catalogue: Catalogue) -> bool:
    return (CACHE / f"{catalogue.id}.json").exists()


def offres_en_cache(catalogue: Catalogue) -> list[Offre]:
    return Extraction.model_validate_json((CACHE / f"{catalogue.id}.json").read_text()).offres


def lire_avec_cache(catalogue: Catalogue, lire) -> list[Offre]:
    """Un catalogue ne change pas : on ne le fait lire qu'une fois par l'IA.

    lire(catalogue) -> (Extraction, complet). Une lecture incomplète n'est pas mise en cache, pour être reprise.
    Le verrou évite de lire deux fois le même catalogue (lecture de fond + clic sur le bouton).
    """
    with _verrou:
        fichier = CACHE / f"{catalogue.id}.json"
        if fichier.exists():
            return Extraction.model_validate_json(fichier.read_text()).offres
        extraction, complet = lire(catalogue)
        if complet:
            CACHE.mkdir(parents=True, exist_ok=True)
            fichier.write_text(extraction.model_dump_json())
        return extraction.offres
