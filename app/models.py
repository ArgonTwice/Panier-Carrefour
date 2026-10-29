from typing import Literal

from pydantic import BaseModel, Field


class Offre(BaseModel):
    type: Literal["bon", "challenge", "promo"]
    produit: str = Field(description="Produit ou rayon concerné, tel qu'écrit sur la capture")
    marque: str | None
    remise_texte: str = Field(description="Texte exact de l'avantage, ex. '-30% sur le 2e', '2€ en cagnotte'")
    remise_euros: float | None = Field(description="Gain en € par achat si calculable, sinon null")
    seuil_achat: float | None = Field(description="Montant minimum d'achat en € si l'offre en impose un")
    conditions: str | None = Field(description="Conditions : quantité, enseigne, drive uniquement, etc.")
    date_fin: str | None = Field(description="Date de fin au format AAAA-MM-JJ si visible")


class Extraction(BaseModel):
    solde_cagnotte: float | None = Field(description="Solde de la cagnotte en € s'il est visible")
    offres: list[Offre]


class LignePanier(BaseModel):
    produit: str
    quantite: int
    prix_estime: float | None = Field(description="Prix total estimé de la ligne en €, après remise")
    economie_estimee: float = Field(description="Économie estimée en € pour la ligne, 0 si aucune")
    offres_utilisees: list[str] = Field(description="remise_texte des offres utilisées")
    besoin: bool = Field(description="true si la ligne répond à un besoin listé, false si c'est une opportunité")
    raison: str


class PropositionPanier(BaseModel):
    lignes: list[LignePanier]
    a_faire: list[str] = Field(description="Actions avant les courses : bons à activer, challenges à valider")
    offres_ecartees: list[str] = Field(description="Offres jugées pas rentables, avec la raison en quelques mots")


class Panier(PropositionPanier):
    total_estime: float
    economie_totale: float
    hors_budget: bool


class DemandePanier(BaseModel):
    besoins: list[str]
    budget: float | None = None
    offres: list[Offre]
    solde_cagnotte: float | None = None
