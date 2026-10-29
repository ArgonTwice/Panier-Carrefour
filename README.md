# Panier Carrefour

Appli perso qui compose un panier de courses optimisé à partir des promos, bons de réduction, challenges et de la cagnotte Carrefour.

Il n'y a aucune connexion au compte Carrefour et aucun identifiant n'est stocké. Les offres perso sont lues sur des **captures d'écran** de l'appli Carrefour.

## Fonctionnement

1. Tu importes 2 à 4 captures (bons, challenges, cagnotte, promos). Gemini en extrait les offres.
2. Tu saisis tes besoins de la semaine et ton budget.
3. Gemini compose le panier. Les totaux sont recalculés côté serveur.

Les offres, les besoins et le budget restent dans le navigateur (localStorage).

## Lancer

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export GEMINI_API_KEY=...   # clé sur https://aistudio.google.com/apikey
# optionnel : export GEMINI_MODEL=gemini-flash-latest
uvicorn app.main:app --reload
```

Puis ouvre http://127.0.0.1:8000.

## Tests

```bash
pytest
```
