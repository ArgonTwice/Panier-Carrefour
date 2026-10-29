from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from . import catalogues, ia
from .catalogues import Catalogue
from .models import DemandePanier, Extraction, Panier

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


@app.get("/api/catalogues")
def liste_catalogues() -> list[Catalogue]:
    return catalogues.catalogues_en_cours()


@app.post("/api/catalogues/{catalogue_id}/lecture")
def lecture_catalogue(catalogue_id: int) -> Extraction:
    catalogue = next((c for c in catalogues.catalogues_en_cours() if c.id == catalogue_id), None)
    if not catalogue:
        raise HTTPException(404, "Catalogue introuvable ou expiré")
    return ia.lire_catalogue(catalogue, catalogues.pages(catalogue_id))


@app.post("/api/panier")
def panier(demande: DemandePanier) -> Panier:
    if not demande.offres:
        raise HTTPException(400, "Aucune offre : importe d'abord tes captures")
    return ia.composer_panier(demande)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
