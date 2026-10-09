# StatSense AI — Procédure de déploiement

Interroger les statistiques publiques de l'ANSD en français, et obtenir un
chiffre exact, sourcé et expliqué.

Ce document suffit à déployer la plateforme sur une machine neuve. Comptez
une quinzaine de minutes, dont l'essentiel en téléchargement.

---

## 1. Prérequis

| | |
|---|---|
| Docker | version 24 ou plus récente, avec `docker compose` |
| Mémoire | 8 Go minimum, 16 Go recommandés |
| Disque | 20 Go libres |
| Processeur | 4 cœurs recommandés |
| Réseau | requis au premier démarrage uniquement : construction de l'image (paquets Python et npm) et téléchargement du modèle |

Aucune autre dépendance : ni Python, ni Node, ni PostgreSQL sur la machine
hôte. Tout est dans les images.

La mémoire est la contrainte réelle : le modèle de langage occupe 2,2 Go
résidents, et il reste chargé pour que les réponses ne paient pas son
rechargement.

---

## 2. Déploiement

```bash
git clone https://github.com/Gindima/statsense.git
cd statsense
cp .env.exemple .env
docker compose up -d
```

La plateforme répond sur **http://localhost:8000**.

### Ce qui se passe au premier démarrage

| Étape | Durée |
|---|---|
| Construction de l'image (frontend compilé, dépendances Python) | 2 à 3 min |
| PostgreSQL démarre, migrations appliquées | 30 s |
| Restauration de la base depuis `data/backups/statsense.dump` | 15 s |
| Téléchargement du modèle `qwen2.5:3b-instruct` (1,9 Go) | 3 à 15 min |

L'application démarre **sans attendre le modèle**. Les questions déjà en
cache répondent immédiatement ; les nouvelles attendent que le
téléchargement soit terminé. C'est délibéré : une plateforme à moitié
disponible vaut mieux qu'un conteneur qui refuse de démarrer.

Les démarrages suivants ne téléchargent rien et ne rechargent rien : le
modèle et la base vivent dans des volumes Docker persistants.

---

## 3. Vérification

### La pile est en place

```bash
docker compose ps
```

Quatre services : `db` et `ollama` sains, `app` démarré, `ollama-init`
terminé après le téléchargement (il n'apparaît plus dans la liste une fois
arrêté ; `docker compose ps -a` le montre).

### La base est complète

```bash
docker compose logs app | grep -E "Restauration|zones,"
```

Attendu :

```
→ Restauration du dump (1.2M)
  25855 zones, 16 indicateurs, 132672 observations
```

Si vous lisez « Chargement complet depuis data/raw » à la place, le dump
était absent : la base est reconstruite depuis les fichiers d'origine, ce
qui prend deux minutes et donne exactement les mêmes chiffres.

### Le modèle est disponible

```bash
docker compose exec ollama ollama list
```

### Une question répond

```bash
curl -s -X POST http://localhost:8000/api/ask/ \
  -H 'Content-Type: application/json' \
  -d '{"question":"Taux de natalité des 14 régions du Sénégal"}' | head -c 300
```

Cette question fait partie des treize réponses préchauffées livrées dans le
dump : elle doit revenir en moins d'une seconde.

Pour éprouver la chaîne complète, modèle compris, posez une question qui
n'est pas en cache :

```bash
curl -s -X POST http://localhost:8000/api/ask/ \
  -H 'Content-Type: application/json' \
  -d '{"question":"Quel est le taux de mortalité à Saint-Louis ?"}' | head -c 300
```

Compter une trentaine de secondes sur un processeur sans carte graphique.
C'est le coût de l'inférence locale, et c'est le prix de la souveraineté des
données : aucune question ne sort de la machine.

---

## 4. Configuration

Tout se règle dans `.env`. Chaque variable a une valeur par défaut, et la
plateforme démarre sans `.env` du tout.

| Variable | Défaut | Rôle |
|---|---|---|
| `SECRET_KEY` | valeur de démonstration | **À changer en production** |
| `DEBUG` | `0` | Ne jamais passer à `1` en production |
| `ALLOWED_HOSTS` | `*` | Domaines autorisés, séparés par des virgules |
| `PORT` | `8000` | Port publié par l'application |
| `OLLAMA_MODEL` | `qwen2.5:3b-instruct` | Modèle de langage employé |
| `DB_NAME` `DB_USER` `DB_PASSWORD` | `statsense` | Identifiants PostgreSQL |
| `DB_PORT_HOTE` | `5433` | Port d'inspection de la base depuis l'hôte |

### Derrière un nom de domaine

```
PORT=8000
ALLOWED_HOSTS=statsense.exemple.sn,localhost
```

Puis un proxy inverse de votre choix vers `127.0.0.1:8000`. L'application
sert elle-même le frontend : aucun second serveur web n'est nécessaire.

### Changer de modèle

Le modèle par défaut, `qwen2.5:3b-instruct`, a été choisi pour fonctionner
sur un simple processeur avec 8 Go de mémoire. Sur une machine équipée d'une
carte graphique, un modèle plus grand se règle en une ligne :

```
OLLAMA_MODEL=qwen2.5:14b-instruct
```

Puis `docker compose up -d`. Le modèle est un **réglage**, pas une
dépendance d'architecture : il ne produit qu'un plan de requête, validé puis
exécuté par le moteur de calcul. Un modèle plus grand améliore la
compréhension des questions ; il ne change aucun chiffre.

