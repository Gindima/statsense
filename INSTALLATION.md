# StatSense AI — Mise en place

De zéro à `make seed` qui tourne. Comptez une heure.

---

## Fichiers fournis et leur destination

| Fichier | Destination |
|---|---|
| `bootstrap.sh` | à la racine, exécuté une fois |
| `docker-compose.yml` | `statsense/docker-compose.yml` |
| `Makefile` | `statsense/Makefile` |
| `env.example` | `statsense/.env` (renommer) |
| `settings.py` | `backend/config/settings.py` (remplace le généré) |
| `geography_models.py` | `backend/geography/models.py` |
| `catalog_models.py` | `backend/catalog/models.py` |
| `observations_models.py` | `backend/observations/models.py` |
| `0002_extensions.py` | `backend/catalog/migrations/` (après le 1er makemigrations) |
| `run.py`, `csv_rgph.py`, `sdmx.py`, `geo.py`, `utils.py`, `catalogue.py` | `data/seed/` |
| `questions_reference.py` | `tests/questions.py` |

---

## Étape 1 — Arborescence

```bash
bash bootstrap.sh
cd statsense
```

Le script crée les dossiers, l'environnement virtuel, installe les dépendances,
initialise le projet Django et les six apps.

**Dépendance manquante à ajouter :**

```bash
backend/.venv/bin/pip install django-cors-headers
backend/.venv/bin/pip freeze > backend/requirements.txt
```

## Étape 2 — Déposer les données

```
data/raw/rgph2023/     vos CSV du recensement
data/raw/sdmx/         pib.xml, emploi.xml
data/raw/geo/sn.json   le GeoJSON des 14 régions
```

Nommage des CSV : `region_departement.csv`, minuscules sans accent.
Le script ne lit pas les noms — c'est pour votre lisibilité.

## Étape 3 — Copier les fichiers fournis

Voir le tableau ci-dessus. Renommez `env.example` en `.env`.

## Étape 4 — Base de données

```bash
make up
```

PostgreSQL démarre sur le **port 5433** (pas 5432, pour éviter tout conflit
avec une instance déjà installée sur votre machine).

## Étape 5 — Migrations

Deux passes, parce que la migration d'extensions dépend de la première.

```bash
make migrate                      # 1re passe
# copier 0002_extensions.py dans backend/catalog/migrations/
# ajuster `dependencies` si le nom de la migration initiale diffère
make migrate                      # 2e passe
```

## Étape 6 — Chargement

```bash
make seed
```

Le rapport final affiche le nombre de zones par niveau, le total
d'observations, et la population nationale calculée comme somme des régions.

**C'est votre premier chiffre vérifiable.** Comparez-le aux publications ANSD.

---

## Vérifications

```bash
make controle        # contrôles sans écriture
make admin           # créer le compte admin
make dev             # puis http://localhost:8000/admin/
```

Dans l'admin, vérifiez que le catalogue contient bien 40 indicateurs
et que les zones sont correctement hiérarchisées.

---

## En cas de problème

**`make up` échoue** — Docker n'est pas lancé, ou le port 5433 est pris.
Changez le port dans `docker-compose.yml` et dans `.env`.

**`makemigrations` ne détecte rien** — les apps ne sont pas dans
`INSTALLED_APPS`, ou les fichiers `models.py` n'ont pas été copiés.

**Erreur sur `ArrayField` ou `GinIndex`** — `django.contrib.postgres`
manque dans `INSTALLED_APPS`.

**`make seed` : « aucun CSV trouvé »** — vérifiez que les fichiers sont
bien dans `data/raw/rgph2023/` avec l'extension `.csv`.

**Anomalies dans le rapport final** — c'est le comportement attendu tant que
les données sont incomplètes. « 3 régions au lieu de 14 » signifie
simplement qu'il manque des fichiers.

---

## Une fois que ça tourne

Dans l'ordre :

1. Parseur SDMX 2.1 `StructureSpecificData` (santé, éducation, mortalité)
2. Niveau `inspection_academique` dans `Zone`
3. Moteur analytique : les 4 méthodes
4. Couche IA : extraction du QueryPlan, validation, narration
5. API et frontend