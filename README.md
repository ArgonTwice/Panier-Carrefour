# Panier Carrefour

Appli perso qui compose un panier de courses optimisé à partir des promos, bons de réduction, challenges et de la cagnotte Carrefour.

Il n'y a aucune connexion au compte Carrefour et aucun identifiant n'est stocké. Les offres perso sont lues sur des **captures d'écran** de l'appli Carrefour.

## Utilisation

**Windows :** double-clic sur `lancer.bat`. La première fois, il installe tout et ouvre le Bloc-notes pour coller la clé Gemini (https://aistudio.google.com/apikey). Ensuite, il met l'appli à jour et l'ouvre dans le navigateur.
**Mac / Linux :** `./lancer.sh`.

Dans l'appli :
1. Écris tes besoins, puis clique sur **Préparer mon panier**. Les catalogues Carrefour de la semaine (promocatalogues.fr) sont lus par Gemini, une seule fois chacun (cache dans `data/`), puis le panier est composé.
2. Quand tes bons ou tes challenges changent, choisis tes captures de l'appli Carrefour : elles sont analysées tout de suite, une offre recapturée remplace l'ancienne et les offres expirées disparaissent toutes seules.

Le calcul tient compte :
- des avantages permanents de la carte PASS (`app/avantages.py`) ;
- de la progression des Challenge Fid' (reste à acheter, rendement du prochain palier) ;
- de l'historique des prix relevés, pour repérer les fausses promos ;
- de ta liste habituelle et de ton stock (dans « Mes habitudes »).

Il te dit quand et où commander, et sépare l'économie en caisse de celle en cagnotte. Tout l'état perso reste dans le navigateur (localStorage).

## Tests

```bash
pytest
```

## Sur le téléphone (Render, gratuit)

1. Sur render.com, inscris-toi avec GitHub, puis New > Blueprint > ce dépôt.
2. Renseigne `GEMINI_API_KEY` (ta clé), `APP_MOT_DE_PASSE` (au choix) et `DATABASE_URL`
   (base gratuite sur neon.tech : inscription avec GitHub, puis « Connection string »), puis Apply.
3. Ouvre le lien `https://….onrender.com` sur le téléphone (n'importe quel identifiant + le mot de passe),
   puis « Ajouter à l'écran d'accueil ».

Le service gratuit s'endort après 15 min sans visite : la première ouverture prend environ 1 min.
La base garde les catalogues lus pendant la veille, et les bons et besoins sont les mêmes sur tous les appareils.
