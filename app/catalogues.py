"""Catalogues Carrefour publiés sur promocatalogues.fr (pages du catalogue en images)."""
import json
import re
from datetime import date, datetime

import httpx
from pydantic import BaseModel

SITE = "https://www.promocatalogues.fr"
CDN = "https://img.offers-cdn.net"
LISTE = f"{SITE}/magasins/carrefour/catalogues-promotions"
# Catalogues hors courses alimentaires ou d'autres régions, inutiles pour le Carrefour de Givors (hyper, Rhône).
# promocatalogues.fr ne filtre pas par magasin : la page de Givors liste les mêmes catalogues que la liste nationale.
EXCLUS = ("bretagne", "alsace", "bredele", "jouets", "voyages", "energies", "tex ", "culture", "sorties")
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


def catalogues_en_cours(aujourdhui: date | None = None) -> list[Catalogue]:
    aujourdhui = aujourdhui or date.today()
    return [
        c for c in parser_liste(_get(LISTE).text)
        if (not c.fin or c.fin >= aujourdhui) and not any(mot in c.titre.lower() + " " for mot in EXCLUS)
    ]


def pages(catalogue_id: int) -> list[tuple[bytes, str]]:
    html = _get(f"{SITE}/regardez/offres/catalogue-carrefour-{catalogue_id}").text
    return [(_get(url).content, "image/jpeg") for url in parser_pages(html)]
