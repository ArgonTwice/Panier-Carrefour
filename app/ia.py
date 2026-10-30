import json
import logging
import os
import threading
import time

import httpx

from google import genai
from google.genai import types

from .avantages import AVANTAGES_PASS
from .catalogues import Catalogue
from .historique import annoter
from .models import DemandePanier, Extraction, LectureCatalogue, Offre, Panier, PropositionPanier

log = logging.getLogger("uvicorn.error")

MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
# Le palier gratuit limite les requêtes par minute : on réessaie au lieu d'échouer
RETRY = types.HttpOptions(retry_options=types.HttpRetryOptions(
    attempts=3, initial_delay=10, max_delay=40, http_status_codes=[429, 500, 503]))


class QuotaEpuise(RuntimeError):
    """Quota journalier de Gemini atteint : inutile de réessayer avant le lendemain."""


def _quota_journalier(e: Exception) -> bool:
    return "RESOURCE_EXHAUSTED" in str(e) and "PerDay" in str(e)

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

PROMPT_CATALOGUE = """Ces images sont les pages du catalogue Carrefour "{titre}", valable du {debut} au {fin}.
Liste chaque produit en promotion, une ligne par produit : produit, marque, texte exact de la promo
(ex. "2ème à -60%", "34% d'économies avec la carte", "Prenez-en 3, payez-en 2") et prix affiché.
Ignore les pages sans offre (couverture, mentions légales). N'invente rien : ce qui est illisible vaut null."""


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


_instance = None
_verrou = threading.Lock()


def _client() -> genai.Client:
    # Un seul client partagé : un client temporaire peut être fermé par le ramasse-miettes en pleine requête
    global _instance
    with _verrou:
        if _instance is None:
            _instance = genai.Client(http_options=RETRY)
        return _instance


def _parse(contents, schema, reflexion=types.ThinkingLevel.LOW, delai=120):
    # Clé lue dans GEMINI_API_KEY par le SDK. Réflexion réduite et délai max : sans eux un appel peut durer des minutes
    debut = time.monotonic()
    try:
        reponse = _client().models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=schema, max_output_tokens=65536,
                thinking_config=types.ThinkingConfig(thinking_level=reflexion),
                http_options=types.HttpOptions(timeout=delai * 1000, retry_options=RETRY.retry_options)),
        )
    except httpx.TimeoutException as e:
        raise RuntimeError(f"Gemini n'a pas répondu en {delai} s, réessaie dans un moment") from e
    except Exception as e:
        if _quota_journalier(e):
            raise QuotaEpuise("Quota gratuit de Gemini atteint pour aujourd'hui : réessaie demain") from e
        raise
    fin = reponse.candidates[0].finish_reason if reponse.candidates else None
    if fin == types.FinishReason.MAX_TOKENS:
        raise RuntimeError("Réponse de Gemini tronquée (trop d'offres d'un coup)")
    if not reponse.text:
        raise RuntimeError(f"Réponse vide de Gemini ({fin})")
    log.info("Gemini : %s en %.0f s", schema.__name__, time.monotonic() - debut)
    return schema.model_validate_json(reponse.text)


def extraire_offres(images: list[tuple[bytes, str]]) -> Extraction:
    return _parse([*_parts(images), PROMPT_EXTRACTION], Extraction)


def _parts(images: list[tuple[bytes, str]]) -> list[types.Part]:
    return [types.Part.from_bytes(data=data, mime_type=media_type) for data, media_type in images]


def lire_catalogue(catalogue: Catalogue, pages: list[tuple[bytes, str]], par_appel: int = 50) -> tuple[Extraction, bool]:
    """Lit le catalogue en une ou deux requêtes (format court). Renvoie (extraction, complet)."""
    prompt = PROMPT_CATALOGUE.format(titre=catalogue.titre, debut=catalogue.debut, fin=catalogue.fin)
    offres, complet = [], True
    for i in range(0, len(pages), par_appel):
        try:
            # Simple recopie des pages : réflexion minimale, mais beaucoup de texte à écrire
            lecture = _parse([*_parts(pages[i:i + par_appel]), prompt], LectureCatalogue,
                             reflexion=types.ThinkingLevel.MINIMAL, delai=300)
        except QuotaEpuise:
            raise
        except Exception as e:
            log.warning("Catalogue %s : pages %s+ ignorées (%s)", catalogue.id, i + 1, e)
            complet = False
            continue
        offres += [
            Offre(type="promo", produit=p.produit, marque=p.marque, remise_texte=p.promo, remise_euros=None,
                  prix_euros=p.prix, seuil_achat=None, conditions=None,
                  date_fin=str(catalogue.fin) if catalogue.fin else None)
            for p in lecture.promos
        ]
    if not offres and not complet:
        raise RuntimeError(f"Lecture du catalogue {catalogue.titre} impossible")
    return Extraction(solde_cagnotte=None, offres=offres), complet


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
