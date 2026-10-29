from .models import Offre

# Avantages permanents du Club Carrefour avec la carte PASS (relevés dans l'appli en octobre 2026).
# Ajoutés d'office au calcul du panier, sans avoir à les capturer chaque semaine.
AVANTAGES_PASS = [
    Offre(type="avantage", produit="Fruits et légumes", marque=None, remise_texte="-15% tous les jours avec la carte PASS",
          remise_euros=None, pourcentage=15, seuil_achat=None, canal="tous", versement="cagnotte",
          conditions="Hors promotions en cours", date_fin=None),
    Offre(type="avantage", produit="Produits Carrefour Bio", marque="Carrefour Bio",
          remise_texte="-15% tous les jours avec la carte PASS", remise_euros=None, pourcentage=15, seuil_achat=None,
          canal="tous", versement="cagnotte", conditions="Hors promotions en cours", date_fin=None),
    Offre(type="avantage", produit="Produits de marque Carrefour", marque="Carrefour",
          remise_texte="-15% un jour par semaine avec la carte PASS", remise_euros=None, pourcentage=15,
          seuil_achat=None, canal="drive", conditions="Un jour par semaine, en drive ou livraison", date_fin=None),
    Offre(type="avantage", produit="Rayon frais de la semaine", marque=None,
          remise_texte="Les mercredis des produits frais : 34% d'économies", remise_euros=None, pourcentage=34,
          seuil_achat=None, canal="drive", jour="mercredi",
          conditions="Commande passée le mercredi en drive ; rayon et montant minimum changent chaque semaine",
          date_fin=None),
    Offre(type="avantage", produit="Univers bébé", marque=None, remise_texte="Les jeudis bébé : 15% d'économies",
          remise_euros=None, pourcentage=15, seuil_achat=None, canal="drive", jour="jeudi",
          conditions="Commande passée le jeudi, hors promotions Pampers", date_fin=None),
]
