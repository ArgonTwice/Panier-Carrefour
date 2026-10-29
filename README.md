# Panier Carrefour

Appli perso qui compose un panier de courses optimisé à partir des promos, bons de réduction, challenges et de la cagnotte Carrefour.

Il n'y a aucune connexion au compte Carrefour et aucun identifiant n'est stocké. Les offres perso sont lues sur des **captures d'écran** de l'appli Carrefour.

## Fonctionnement

0. Les catalogues Carrefour en cours sont listés depuis promocatalogues.fr. Un clic sur « Lire » télécharge les pages et Gemini en extrait les promos.
1. Tu importes 2 à 4 captures (bons, challenges, cagnotte, promos). Gemini en extrait les offres.
2. Tu saisis tes besoins de la semaine et ton budget.
3. Gemini compose le panier. Les totaux sont recalculés côté serveur.

Les avantages permanents de la carte PASS (fruits et légumes, Carrefour Bio, mercredis frais, jeudis bébé…) sont ajoutés d'office au calcul, voir `app/avantages.py`. Les offres, les besoins et le budget restent dans le navigateur (localStorage).

## Lancer

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # puis colle ta clé (https://aistudio.google.com/apikey) dans .env
uvicorn app.main:app --reload --env-file .env
```

Puis ouvre http://127.0.0.1:8000.

## Tests

```bash
pytest
```
