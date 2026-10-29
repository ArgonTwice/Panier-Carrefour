import os
from concurrent.futures import ThreadPoolExecutor

from google import genai
from google.genai import types

from .avantages import AVANTAGES_PASS
from .catalogues import Catalogue
from .models import DemandePanier, Extraction, Panier, PropositionPanier

MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

PROMPT_EXTRACTION = """Ces captures viennent de l'appli Carrefour d'un client qui a la carte PASS et le Club Carrefour.
Liste chaque offre visible, une seule fois même si elle apparaît sur plusieurs captures.

Repères pour classer les offres :
- "bon" : coupon à activer ("1 ACHETÉ = 0,40 € DE REMISE", "2 ACHETÉS = 0,60 € D'ÉCONOMIES"). active=true si "Activé",
  false si un bouton "Activer" est visible. Onglet "En magasin" -> canal "magasin", "Drive & Livraison" -> "drive".
  "DE REMISE" -> versement "immediat" ; "D'ÉCONOMIES" avec le logo Club -> versement "cagnotte".
- "challenge" : Challenge Fid' avec paliers "Je gagne X€" pour "Mes achats" de Y€ ; deja_achete = montant "Mes achats".
  Un challenge "Gagnez jusqu'à X€" avec bouton "Activer ce challenge !" n'est pas activé (active=false).
  Les gains de challenge vont dans la cagnotte.
- "avantage" : remise permanente ou récurrente du Club ("-15% sur les fruits et légumes", "Les mercredis des produits frais").
- "promo" : promotion produit ou catalogue avec prix ("Le 2ème à -60%", "Prenez en 3 = Payez en 2").
Le solde de la cagnotte est affiché "Votre cagnotte".
N'invente rien : un champ illisible ou absent vaut null."""

PROMPT_CATALOGUE = """Ces images sont des pages du catalogue Carrefour "{titre}", valable du {debut} au {fin}.
Liste chaque produit en promotion : type "promo", produit, marque, texte exact de la promo, prix affiché après remise,
remise en € ou en %, quantité requise ("2 achetés", "le 2ème à -60%"), conditions ("avec la carte", "en magasin uniquement").
date_fin = {fin}. Ignore les pages sans offre (couverture, mentions légales).
N'invente rien : un champ illisible ou absent vaut null."""

PROMPT_PANIER = """Tu composes le panier de courses Carrefour de la semaine pour un client qui a la carte PASS et le Club Carrefour.

Besoins : {besoins}
Budget : {budget}
Cagnotte disponible : {cagnotte}

Offres disponibles (JSON) :
{offres}

Règles :
- Couvre d'abord les besoins, en choisissant pour chacun l'offre ou la combinaison la plus rentable.
- Cumul : un bon se cumule avec une promo sur le même produit, sauf mention contraire. Les avantages Club marqués
  "hors promotions en cours" ne se cumulent pas avec une promo : garde le plus intéressant des deux.
- Respecte la quantité requise, les seuils d'achat, le canal (magasin ou drive) et le jour imposé par chaque offre.
  Si une offre impose un jour (ex. mercredi en drive), dis-le dans a_faire.
- Bons et challenges dont active=false : s'ils servent au panier, ajoute dans a_faire de les activer.
- Challenges : pour chacun, calcule ce qu'il reste à acheter avant le prochain palier (achat_euros - deja_achete).
  Pousse un challenge seulement si les produits sont utiles ou se conservent et que le gain du palier vaut le surcoût.
  Les gains de challenge arrivent dans la cagnotte le mois suivant.
- Ajoute une opportunité hors besoins seulement si l'économie est forte et le produit se conserve.
- Une promo n'est pas rentable si elle pousse à acheter plus que nécessaire pour un produit périssable.
- Dans economie_estimee, compte aussi ce qui est crédité en cagnotte, et précise-le dans la raison.
- Les prix sont des estimations : mets null si tu n'as aucune base pour estimer."""


def _parse(contents, schema):
    # Clé lue dans GEMINI_API_KEY par le SDK
    reponse = genai.Client().models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema),
    )
    if not reponse.text:
        raise RuntimeError("Réponse vide du modèle")
    return schema.model_validate_json(reponse.text)


def extraire_offres(images: list[tuple[bytes, str]]) -> Extraction:
    return _parse([*_parts(images), PROMPT_EXTRACTION], Extraction)


def _parts(images: list[tuple[bytes, str]]) -> list[types.Part]:
    return [types.Part.from_bytes(data=data, mime_type=media_type) for data, media_type in images]


def lire_catalogue(catalogue: Catalogue, pages: list[tuple[bytes, str]], par_appel: int = 10) -> Extraction:
    prompt = PROMPT_CATALOGUE.format(titre=catalogue.titre, debut=catalogue.debut, fin=catalogue.fin)
    lots = [pages[i:i + par_appel] for i in range(0, len(pages), par_appel)]
    # Quelques appels en parallèle : un catalogue fait souvent 50 à 80 pages
    with ThreadPoolExecutor(max_workers=4) as pool:
        extractions = list(pool.map(lambda lot: _parse([*_parts(lot), prompt], Extraction), lots))
    return Extraction(solde_cagnotte=None, offres=[o for e in extractions for o in e.offres])


def composer_panier(demande: DemandePanier) -> Panier:
    offres = demande.offres + (AVANTAGES_PASS if demande.carte_pass else [])
    prompt = PROMPT_PANIER.format(
        besoins=", ".join(demande.besoins) or "aucun précisé",
        budget=f"{demande.budget} €" if demande.budget else "non précisé",
        cagnotte=f"{demande.solde_cagnotte} €" if demande.solde_cagnotte else "inconnue",
        offres="[" + ",".join(o.model_dump_json(exclude_defaults=True) for o in offres) + "]",
    )
    return totaliser(_parse(prompt, PropositionPanier), demande.budget)


def totaliser(proposition: PropositionPanier, budget: float | None) -> Panier:
    # Totaux recalculés ici plutôt que confiés au modèle
    total = round(sum(l.prix_estime or 0 for l in proposition.lignes), 2)
    return Panier(
        **proposition.model_dump(),
        total_estime=total,
        economie_totale=round(sum(l.economie_estimee for l in proposition.lignes), 2),
        hors_budget=budget is not None and total > budget,
    )
