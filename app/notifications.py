"""Notifications sur le téléphone (Web Push), sans compte ni appli à installer en plus.

Les clés VAPID sont créées au premier usage et gardées dans le stockage : rien à configurer.
"""
import base64
import json
import logging

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02
from pywebpush import WebPushException, webpush

from . import stockage

log = logging.getLogger("uvicorn.error")
CONTACT = {"sub": "mailto:panier-carrefour@users.noreply.github.com"}


def _vapid() -> Vapid02:
    pem = stockage.lire("vapid")
    if pem:
        return Vapid02.from_pem(pem.encode())
    vapid = Vapid02()
    vapid.generate_keys()
    stockage.ecrire("vapid", vapid.private_pem().decode())
    return vapid


def cle_publique() -> str:
    brut = _vapid().public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(brut).rstrip(b"=").decode()


def _abonnements() -> list[dict]:
    return json.loads(stockage.lire("abonnements") or "[]")


def abonner(abonnement: dict) -> None:
    autres = [a for a in _abonnements() if a.get("endpoint") != abonnement.get("endpoint")]
    stockage.ecrire("abonnements", json.dumps(autres + [abonnement]))


def envoyer(titre: str, texte: str) -> int:
    """Envoie à tous les appareils abonnés ; renvoie le nombre d'envois réussis."""
    abonnements, gardes, envoyes = _abonnements(), [], 0
    if not abonnements:
        return 0
    vapid = _vapid()
    for a in abonnements:
        try:
            webpush(a, json.dumps({"titre": titre, "texte": texte}), vapid_private_key=vapid,
                    vapid_claims=dict(CONTACT), timeout=15, ttl=86400)
            envoyes += 1
        except WebPushException as e:
            # 404/410 : notifications désactivées sur cet appareil, l'abonnement est retiré
            if e.response is not None and e.response.status_code in (404, 410):
                continue
            log.warning("Notification non envoyée : %s", e)
        gardes.append(a)
    if len(gardes) != len(abonnements):
        stockage.ecrire("abonnements", json.dumps(gardes))
    return envoyes
