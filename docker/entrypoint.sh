#!/bin/sh
# docker/entrypoint.sh
#
# StatSense AI — démarrage du conteneur applicatif
#
# Quatre étapes, dans cet ordre :
#   1. attendre que PostgreSQL réponde
#   2. appliquer les migrations
#   3. peupler la base SI elle est vide
#   4. lancer gunicorn
#
#
# POURQUOI UN DUMP ET NON LE CHARGEMENT
#
# Rejouer le chargement demande deux minutes, les 46 CSV et les fichiers SDMX,
# et offre une dizaine d'occasions d'échouer. Un dump PostgreSQL se restaure
# en quelques secondes et donne exactement la même base, aux mêmes chiffres.
# Les CSV restent dans l'image — la reproductibilité est démontrable — mais
# ils ne sont plus sur le chemin critique du démarrage.
#
#
# POURQUOI LE DUMP NE CONTIENT QUE LES TABLES APPLICATIVES
#
# Les migrations tournent AVANT la restauration, et Django peuple lui-même
# `django_content_type` et `auth_permission` au passage. Un dump complet des
# données réinsère ces lignes, et la restauration casse :
#
#     COPY failed for table "django_content_type":
#     duplicate key value violates unique constraint
#
# Le dump est donc limité aux tables de nos applications :
#
#     pg_dump --data-only --no-owner --no-privileges -Fc \
#             -t 'catalog_*' -t 'geography_*' -t 'observations_*' -t 'api_*'
#
#
# POURQUOI LE RÉSULTAT EST VÉRIFIÉ
#
# Une restauration partielle est le pire des cas : l'application démarre, les
# pages s'affichent, et les réponses sont fausses ou absentes sans que rien ne
# le signale. La version antérieure se contentait d'avertir puis continuait.
#
# Le compte d'observations est donc contrôlé après restauration, et un compte
# anormal déclenche le chargement complet. Mieux vaut deux minutes de plus
# qu'une base silencieusement incomplète.
#
# Si les données brutes manquent aussi, l'application démarre vide plutôt que
# de refuser de démarrer : un catalogue vide se voit, un conteneur mort
# s'explique mal.

set -e

DUMP="${DUMP:-/app/data/backups/statsense.dump}"
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-statsense}"
DB_USER="${DB_USER:-statsense}"

# Plancher de vraisemblance. Le chargement complet produit 132 565
# observations ; un dixième de ce chiffre signale une restauration
# interrompue, pas un jeu de données réduit.
MINIMUM_OBS=10000


compter_observations() {
    python backend/manage.py shell -c \
        "from observations.models import Observation; print(Observation.objects.count())" \
        2>/dev/null | tail -1 | tr -d '[:space:]'
}

est_un_nombre() {
    case "$1" in
        '' | *[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

charger_depuis_les_sources() {
    if [ -z "$(ls /app/data/raw/rgph2023/*.csv 2>/dev/null)" ]; then
        echo "⚠  Données brutes absentes. L'application démarre avec une base"
        echo "   vide : le catalogue sera indisponible."
        return 0
    fi
    echo "→ Chargement complet depuis data/raw (2 à 4 minutes)"
    python data/seed/run.py --rebuild || {
        echo "⚠  Le chargement a signalé des anomalies. L'application démarre"
        echo "   quand même ; consulte le journal ci-dessus."
    }
}


echo "→ Attente de PostgreSQL sur ${DB_HOST}:${DB_PORT}"
i=0
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -gt 60 ]; then
        echo "✗ PostgreSQL injoignable après 120 s. Abandon."
        exit 1
    fi
    sleep 2
done
echo "  base joignable"

echo "→ Migrations"
python backend/manage.py migrate --noinput

# La base est-elle déjà peuplée ? On interroge le modèle plutôt que les
# tables : c'est la même question, posée dans le langage de l'application.
OBS=$(compter_observations)

if est_un_nombre "$OBS" && [ "$OBS" -ge "$MINIMUM_OBS" ]; then
    echo "→ Données déjà présentes (${OBS} observations), rien à charger"

elif [ -f "$DUMP" ]; then
    echo "→ Restauration du dump ($(du -h "$DUMP" | cut -f1))"
    # --disable-triggers : évite d'avoir à trier les insertions par clé
    # étrangère. Exige les droits de superutilisateur, dont l'utilisateur
    # propriétaire dispose dans ce conteneur.
    PGPASSWORD="${DB_PASSWORD:-statsense}" pg_restore \
        --host "$DB_HOST" --port "$DB_PORT" \
        --username "$DB_USER" --dbname "$DB_NAME" \
        --data-only --disable-triggers --no-owner --no-privileges \
        "$DUMP" || echo "  ⚠ la restauration a signalé des erreurs"

    OBS=$(compter_observations)
    if est_un_nombre "$OBS" && [ "$OBS" -ge "$MINIMUM_OBS" ]; then
        python backend/manage.py shell -c \
            "from observations.models import Observation as O; from geography.models import Zone; \
from catalog.models import Indicateur as I; \
print(f'  {Zone.objects.count()} zones, {I.objects.count()} indicateurs, {O.objects.count()} observations')"
    else
        echo "  ⚠ restauration incomplète (${OBS:-0} observations, minimum ${MINIMUM_OBS})"
        charger_depuis_les_sources
    fi

else
    echo "→ Aucun dump présent"
    charger_depuis_les_sources
fi

echo "→ Fichiers statiques"
python backend/manage.py collectstatic --noinput >/dev/null

echo "→ Vérification du modèle de langage"
python - <<'PY' || true
import os, requests
hote = os.getenv("OLLAMA_HOST", "http://ollama:11434").rstrip("/")
modele = os.getenv("OLLAMA_MODEL", "qwen2.5:3b-instruct")
try:
    noms = [m["name"] for m in requests.get(f"{hote}/api/tags", timeout=5)
            .json().get("models", [])]
    if any(n.startswith(modele.split(":")[0]) for n in noms):
        print(f"  {modele} disponible sur {hote}")
    else:
        print(f"  ⚠ {modele} absent de {hote}. Modèles présents : {noms or 'aucun'}")
        print("    La plateforme démarre : les questions déjà en cache")
        print("    répondent, les nouvelles attendront le modèle.")
except Exception as e:
    print(f"  ⚠ {hote} injoignable ({e.__class__.__name__}).")
PY

echo "→ gunicorn sur 0.0.0.0:8000"
# --timeout 300 : une question non mise en cache demande une trentaine de
# secondes d'inférence sur processeur. Le défaut de gunicorn, 30 s, tuerait
# le worker au milieu de la réponse.
# Le mode threads évite qu'une inférence lente bloque les autres requêtes.
exec gunicorn config.wsgi:application \
    --chdir /app/backend \
    --bind 0.0.0.0:8000 \
    --workers 2 --threads 4 --worker-class gthread \
    --timeout 300 --graceful-timeout 30 \
    --access-logfile - --error-logfile -