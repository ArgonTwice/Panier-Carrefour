from typing import Literal

from pydantic import BaseModel, Field


class Palier(BaseModel):
    achat_euros: float = Field(description="Montant d'achats à atteindre, ex. 3 pour '3 €'")
    gain_euros: float = Field(description="Gain à ce palier, ex. 0.5 pour 'Je gagne 0,50€'")


class Offre(BaseModel):
    type: Literal["bon", "challenge", "promo", "avantage"]
    produit: str = Field(description="Produit, marque ou rayon concerné, tel qu'écrit sur la capture")
    marque: str | None
    remise_texte: str = Field(description="Texte exact de l'avantage, ex. '2 ACHETÉS = 0,60 € D'ÉCONOMIES'")
    remise_euros: float | None = Field(description="Remise fixe en € si l'offre en donne une")
    prix_euros: float | None = Field(default=None, description="Prix affiché en € (après promo) si visible")
    pourcentage: float | None = Field(default=None, description="Remise en %, ex. 15 pour '-15%'")
    quantite_requise: int | None = Field(default=None, description="Nombre de produits à acheter, ex. 2 pour '2 ACHETÉS'")
    seuil_achat: float | None = Field(description="Montant minimum d'achat en € si l'offre en impose un")
    paliers: list[Palier] = Field(default=[], description="Paliers d'un challenge, dans l'ordre")
    deja_achete: float | None = Field(default=None, description="Challenge : montant 'Mes achats' déjà réalisé en €")
    active: bool | None = Field(default=None, description="true si 'Activé', false si bouton 'Activer' visible, sinon null")
    canal: Literal["magasin", "drive", "tous"] | None = Field(
        default=None, description="'magasin' (onglet En magasin), 'drive' (Drive & Livraison), 'tous' si les deux")
    jour: str | None = Field(default=None, description="Jour de validité si l'offre est liée à un jour, ex. 'mercredi'")
    versement: Literal["immediat", "cagnotte"] | None = Field(
        default=None, description="'immediat' si remise en caisse, 'cagnotte' si crédité sur le compte fidélité")
    conditions: str | None = Field(description="Conditions : hors promotions, exclusions, etc.")
    date_fin: str | None = Field(description="Date de fin au format AAAA-MM-JJ si visible")


class Extraction(BaseModel):
    solde_cagnotte: float | None = Field(description="Solde de la cagnotte en € s'il est visible")
    offres: list[Offre]


class PromoCatalogue(BaseModel):
    """Format court pour lire un catalogue entier en une requête (le palier gratuit de Gemini est limité par jour)."""
    produit: str
    marque: str | None
    promo: str = Field(description="Texte exact de la promo, ex. '2ème à -60%', '34% d'économies avec la carte'")
    prix: float | None = Field(description="Prix affiché en €, null si absent")


class LectureCatalogue(BaseModel):
    promos: list[PromoCatalogue]


class LignePanier(BaseModel):
    produit: str
    quantite: int
    prix_estime: float | None = Field(description="Prix total estimé de la ligne en €, après remise")
    economie_estimee: float = Field(description="Économie estimée en € pour la ligne, 0 si aucune")
    dont_cagnotte: float = Field(default=0, description="Part de economie_estimee créditée en cagnotte, en €")
    offres_utilisees: list[str] = Field(description="remise_texte des offres utilisées")
    canal: Literal["magasin", "drive"] = Field(default="magasin", description="Où acheter ce produit")
    besoin: bool = Field(description="true si la ligne répond à un besoin listé, false si c'est une opportunité")
    raison: str


class PropositionPanier(BaseModel):
    quand_commander: str = Field(default="", description="Jour et canal conseillés (magasin, drive), avec la raison")
    lignes: list[LignePanier]
    a_faire: list[str] = Field(description="Actions avant les courses : bons à activer, challenges à valider")
    offres_ecartees: list[str] = Field(description="Offres jugées pas rentables, avec la raison en quelques mots")


class Panier(PropositionPanier):
    total_estime: float
    economie_totale: float
    economie_cagnotte: float
    hors_budget: bool


class Releve(BaseModel):
    produit: str
    marque: str | None = None
    prix: float
    date_fin: str | None = None


class DemandePanier(BaseModel):
    besoins: list[str]
    budget: float | None = None
    offres: list[Offre]
    solde_cagnotte: float | None = None
    carte_pass: bool = True
    canal: Literal["magasin", "drive", "les_deux"] = "les_deux"
    habituels: list[str] = []
    stock: list[str] = []
    historique: list[Releve] = []
