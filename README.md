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

Pour aller plus vite :
- **🎤 Dicter** tes besoins, ou **⚡ Comme d'habitude** (ta liste habituelle, moins ce qui est en stock).
- **🧾 Photo du ticket de caisse** après les courses : prix réels relevés, progression des challenges mise à jour,
  produits qui se conservent ajoutés au stock, et un produit acheté sur 2 tickets devient une habitude.
- **🔔 Me prévenir** : notification quand le panier de la semaine est prêt, et pour les bons qui expirent sous 3 jours.
  Sur iPhone, ajoute d'abord l'appli à l'écran d'accueil.

Le **mardi** (sortie des catalogues et Mardi PASS), l'appli lit les nouveaux catalogues et prépare le panier toute seule
avec tes besoins (ou « comme d'habitude »). En ligne, Render s'endort : le workflow GitHub `reveil.yml` la réveille
le mardi matin et chaque jour pour les rappels. Si l'adresse de ton appli n'est pas `https://panier-carrefour.onrender.com`,
mets-la dans la variable `APP_URL` du dépôt (Settings > Secrets and variables > Actions > Variables).

Il te dit quand et où commander, et sépare l'économie en caisse de celle en cagnotte. Tout l'état perso reste dans le navigateur (localStorage).

## Tests

```bash
pytest
```

## Sur le téléphone (Render, gratuit)

1. Sur render.com, inscris-toi avec GitHub, puis New > Blueprint > ce dépôt.
2. Renseigne `GEMINI_API_KEY` (ta clé), `APP_MOT_DE_PASSE` (au choix ; un par personne séparés par une virgule, ex. `le_mien,le_sien`) et `DATABASE_URL`
   (base gratuite sur neon.tech : inscription avec GitHub, puis « Connection string »), puis Apply.
3. Ouvre le lien `https://….onrender.com` sur le téléphone (n'importe quel identifiant + le mot de passe),
   puis « Ajouter à l'écran d'accueil ».

Le service gratuit s'endort après 15 min sans visite : la première ouverture prend environ 1 min.
La base garde les catalogues lus pendant la veille, et les bons et besoins sont les mêmes sur tous les appareils.
