"""
backend/config/settings.py

StatSense AI — configuration Django


TROIS AJOUTS POUR LE DÉPLOIEMENT

1. WHITENOISE sert le frontend compilé. Le frontend n'a pas de conteneur :
   il est bâti dans l'image et servi par Django à la racine du domaine, ce
   qui donne une seule adresse et un service en moins.

   WHITENOISE_ROOT publie le contenu de frontend/dist tel quel, de sorte que
   /assets/index-abc.js réponde sans que le HTML compilé ait à être
   réécrit. Aucun changement dans vite.config.js n'est donc nécessaire, et
   le proxy du serveur de développement continue de fonctionner comme
   avant.

2. ALLOWED_HOSTS et CSRF_TRUSTED_ORIGINS viennent de l'environnement. Avec
   DEBUG=0 et ALLOWED_HOSTS mal renseigné, Django répond 400 à toutes les
   requêtes — panne classique, et indéchiffrable pour qui découvre le
   projet.

3. Les valeurs par défaut de la base visent la machine de développement
   (localhost:5433, le port publié par Docker). En conteneur, docker
   compose fournit DB_HOST=db et DB_PORT=5432 par variables
   d'environnement, et `load_dotenv` ne les écrase pas : l'environnement
   réel a toujours priorité sur le fichier .env.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent      # backend/
RACINE = BASE_DIR.parent                               # statsense/

# override=False par défaut : une variable déjà présente dans
# l'environnement — celles de docker compose — n'est pas remplacée.
load_dotenv(RACINE / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-seulement-a-changer-en-production")
DEBUG = os.getenv("DEBUG", "1") == "1"

_hotes = os.getenv("ALLOWED_HOSTS", "*" if DEBUG else "")
ALLOWED_HOSTS = [h.strip() for h in _hotes.split(",") if h.strip()] or ["*"]

# Nécessaire derrière un proxy ou un nom de domaine : sans cela, l'admin
# Django refuse les formulaires avec une erreur CSRF peu explicite.
_origines = os.getenv("CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _origines.split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # requis pour ArrayField, JSONField indexé et les extensions
    "django.contrib.postgres",

    "rest_framework",
    "corsheaders",

    "geography",
    "catalog",
    "observations",
    "analytics",
    "ai",
    "api",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise juste après SecurityMiddleware, avant tout le reste :
    # un fichier statique ne doit pas traverser les sessions ni
    # l'authentification.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# --- frontend compilé ------------------------------------------------------
# En conteneur : /app/frontend_dist, posé par le Dockerfile.
# En développement : frontend/dist, présent après `npm run build`.
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", RACINE / "frontend" / "dist"))
FRONTEND_PRET = (FRONTEND_DIST / "index.html").exists()

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    # Le index.html compilé sert de gabarit à la route attrape-tout, pour
    # que les adresses internes du frontend fonctionnent au rechargement.
    "DIRS": [FRONTEND_DIST] if FRONTEND_PRET else [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "statsense"),
        "USER": os.getenv("DB_USER", "statsense"),
        "PASSWORD": os.getenv("DB_PASSWORD", "statsense"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5433"),
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Dakar"
USE_I18N = True
USE_TZ = True

# --- fichiers statiques ----------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = RACINE / "staticfiles"

if FRONTEND_PRET:
    # Publie frontend/dist à la racine du domaine : /assets/... répond
    # directement, et / renvoie index.html.
    WHITENOISE_ROOT = FRONTEND_DIST
    WHITENOISE_INDEX_FILE = True

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "UNAUTHENTICATED_USER": None,
}

# En production le frontend est servi par Django : même origine, donc aucun
# besoin de CORS. En développement, le serveur Vite est sur un autre port.
CORS_ALLOW_ALL_ORIGINS = DEBUG

NARRATION_LLM = False

# --- chemins des données ---------------------------------------------------
DATA_DIR = RACINE / "data"
RAW_DIR = DATA_DIR / "raw"

# --- modèle de langage -----------------------------------------------------
# Un réglage d'exploitation, pas une dépendance d'architecture : le modèle ne
# produit qu'un plan de requête, que le moteur valide avant de l'exécuter.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b-instruct")