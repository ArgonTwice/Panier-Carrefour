import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import catalogues, ia
from .catalogues import Catalogue
from .models import DemandePanier, Extraction, Offre, Panier

TYPES_IMAGE = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}
MAX_CAPTURES = 10

log = logging.getLogger("uvicorn.error")


lecture = {"en_cours": False, "erreur": None}


def lire_en_fond():
    """Lit un à un les catalogues pas encore en cache ; s'arrête net si le quota du jour est atteint."""
    try:
        for c in catalogues.catalogues_en_cours():
            catalogues.lire_avec_cache(c, lambda c: ia.lire_catalogue(c, catalogues.pages(c.id)))
        lecture["erreur"] = None
        log.info("Catalogues de la semaine lus")
    except ia.QuotaEpuise as e:
        lecture["erreur"] = str(e)
        log.warning("%s", e)
    except Exception as e:
        lecture["erreur"] = f"Lecture des catalogues interrompue : {e}"[:300]
        log.exception("Lecture des catalogues en arrière-plan impossible")
    finally:
        lecture["en_cours"] = False


def relancer_lecture():
    if not lecture["en_cours"]:
        lecture["en_cours"] = True
        threading.Thread(target=lire_en_fond, daemon=True).start()


@asynccontextmanager
async def lifespan(app):
    # Les catalogues sont lus dès le lancement, pendant que l'utilisateur écrit ses besoins
    relancer_lecture()
    yield


app = FastAPI(title="Panier Carrefour", lifespan=lifespan)


@app.exception_handler(Exception)
async def erreur(request: Request, exc: Exception):
    log.exception("Erreur sur %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__} : {str(exc)[:300]}"})


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
    """Promos des catalogues déjà lus, sans attendre les autres : leur lecture continue en arrière-plan."""
    lus = [c for c in catalogues.catalogues_en_cours() if catalogues.est_en_cache(c)]
    relancer_lecture()
    return PromosSemaine(catalogues=lus, offres=[o for c in lus for o in catalogues.offres_en_cache(c)])


@app.get("/api/progression")
def progression() -> dict:
    en_cours = catalogues.catalogues_en_cours()
    return {"lus": sum(catalogues.est_en_cache(c) for c in en_cours), "total": len(en_cours),
            "en_cours": lecture["en_cours"], "erreur": lecture["erreur"]}


@app.post("/api/panier")
def panier(demande: DemandePanier) -> Panier:
    if not demande.offres:
        raise HTTPException(400, "Aucune offre trouvée")
    return ia.composer_panier(demande)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
