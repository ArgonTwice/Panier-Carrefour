from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from . import claude
from .models import DemandePanier, Extraction, Panier

TYPES_IMAGE = {"image/png", "image/jpeg", "image/webp", "image/gif"}
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
    return claude.extraire_offres(images)


@app.post("/api/panier")
def panier(demande: DemandePanier) -> Panier:
    if not demande.offres:
        raise HTTPException(400, "Aucune offre : importe d'abord tes captures")
    return claude.composer_panier(demande)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
