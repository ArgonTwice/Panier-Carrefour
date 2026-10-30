import re
import unicodedata

from .models import Offre, Releve


def cle(produit: str, marque: str | None) -> str:
    texte = unicodedata.normalize("NFKD", f"{marque or ''} {produit}").encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", texte))


def progression(offre: Offre) -> dict | None:
    """Pour un challenge : palier atteint, prochain palier, reste à acheter et rendement de ce reste."""
    if offre.type != "challenge" or not offre.paliers:
        return None
    deja = offre.deja_achete or 0
    atteints = [p for p in offre.paliers if p.achat_euros <= deja]
    suivant = next((p for p in sorted(offre.paliers, key=lambda p: p.achat_euros) if p.achat_euros > deja), None)
    gain_actuel = max((p.gain_euros for p in atteints), default=0)
    if not suivant:
        return {"gain_acquis": gain_actuel, "termine": True}
    reste = round(suivant.achat_euros - deja, 2)
    return {
        "gain_acquis": gain_actuel,
        "reste_a_acheter": reste,
        "gain_au_prochain_palier": suivant.gain_euros,
        # Part des achats restants rendue en cagnotte : 30 % = 0,30 € gagnés par euro dépensé
        "rendement_pct": round((suivant.gain_euros - gain_actuel) / reste * 100) if reste > 0 else None,
    }


def annoter(offre: Offre, historique: list[Releve]) -> dict:
    """Ajoute à l'offre la progression d'un challenge et les prix déjà relevés pour le même produit."""
    donnees = offre.model_dump(exclude_defaults=True)
    if prog := progression(offre):
        donnees["progression"] = prog
    if offre.prix_euros is None:
        return donnees
    k = cle(offre.produit, offre.marque)
    # Un relevé du même catalogue (même date de fin) n'est pas un point de comparaison
    prix = [r.prix for r in historique if cle(r.produit, r.marque) == k and r.date_fin != offre.date_fin]
    if prix:
        donnees["prix_deja_vus"] = {"min": min(prix), "moyenne": round(sum(prix) / len(prix), 2), "releves": len(prix)}
    return donnees