### Déploiement hors ligne

Sur une machine sans accès à Internet, transférez le modèle depuis une
machine qui l'a déjà :

```bash
docker compose cp ~/.ollama/models/. ollama:/root/.ollama/models/
docker compose restart ollama
```

Sans aucun réseau, l'image de l'application doit aussi être construite
ailleurs, puis transférée :

```bash
docker save statsense-app | gzip > statsense-app.tar.gz   # machine connectée
docker load < statsense-app.tar.gz                         # machine cible
```

---

## 5. Exploitation

```bash
docker compose logs -f app          # journaux en continu
docker compose stop                 # arrêter sans rien perdre
docker compose up -d                # reprendre
docker compose down                 # retirer les conteneurs, garder les données
```

`down` conserve les volumes : la base et le modèle survivent. Pour repartir
d'une base vide — en gardant le modèle, et donc sans retélécharger :

```bash
docker compose down
docker volume rm statsense_pgdata
docker compose up -d
```

### Recharger les données depuis les fichiers d'origine

Les 46 fichiers CSV du recensement et les 9 fichiers SDMX sont dans
`data/raw/`. La reproductibilité est donc vérifiable :

```bash
docker compose exec app python data/seed/run.py --rebuild
```

Le rapport nomme chaque anomalie rencontrée dans les fichiers sources et
chaque correction appliquée.

### Régénérer le dump

Après un rechargement ou un préchauffage :

```bash
./docker/dump.sh
```

Le script vérifie que les quatre familles de tables sont présentes avant de
remplacer `data/backups/statsense.dump`.

Le dump porte les données **et** le cache des questions préchauffées. Il
doit donc être régénéré après le préchauffage, jamais avant.

---

## 6. En cas de problème

**`docker compose up` échoue sur un port occupé.** Changez `PORT` ou
`DB_PORT_HOTE` dans `.env`.

**L'application répond, mais toute question neuve échoue.** Le modèle n'est
pas encore téléchargé. `docker compose logs ollama-init` donne l'avancement.

**« qwen2.5:3b-instruct absent ».** Le téléchargement a échoué, faute de
réseau. L'application fonctionne avec les questions en cache ; voir la
section « déploiement hors ligne ».

**La première question prend deux à trois minutes.** C'est le chargement du
modèle en mémoire, payé une seule fois. Les suivantes tiennent dans la
trentaine de secondes.

**`pg_restore` signale des erreurs.** Un avertissement sur
`transaction_timeout` est sans conséquence. La ligne qui suit donne le
compte réel de zones, d'indicateurs et d'observations : c'est elle qui dit
si la restauration a réussi. En cas de compte anormal, l'entrypoint
enchaîne de lui-même sur le chargement complet.

**PostgreSQL met plus d'une minute à devenir sain.** Une récupération après
arrêt brutal. Préférez `docker compose down` à l'extinction de la machine.

---

## 7. Ce qui tourne

Quatre services, un seul port exposé.

```
db           PostgreSQL 16 + pg_trgm        volume pgdata
ollama       modèle de langage local        volume ollama
ollama-init  télécharge le modèle une fois, puis s'arrête
app          Django + gunicorn              port 8000
             sert l'API et le frontend compilé
```

Le frontend n'a pas de conteneur : il est compilé pendant la construction de
l'image et servi par Django. Chaque service en moins est une panne en moins.

### La chaîne d'une question

```
question en français
  -> questions documentaires et analyses non proposées  (code)
  -> présélection du catalogue                          (PostgreSQL)
  -> extraction d'un plan de requête                    (modèle de langage)
  -> corrections déterministes du plan                  (code)
  -> calcul                                             (SQL paramétré)
  -> rédaction de la réponse                            (code)
```

Le modèle de langage ne voit aucun chiffre et n'en produit aucun. Il traduit
une question en plan ; le calcul est fait en SQL déterministe. Les quatre
formules des indicateurs dérivés sont déclarées dans le catalogue, lisibles
dans `data/seed/catalogue.py`.

Sept champs du plan sur huit lui ont été retirés — zones, ventilations, périodes,
sens du tri, nombre d'éléments, niveau géographique, méthode — parce que
chacun a une forme fermée que le code reconnaît sans faillir.

### Données chargées

| Source | Couverture |
|---|---|
| RGPH-5, 2023 | 7 indicateurs, jusqu'au quartier — 25 241 quartiers |
| Catalogue standardisé ANSD (SDMX 2.1) | 9 indicateurs régionaux annuels, 1992 à 2025 |

132 672 observations, 16 indicateurs, 25 855 zones sur cinq niveaux
administratifs.

Trois anomalies ont été relevées dans les fichiers téléchargés : lignes
dupliquées (Ziguinchor, un défaut d'affichage du site corrigé depuis par
l'ANSD), villages homonymes, et totaux incompatibles avec leurs composantes.
Chacune est traitée de façon documentée et nommée dans le journal de
chargement. Elles ont été signalées à l'ANSD le 30 septembre 2026.

---

## 8. Licence et propriété

Projet réalisé pour le Hackathon des 20 ans de l'ANSD, octobre 2026.

Les données proviennent des publications publiques de l'ANSD et restent sa
propriété. Le GeoJSON des limites régionales vient de Simplemaps, sous
licence CC BY 4.0.