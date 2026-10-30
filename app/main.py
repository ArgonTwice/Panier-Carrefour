import base64
import json
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auto, catalogues, ia, notifications, stockage
from .catalogues import Catalogue
from .models import DemandePanier, Extraction, LectureTicket, Offre, Panier

TYPES_IMAGE = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}
TYPES_VIDEO = {"video/mp4", "video/quicktime", "video/webm", "video/3gpp", "video/x-matroska"}
MAX_CAPTURES = 60

log = logging.getLogger("uvicorn.error")
# Affiche chaque requête HTTP vers Gemini et ses réessais (429, 503) dans la fenêtre noire
logging.basicConfig(level=logging.WARNING, format="%(levelname)s:     %(message)s")
for nom in ("httpx", "google_genai"):
    logging.getLogger(nom).setLevel(logging.INFO)


lecture = {"en_cours": False, "erreur": None, "catalogue": None}


def lire_en_fond():
    """Lit un à un les catalogues pas encore en cache ; s'arrête net si le quota du jour est atteint."""
    try:
        en_cours = catalogues.catalogues_en_cours()
        catalogues.purger(en_cours)
        for c in en_cours:
            if catalogues.est_en_cache(c):
                continue
            lecture["catalogue"] = c.titre
            log.info("Lecture du catalogue %s…", c.titre)
            debut = time.monotonic()
            offres = catalogues.lire_avec_cache(c, lambda c: ia.lire_catalogue(c, catalogues.pages(c.id)))
            log.info("%s : %d promos lues en %.0f s", c.titre, len(offres), time.monotonic() - debut)
        lecture["erreur"] = None
        log.info("Catalogues de la semaine lus")
        try:
            auto.panier_de_la_semaine(en_cours)
        except Exception:
            log.exception("Panier automatique impossible")
    except ia.QuotaEpuise as e:
        lecture["erreur"] = str(e)
        log.warning("%s", e)
    except Exception as e:
        lecture["erreur"] = f"Lecture des catalogues interrompue : {e}"[:300]
        log.exception("Lecture des catalogues en arrière-plan impossible")
    finally:
        lecture["en_cours"] = False
        lecture["catalogue"] = None


def relancer_lecture():
    if not lecture["en_cours"]:
        lecture["en_cours"] = True
        threading.Thread(target=lire_en_fond, daemon=True).start()


def reveiller():
    """Au lancement et à chaque réveil planifié : rappel des bons, lecture des catalogues puis panier du mardi."""
    try:
        auto.rappeler_bons()
    except Exception:
        log.exception("Rappel des bons impossible")
    relancer_lecture()


@asynccontextmanager
async def lifespan(app):
    # Les catalogues sont lus dès le lancement, pendant que l'utilisateur écrit ses besoins
    threading.Thread(target=reveiller, daemon=True).start()
    yield


app = FastAPI(title="Panier Carrefour", lifespan=lifespan)


def _autorise(request: Request) -> bool:
    # En ligne, APP_MOT_DE_PASSE protège l'appli (et donc la clé Gemini) ; en local il n'est pas défini
    attendu = os.environ.get("APP_MOT_DE_PASSE")
    if not attendu:
        return True
    try:
        _, mot_de_passe = base64.b64decode(request.headers["authorization"].removeprefix("Basic ")).decode().split(":", 1)
    except (KeyError, ValueError):
        return False
    return secrets.compare_digest(mot_de_passe.encode(), attendu.encode())


@app.middleware("http")
async def sans_cache(request: Request, suite):
    # Le réveil planifié (GitHub Actions) n'a pas le mot de passe : il ne renvoie aucune donnée
    if request.url.path != "/api/reveil" and not _autorise(request):
        return Response("Mot de passe requis", status_code=401, headers={"WWW-Authenticate": 'Basic realm="Panier"'})
    # Le navigateur recharge toujours la page : une mise à jour de l'appli est prise en compte tout de suite
    reponse = await suite(request)
    reponse.headers["Cache-Control"] = "no-store"
    return reponse


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
        if c.content_type not in TYPES_IMAGE | TYPES_VIDEO:
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
            "en_cours": lecture["en_cours"], "erreur": lecture["erreur"], "catalogue": lecture["catalogue"]}


@app.post("/api/panier")
def panier(demande: DemandePanier) -> Panier:
    # Sans catalogue lu ni offre perso, le panier s'appuie quand même sur les avantages carte PASS
    if not demande.offres and not demande.carte_pass:
        raise HTTPException(400, "Aucune offre trouvée")
    return ia.composer_panier(demande)


@app.post("/api/ticket")
async def ticket(photos: list[UploadFile], challenges: str = Form("[]")) -> LectureTicket:
    if not 0 < len(photos) <= 10:
        raise HTTPException(400, "Entre 1 et 10 photos du ticket")
    images = []
    for f in photos:
        if f.content_type not in TYPES_IMAGE:
            raise HTTPException(400, f"{f.filename} : prends une photo du ticket")
        images.append((await f.read(), f.content_type))
    return ia.lire_ticket(images, [Offre.model_validate(c) for c in json.loads(challenges)])


@app.get("/api/reveil")
def reveil() -> dict:
    threading.Thread(target=reveiller, daemon=True).start()
    return {"ok": True}


@app.get("/api/notifications")
def cle_notifications() -> dict:
    return {"cle": notifications.cle_publique()}


@app.post("/api/notifications")
def abonner(abonnement: dict) -> dict:
    notifications.abonner(abonnement)
    return {"ok": True}


@app.post("/api/notifications/essai")
def essai_notification() -> dict:
    return {"envoyes": notifications.envoyer("🛒 Panier Carrefour", "Les notifications marchent sur cet appareil")}


@app.get("/api/etat")
def lire_etat() -> dict:
    """Bons, besoins et historique : enregistrés côté serveur pour être les mêmes sur le PC et le téléphone."""
    return {"etat": json.loads(stockage.lire("etat") or "null")}


@app.put("/api/etat")
def ecrire_etat(etat: dict) -> dict:
    stockage.ecrire("etat", json.dumps(etat, ensure_ascii=False))
    return {"ok": True}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
