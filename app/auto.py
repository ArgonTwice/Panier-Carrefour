"""Ce que l'appli fait toute seule : panier préparé le mardi (sortie des catalogues) et rappel des bons qui expirent."""
import json
import logging
from datetime import date, timedelta

from . import catalogues, ia, notifications, stockage
from .historique import cle
from .models import DemandePanier, Offre, Releve

log = logging.getLogger("uvicorn.error")
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
DELAI_RAPPEL = 3  # jours


def mardi(aujourdhui: date) -> date:
    """Mardi de la semaine Carrefour en cours : les catalogues et le Mardi PASS commencent ce jour-là."""
    return aujourdhui - timedelta(days=(aujourdhui.weekday() - 1) % 7)


def _lignes(texte: str | None) -> list[str]:
    return [l.strip() for l in (texte or "").splitlines() if l.strip()]


def comme_d_habitude(habituels: list[str], stock: list[str]) -> list[str]:
    en_stock = {cle(s, None) for s in stock}
    return [h for h in habituels if cle(h, None) not in en_stock]


def _etat() -> dict:
    return json.loads(stockage.lire("etat") or "null") or {}


def _valides(modele, donnees: list) -> list:
    valides = []
    for d in donnees:
        try:
            valides.append(modele.model_validate(d))
        except ValueError:
            pass
    return valides


def panier_de_la_semaine(en_cours: list[catalogues.Catalogue], aujourdhui: date | None = None) -> bool:
    """Compose le panier une fois par semaine, dès que les nouveaux catalogues sont lus, puis prévient le téléphone."""
    aujourdhui = aujourdhui or date.today()
    semaine = mardi(aujourdhui)
    if stockage.lire("panier_auto") == semaine.isoformat():
        return False
    # Catalogues de la semaine pas encore publiés : on attend le prochain réveil plutôt que de reprendre les anciens
    if not any(c.debut and semaine - timedelta(days=1) <= c.debut <= aujourdhui for c in en_cours):
        return False
    sauvegarde = _etat()
    etat, champs = sauvegarde.get("etat") or {}, sauvegarde.get("champs") or {}
    habituels, stock = _lignes(champs.get("habituels")), _lignes(champs.get("stock"))
    besoins = _lignes(champs.get("besoins")) or comme_d_habitude(habituels, stock)
    if not besoins:
        return False  # rien à acheter connu : pas de panier ni de notification
    perso = [o for o in _valides(Offre, etat.get("offres") or []) if not o.date_fin or o.date_fin >= aujourdhui.isoformat()]
    demande = DemandePanier(
        besoins=besoins, habituels=habituels, stock=stock,
        budget=float(champs["budget"]) if champs.get("budget") else None,
        offres=perso + [o for c in en_cours if catalogues.est_en_cache(c) for o in catalogues.offres_en_cache(c)],
        solde_cagnotte=etat.get("solde_cagnotte"),
        canal=champs.get("canal") or "les_deux",
        historique=_valides(Releve, etat.get("historique") or []),
    )
    panier = ia.composer_panier(demande)
    # État relu après l'appel à Gemini (1 à 2 min) : une modification faite entre-temps sur le téléphone est gardée
    sauvegarde = _etat()
    sauvegarde.setdefault("etat", {})["panier"] = {**panier.model_dump(), "coches": [], "auto": aujourdhui.isoformat()}
    sauvegarde.setdefault("champs", champs)
    stockage.ecrire("etat", json.dumps(sauvegarde, ensure_ascii=False))
    stockage.ecrire("panier_auto", semaine.isoformat())
    log.info("Panier de la semaine préparé automatiquement")
    notifications.envoyer("🛒 Ton panier de la semaine est prêt",
                          f"{len(panier.lignes)} produits · {panier.total_estime:.2f} € · "
                          f"{panier.economie_totale:.2f} € d'économie")
    return True


def rappeler_bons(aujourdhui: date | None = None) -> list[str]:
    """Notifie une seule fois chaque bon qui expire dans 3 jours ou moins."""
    aujourdhui = aujourdhui or date.today()
    limite = (aujourdhui + timedelta(days=DELAI_RAPPEL)).isoformat()
    deja = set(json.loads(stockage.lire("rappels") or "[]"))
    bons = [o for o in _valides(Offre, (_etat().get("etat") or {}).get("offres") or [])
            if o.type == "bon" and o.date_fin and aujourdhui.isoformat() <= o.date_fin <= limite]
    nouveaux = [o for o in bons if f"{o.produit}|{o.remise_texte}|{o.date_fin}" not in deja]
    if not nouveaux:
        return []
    textes = [f"{o.produit} ({JOURS[date.fromisoformat(o.date_fin).weekday()]})" for o in nouveaux]
    if not notifications.envoyer(f"⏰ {len(nouveaux)} bon{'s' if len(nouveaux) > 1 else ''} expire"
                                 f"{'nt' if len(nouveaux) > 1 else ''} bientôt", ", ".join(textes)):
        return []  # aucun appareil prévenu : on réessaiera au prochain réveil
    # Seuls les rappels de bons encore valables sont gardés
    gardes = [k for k in deja if k.rsplit("|", 1)[-1] >= aujourdhui.isoformat()]
    stockage.ecrire("rappels", json.dumps(gardes + [f"{o.produit}|{o.remise_texte}|{o.date_fin}" for o in nouveaux]))
    return textes
