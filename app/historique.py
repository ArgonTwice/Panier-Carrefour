import re
import unicodedata

from .models import Offre, Releve


def cle(produit: str, marque: str | None) -> str:
    texte = unicodedata.normalize("NFKD", f"{marque or ''} {produit}").encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", texte))


def annoter(offre: Offre, historique: list[Releve]) -> dict:
    """Ajoute à l'offre les prix relevés pour le même produit lors des catalogues précédents."""
    donnees = offre.model_dump(exclude_defaults=True)
    if offre.prix_euros is None:
        return donnees
    k = cle(offre.produit, offre.marque)
    # Un relevé du même catalogue (même date de fin) n'est pas un point de comparaison
    prix = [r.prix for r in historique if cle(r.produit, r.marque) == k and r.date_fin != offre.date_fin]
    if prix:
        donnees["prix_deja_vus"] = {"min": min(prix), "moyenne": round(sum(prix) / len(prix), 2), "releves": len(prix)}
    return donnees
