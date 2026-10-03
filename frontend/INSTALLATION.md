# StatSense AI — Frontend

React + Vite + Tailwind. À déposer dans `statsense/frontend/`.

## Installation

```bash
cd ~/projets/statsense/frontend
npm install
npm run dev
```

Vite sert sur `http://localhost:5173` et relaie `/api` vers Django sur
le port 8000 — aucune configuration CORS n'est donc nécessaire.

Django doit tourner en parallèle : `make dev` dans un autre terminal.

## Ce que fait l'interface

L'écran suit l'architecture du projet, et c'est délibéré :

    question  →  plan de requête  →  résultat calculé

Le plan affiché entre les deux rend visible la séparation qui fonde
StatSense : le modèle a produit cet objet, et rien d'autre. Le calcul
qui suit n'en dépend plus. Déplié, il montre le JSON exact — ce qu'un
évaluateur voudra vérifier.

## Fichiers

| Fichier | Rôle |
|---|---|
| `src/App.jsx` | enchaînement des écrans, appels à l'API |
| `src/components/PlanRequete.jsx` | le plan, replié puis déplié |
| `src/components/Resultat.jsx` | les quatre rendus selon `chart_hint` |
| `src/components/Carte.jsx` | choroplèthe, jointure par code de région |
| `src/components/Refus.jsx` | refus méthodologique et alternatives |
| `src/components/Clarification.jsx` | demande de précision |
| `src/components/Catalogue.jsx` | inventaire des données chargées |
| `src/components/Notes.jsx` | avertissements produits par le moteur |
| `src/components/Sources.jsx` | provenance, sous chaque résultat |
| `src/lib/api.js` | accès aux cinq points d'entrée |
| `src/lib/format.js` | nombres à la française, unités, périodes |

## Mise en production

```bash
npm run build
```

Le résultat est dans `dist/`. Pour le servir depuis Django, ajoutez
`dist/` aux `STATICFILES_DIRS` et une route attrape-tout vers
`index.html`. Pour la démonstration en local, `npm run dev` suffit et
recharge à chaud.

## Points à connaître

**La carte.** Le GeoJSON vient de `/api/geo/` et n'est jamais stocké en
base. Les valeurs y sont jointes dans le navigateur par `geojson_id`,
puis par le nom en repli. Une région sans donnée reste grise plutôt que
masquée : l'absence est une information.

**Les classes de couleur** sont calculées par rangs et non par
intervalles égaux. La population sénégalaise est très concentrée sur
Dakar ; un découpage linéaire écraserait treize régions dans la classe
la plus claire.

**Les notes déjà reprises par le texte ne sont pas réaffichées**, pour
ne pas lire deux fois la même phrase.
