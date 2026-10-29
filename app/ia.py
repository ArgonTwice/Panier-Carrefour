import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from google import genai
from google.genai import types

from .avantages import AVANTAGES_PASS
from .catalogues import Catalogue
from .historique import annoter
from .models import DemandePanier, Extraction, Panier, PropositionPanier

log = logging.getLogger("uvicorn.error")

MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
# Le palier gratuit limite les requêtes par minute : on réessaie au lieu d'échouer
RETRY = types.HttpOptions(retry_options=types.HttpRetryOptions(
    attempts=6, initial_delay=5, max_delay=60, http_status_codes=[429, 500, 503]))

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

Besoins de la semaine : {besoins}
Produits achetés habituellement : {habituels}
Déjà en stock à la maison : {stock}
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
- Challenges : "progression" donne le reste à acheter avant le prochain palier et son rendement (rendement_pct = part
  du reste rendue en cagnotte). Un rendement de 20 % ou plus sur des produits utiles ou qui se conservent vaut le coup ;
  en dessous, ne pousse le challenge que si les achats étaient prévus. Les gains arrivent en cagnotte le mois suivant.
  Dans a_faire, indique pour chaque challenge à jouer le montant restant et le gain visé.
- Jour et canal : dans quand_commander, conseille quand et où faire les courses (magasin, ou drive un jour précis
  pour profiter d'une offre liée au jour). Si le panier gagne à être coupé en deux (ex. frais le mercredi en drive),
  dis-le, et ne le propose que si le gain dépasse quelques euros.
- Produits habituels absents des besoins : propose d'en faire le stock seulement s'ils se conservent et sont à un très
  bon prix. Ne propose rien de ce qui est déjà en stock, sauf affaire exceptionnelle sur un produit qui se conserve.
- prix_deja_vus donne les prix relevés pour ce produit dans les catalogues précédents. Si le prix actuel est au-dessus
  du min déjà vu, ce n'est pas une vraie bonne affaire : achète seulement le nécessaire et dis-le dans la raison.
  S'il est au niveau du min ou en dessous, c'est le bon moment pour faire le stock d'un produit qui se conserve.
- Ajoute une opportunité hors besoins et hors habituels seulement si l'économie est forte et le produit se conserve.
- Une promo n'est pas rentable si elle pousse à acheter plus que nécessaire pour un produit périssable.
- Dans economie_estimee, compte aussi ce qui est crédité en cagnotte, et mets cette part dans dont_cagnotte.
- Les prix sont des estimations : mets null si tu n'as aucune base pour estimer."""


def _parse(contents, schema):
    # Clé lue dans GEMINI_API_KEY par le SDK
    reponse = genai.Client(http_options=RETRY).models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=schema, max_output_tokens=65536),
    )
    fin = reponse.candidates[0].finish_reason if reponse.candidates else None
    if fin == types.FinishReason.MAX_TOKENS:
        raise RuntimeError("Réponse de Gemini tronquée (trop d'offres d'un coup)")
    if not reponse.text:
        raise RuntimeError(f"Réponse vide de Gemini ({fin})")
    return schema.model_validate_json(reponse.text)


def extraire_offres(images: list[tuple[bytes, str]]) -> Extraction:
    return _parse([*_parts(images), PROMPT_EXTRACTION], Extraction)


def _parts(images: list[tuple[bytes, str]]) -> list[types.Part]:
    return [types.Part.from_bytes(data=data, mime_type=media_type) for data, media_type in images]


def lire_catalogue(catalogue: Catalogue, pages: list[tuple[bytes, str]], par_appel: int = 5) -> tuple[Extraction, bool]:
    """Lit le catalogue par petits lots de pages ; un lot en échec est sauté. Renvoie (extraction, complet)."""
    prompt = PROMPT_CATALOGUE.format(titre=catalogue.titre, debut=catalogue.debut, fin=catalogue.fin)
    lots = [pages[i:i + par_appel] for i in range(0, len(pages), par_appel)]

    def lire_lot(lot):
        try:
            return _parse([*_parts(lot), prompt], Extraction)
        except Exception as e:
            log.warning("Catalogue %s : lot de pages ignoré (%s)", catalogue.id, e)
            return e

    with ThreadPoolExecutor(max_workers=4) as pool:
        resultats = list(pool.map(lire_lot, lots))
    echecs = [r for r in resultats if isinstance(r, Exception)]
    if lots and len(echecs) == len(lots):
        raise echecs[0]
    offres = [o for r in resultats if isinstance(r, Extraction) for o in r.offres]
    return Extraction(solde_cagnotte=None, offres=offres), not echecs


def composer_panier(demande: DemandePanier) -> Panier:
    offres = demande.offres + (AVANTAGES_PASS if demande.carte_pass else [])
    prompt = PROMPT_PANIER.format(
        besoins=", ".join(demande.besoins) or "aucun précisé",
        habituels=", ".join(demande.habituels) or "non précisés",
        stock=", ".join(demande.stock) or "non précisé",
        budget=f"{demande.budget} €" if demande.budget else "non précisé",
        cagnotte=f"{demande.solde_cagnotte} €" if demande.solde_cagnotte else "inconnue",
        offres=json.dumps([annoter(o, demande.historique) for o in offres], ensure_ascii=False),
    )
    return totaliser(_parse(prompt, PropositionPanier), demande.budget)


def totaliser(proposition: PropositionPanier, budget: float | None) -> Panier:
    # Totaux recalculés ici plutôt que confiés au modèle
    total = round(sum(l.prix_estime or 0 for l in proposition.lignes), 2)
    return Panier(
        **proposition.model_dump(),
        total_estime=total,
        economie_totale=round(sum(l.economie_estimee for l in proposition.lignes), 2),
        economie_cagnotte=round(sum(min(l.dont_cagnotte, l.economie_estimee) for l in proposition.lignes), 2),
        hors_budget=budget is not None and total > budget,
    )
