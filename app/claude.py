import base64

import anthropic

from .models import DemandePanier, Extraction, Panier, PropositionPanier

MODEL = "claude-opus-5-5"

PROMPT_EXTRACTION = """Ces captures viennent de l'appli Carrefour d'un client (bons de réduction, challenges, promos, cagnotte).
Liste chaque offre visible, une seule fois même si elle apparaît sur plusieurs captures.
N'invente rien : un champ illisible ou absent vaut null."""

PROMPT_PANIER = """Tu composes le panier de courses Carrefour de la semaine pour un client.

Besoins : {besoins}
Budget : {budget}
Cagnotte disponible : {cagnotte}

Offres disponibles (JSON) :
{offres}

Règles :
- Couvre d'abord les besoins, en choisissant pour chacun l'offre la plus rentable.
- Ajoute une opportunité hors besoins seulement si l'économie est forte et le produit se conserve, ou si elle débloque un challenge dont le gain dépasse le surcoût.
- Respecte les seuils d'achat et les conditions des offres.
- Une promo n'est pas rentable si elle pousse à acheter plus que nécessaire pour un produit périssable.
- Les prix sont des estimations : mets null si tu n'as aucune base pour estimer."""


def _parse(content, output_format):
    reponse = anthropic.Anthropic().messages.parse(
        model=MODEL,
        max_tokens=16000,
        messages=[{"role": "user", "content": content}],
        output_format=output_format,
    )
    if reponse.stop_reason == "refusal":
        raise RuntimeError("Requête refusée par le modèle")
    return reponse.parsed_output


def extraire_offres(images: list[tuple[bytes, str]]) -> Extraction:
    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode()},
        }
        for data, media_type in images
    ]
    content.append({"type": "text", "text": PROMPT_EXTRACTION})
    return _parse(content, Extraction)


def composer_panier(demande: DemandePanier) -> Panier:
    prompt = PROMPT_PANIER.format(
        besoins=", ".join(demande.besoins) or "aucun précisé",
        budget=f"{demande.budget} €" if demande.budget else "non précisé",
        cagnotte=f"{demande.solde_cagnotte} €" if demande.solde_cagnotte else "inconnue",
        offres="[" + ",".join(o.model_dump_json() for o in demande.offres) + "]",
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
