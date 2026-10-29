from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import catalogues, ia
from .catalogues import Catalogue
from .models import DemandePanier, Extraction, Offre, Panier

TYPES_IMAGE = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}
MAX_CAPTURES = 10

app = FastAPI(title="Panier Carrefour")


@app.post("/api/extraction")
async def extraction(captures: list[UploadFile]) -> Extraction:
    if not 0 < len(captures) <= MAX_CAPTURES:
        raise HTTPException(400, f"Entre 1 et {MAX_CAPTURES} captures")
    images = []
    for c in captures:
        if c.content_type not in TYPES_IMAGE:
            raise HTTPException(400, f"{c.filename} : format non supporté")
        images.append((await c.read(), c.content_type))
    return ia.extraire_offres(images)


class PromosSemaine(BaseModel):
    catalogues: list[Catalogue]
    offres: list[Offre]


@app.post("/api/promos-semaine")
def promos_semaine() -> PromosSemaine:
    """Promos de tous les catalogues en cours ; seuls les nouveaux catalogues sont lus par l'IA."""
    en_cours = catalogues.catalogues_en_cours()
    offres = [
        o for c in en_cours
        for o in catalogues.lire_avec_cache(c, lambda c: ia.lire_catalogue(c, catalogues.pages(c.id)))
    ]
    return PromosSemaine(catalogues=en_cours, offres=offres)


@app.post("/api/panier")
def panier(demande: DemandePanier) -> Panier:
    if not demande.offres:
        raise HTTPException(400, "Aucune offre trouvée")
    return ia.composer_panier(demande)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
