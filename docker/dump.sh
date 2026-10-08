#!/usr/bin/env bash
# docker/dump.sh
#
# Régénère data/backups/statsense.dump : données + cache préchauffé.
# À lancer depuis n'importe où, pile démarrée, APRÈS le préchauffage.

set -euo pipefail
cd "$(dirname "$0")/.."

DUMP="data/backups/statsense.dump"
TMP="${DUMP}.tmp"

# Tables applicatives seulement : les tables de Django sont recréées par
# les migrations, et les réinsérer ferait échouer la restauration.
docker compose exec -T db pg_dump -U statsense -d statsense \
    --data-only --no-owner --no-privileges -Fc \
    -t 'catalog_*' -t 'geography_*' -t 'observations_*' -t 'api_*' > "$TMP"

# Contrôle avant de remplacer quoi que ce soit.
liste="$(docker compose exec -T db pg_restore --list < "$TMP")"
for table in observations_observation geography_zone catalog_indicateur api_requete; do
    if ! printf '%s' "$liste" | grep -q "TABLE DATA public ${table}"; then
        echo "✗ ${table} absente du dump — l'ancien dump est conservé."
        rm -f "$TMP"
        exit 1
    fi
done

mv "$TMP" "$DUMP"
echo "✓ $(ls -lh "$DUMP" | awk '{print $5, $6, $7, $8}')  ${DUMP}"
git status --short "$DUMP"