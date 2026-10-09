# StatSense AI

Interroger les statistiques publiques de l'ANSD en français, et obtenir un chiffre exact, sourcé et expliqué.

Projet réalisé pour le Hackathon des 20 ans de l'ANSD, octobre 2026.

## Déploiement

Prérequis : Git et Docker 24+ avec Docker Compose v2. Connexion Internet au premier démarrage (image et modèle, environ 2 Go).

```bash
git clone https://srv-git.ansd.sn/hackathon-2026/statsense-ai.git
cd statsense-ai
cp .env.exemple .env
docker compose up -d
```

La plateforme répond sur http://localhost:8000.

Au premier démarrage, la base est restaurée automatiquement et le modèle de langage se télécharge en arrière-plan. Suivi du téléchargement :

```bash
docker compose logs -f ollama-init     # attendre « success »
```

Les questions de démonstration répondent immédiatement ; les nouvelles questions, dès que le modèle est téléchargé.

Procédure complète, vérifications, dépannage et mode hors ligne : [DEPLOIEMENT.md](DEPLOIEMENT.md).

## Vérification rapide

```bash
docker compose logs app | grep -E "Restauration|zones,"
# attendu : 25855 zones, 16 indicateurs, 132672 observations
```

## Principe

Un modèle de langage open source, exécuté localement (Qwen 2.5 via Ollama), traduit la question en un plan de requête. Le calcul est fait par un moteur SQL déterministe : le modèle ne voit et ne produit aucun chiffre. Chaque réponse porte sa source, et la plateforme refuse explicitement, avec le motif, ce que les données ne permettent pas de servir.

## Données

- RGPH-5 2023, jusqu'au quartier, village ou hameau (25 241 localités)
- Catalogue SDMX de l'ANSD : population projetée, emploi, chômage, natalité, mortalité, eau, électricité, bien-être

16 indicateurs, 132 672 observations. Aucune donnée ne quitte la machine.

Les données proviennent des publications publiques de l'ANSD et restent sa propriété. Limites régionales : Simplemaps, licence CC BY 4.0.
