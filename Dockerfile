# Dockerfile
#
# StatSense AI — image unique : API Django + frontend compilé
#
# Le frontend n'a pas son propre conteneur. Il est compilé ici, puis servi
# par Django via WhiteNoise. Un service en moins est une panne en moins, et
# le jury n'a qu'une seule adresse à ouvrir.
#
# Deux étapes :
#   1. node compile le frontend React en fichiers statiques
#   2. python reçoit ces fichiers et sert tout sur le port 8000
#
# Rien n'est téléchargé au démarrage : tout est figé dans l'image.

# --- étape 1 : compilation du frontend -------------------------------------
FROM node:20-alpine AS frontend

WORKDIR /frontend

# Les dépendances d'abord : cette couche ne change que si package.json change,
# donc les reconstructions suivantes sautent l'installation.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# --- étape 2 : application ------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    FRONTEND_DIST=/app/frontend_dist

# postgresql-client fournit pg_restore, utilisé au premier démarrage pour
# restaurer le jeu de données sans rejouer le chargement des 46 CSV.
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY data/ ./data/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Le frontend compilé, servi par WhiteNoise à la racine du domaine.
COPY --from=frontend /frontend/dist /app/frontend_dist

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]