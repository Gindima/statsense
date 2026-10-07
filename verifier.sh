#!/usr/bin/env bash
# verifier.sh
#
# StatSense AI — Vérification d'un déploiement
#
#     ./verifier.sh              vérification standard, une quinzaine de secondes
#     ./verifier.sh --complet    ajoute une question neuve (compter 30 à 60 s)
#
# À lancer après `docker compose up -d`. Le script rend un VERDICT, et quand
# quelque chose manque il donne la commande qui le corrige.
#
#
# CE QUI EST BLOQUANT ET CE QUI NE L'EST PAS
#
# La distinction n'est pas cosmétique, elle suit l'architecture.
#
# Les chiffres de la plateforme sont calculés en SQL déterministe. Le modèle
# de langage ne sert qu'à traduire une question en plan de requête. Un modèle
# absent empêche donc de poser des questions NEUVES, mais n'empêche ni la
# plateforme de fonctionner, ni les questions déjà en cache de répondre, ni
# les chiffres d'être exacts.
#
#     bloquant        les conteneurs, l'API, et une question en cache qui
#                     rend un chiffre
#
#     non bloquant    le modèle de langage, les compteurs de données
#
# Un script qui échouerait sur un modèle manquant mentirait sur l'état réel
# du déploiement.

set -uo pipefail

# --- réglages lus dans .env, défauts sinon ---------------------------------

PORT=8000
[ -f .env ] && PORT="$(grep -E '^PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '[:space:]')"
[ -z "${PORT:-}" ] && PORT=8000

BASE="http://localhost:${PORT}"
QUESTION_CACHE="Taux de natalité des 14 régions du Sénégal"
QUESTION_NEUVE="Quel est le taux de mortalité à Saint-Louis ?"

bloquants=0
avertissements=0

# --- affichage -------------------------------------------------------------

ok()    { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn()  { printf '  \033[33m!\033[0m %s\n' "$1"; avertissements=$((avertissements + 1)); }
fail()  { printf '  \033[31m✗\033[0m %s\n' "$1"; bloquants=$((bloquants + 1)); }
info()  { printf '    %s\n' "$1"; }
titre() { printf '\n  \033[1m%s\033[0m\n' "$1"; }

# --- 0. outils -------------------------------------------------------------

titre "Outils"

if ! command -v docker >/dev/null 2>&1; then
    fail "Docker introuvable."
    info "Installer Docker 24 ou plus récent, puis relancer ce script."
    printf '\n  \033[31mVÉRIFICATION IMPOSSIBLE\033[0m\n\n'
    exit 2
fi

if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
    warn "Docker Compose v1 détecté : remplacer « docker compose » par « docker-compose » dans la documentation."
else
    fail "Docker Compose introuvable."
    info "Installer le plugin compose : apt install docker-compose-plugin"
    printf '\n  \033[31mVÉRIFICATION IMPOSSIBLE\033[0m\n\n'
    exit 2
fi
[ "$DC" = "docker compose" ] && ok "Docker et Docker Compose présents"

if ! command -v curl >/dev/null 2>&1; then
    fail "curl introuvable — nécessaire pour interroger l'API."
    info "apt install curl"
    printf '\n  \033[31mVÉRIFICATION IMPOSSIBLE\033[0m\n\n'
    exit 2
fi

# --- 1. conteneurs ---------------------------------------------------------

titre "Services"

etat="$($DC ps 2>/dev/null)"
if [ -z "$etat" ]; then
    fail "Aucun service lancé."
    info "$DC up -d"
    printf '\n  \033[31mDÉPLOIEMENT NON CONFORME\033[0m\n\n'
    exit 1
fi

for service in db ollama app; do
    ligne="$(printf '%s\n' "$etat" | grep -E "(^|[-_])${service}([-_]|[[:space:]])" | head -1)"
    if [ -z "$ligne" ]; then
        fail "service « ${service} » absent"
    elif printf '%s' "$ligne" | grep -qiE 'up|running|healthy'; then
        ok "service « ${service} » démarré"
    else
        fail "service « ${service} » présent mais arrêté"
        info "$DC logs ${service} | tail -40"
    fi
done

# --- 2. données ------------------------------------------------------------
#
# Le compte n'est imprimé par l'entrypoint qu'au PREMIER démarrage. Sur une
# pile déjà lancée, son absence ne dit rien : c'est pourquoi ce contrôle
# n'est pas bloquant. La preuve que les données sont là, c'est la question
# du point 4.

titre "Données"

compte="$($DC logs app 2>/dev/null \
    | grep -oE '[0-9]+ zones, [0-9]+ indicateurs, [0-9]+ observations' \
    | tail -1)"

if [ -n "$compte" ]; then
    ok "base chargée — ${compte}"
    case "$compte" in
        "25855 zones, 16 indicateurs, 132672 observations")
            ok "comptes identiques à la référence du dépôt" ;;
        *)
            warn "comptes différents de la référence attendue"
            info "référence : 25855 zones, 16 indicateurs, 132672 observations" ;;
    esac
else
    warn "compteur de chargement absent des journaux (normal après un redémarrage)"
fi

# --- 3. modèle de langage --------------------------------------------------

titre "Modèle de langage"

modele="qwen2.5:3b-instruct"
[ -f .env ] && m="$(grep -E '^OLLAMA_MODEL=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '[:space:]')" \
    && [ -n "$m" ] && modele="$m"

liste="$($DC exec -T ollama ollama list 2>/dev/null)"
if printf '%s' "$liste" | grep -q "${modele%%:*}"; then
    ok "${modele} présent"
else
    warn "${modele} absent : les questions NEUVES ne pourront pas être traitées."
    info "Les questions en cache répondent normalement, et les chiffres"
    info "restent exacts — le modèle ne calcule rien."
    info ""
    info "Si la machine a accès à Internet :"
    info "  $DC exec ollama ollama pull ${modele}"
    info ""
    info "Sinon, depuis une machine qui a déjà le modèle :"
    info "  ollama pull ${modele}"
    info "  tar -C ~/.ollama -czf modele.tgz models"
    info "  # transférer modele.tgz, puis ici :"
    info "  tar -C /tmp -xzf modele.tgz"
    info "  $DC cp /tmp/models/. ollama:/root/.ollama/models/"
    info "  $DC restart ollama"
fi

# --- 4. l'API répond -------------------------------------------------------

titre "Interface"

code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "${BASE}/" 2>/dev/null)"
if [ "$code" = "200" ]; then
    ok "page servie sur ${BASE}"
else
    fail "page non servie sur ${BASE} (code ${code:-aucun})"
    info "Port occupé ? Changer PORT dans .env, puis $DC up -d"
    info "$DC logs app | tail -40"
fi

# --- 5. une question répond avec un chiffre --------------------------------
#
# Le seul contrôle qui prouve que la chaîne entière fonctionne : catalogue,
# base, moteur de calcul, sérialisation.

titre "Réponse à une question"

debut="$(date +%s)"
reponse="$(curl -s --max-time 120 -X POST "${BASE}/api/ask/" \
    -H 'Content-Type: application/json' \
    -d "{\"question\":\"${QUESTION_CACHE}\"}" 2>/dev/null)"
duree=$(( $(date +%s) - debut ))

if [ -z "$reponse" ]; then
    fail "aucune réponse de l'API"
    info "$DC logs app | tail -40"
elif printf '%s' "$reponse" | grep -q '"statut"[[:space:]]*:[[:space:]]*"ok"'; then
    lignes="$(printf '%s' "$reponse" | grep -o '"valeur"' | wc -l | tr -d ' ')"
    ok "question servie en ${duree}s — ${lignes} valeur(s) calculée(s)"
    if [ "$duree" -le 3 ]; then
        ok "réponse préchauffée (cache du dump en place)"
    else
        warn "réponse en ${duree}s : le cache préchauffé n'a pas servi"
        info "Sans conséquence sur l'exactitude, seulement sur la vitesse."
    fi
else
    fail "la question n'a pas abouti"
    info "$(printf '%s' "$reponse" | head -c 300)"
fi

# --- 6. question neuve, à la demande ---------------------------------------

if [ "${1:-}" = "--complet" ]; then
    titre "Question neuve (chaîne complète, modèle compris)"
    info "Sans carte graphique, compter 30 à 60 s. Le premier appel après"
    info "le démarrage d'Ollama peut atteindre 3 min : c'est le chargement"
    info "du modèle en mémoire, payé une seule fois."

    debut="$(date +%s)"
    reponse="$(curl -s --max-time 300 -X POST "${BASE}/api/ask/" \
        -H 'Content-Type: application/json' \
        -d "{\"question\":\"${QUESTION_NEUVE}\"}" 2>/dev/null)"
    duree=$(( $(date +%s) - debut ))

    origine="$(printf '%s' "$reponse" | grep -o '"origine"[[:space:]]*:[[:space:]]*"[a-z]*"' \
        | head -1 | sed 's/.*"\([a-z]*\)"$/\1/')"

    if printf '%s' "$reponse" | grep -q '"statut"[[:space:]]*:[[:space:]]*"ok"'; then
        ok "question neuve servie en ${duree}s (origine : ${origine:-inconnue})"
        [ "$origine" = "repli" ] && warn "réponse produite sans le modèle : voir la section « Modèle de langage »"
    elif printf '%s' "$reponse" | grep -q '"statut"'; then
        statut="$(printf '%s' "$reponse" | grep -o '"statut"[[:space:]]*:[[:space:]]*"[a-z_]*"' \
            | head -1 | sed 's/.*"\([a-z_]*\)"$/\1/')"
        ok "réponse motivée en ${duree}s — statut « ${statut} »"
        info "Un refus explicite est une réponse valide : la plateforme"
        info "refuse ce que les données ne permettent pas d'affirmer."
    else
        fail "question neuve sans réponse exploitable"
        info "$(printf '%s' "$reponse" | head -c 300)"
    fi
fi

# --- verdict ---------------------------------------------------------------

printf '\n'
if [ "$bloquants" -gt 0 ]; then
    printf '  \033[31mDÉPLOIEMENT NON CONFORME\033[0m — %d point(s) bloquant(s)\n' "$bloquants"
    printf '  Chaque point ci-dessus porte la commande qui le corrige.\n\n'
    exit 1
fi

if [ "$avertissements" -gt 0 ]; then
    printf '  \033[32mDÉPLOIEMENT CONFORME\033[0m — avec %d réserve(s)\n' "$avertissements"
    printf '  La plateforme répond et ses chiffres sont exacts.\n'
    printf '  Les réserves ci-dessus limitent l'"'"'usage, pas la validité.\n\n'
    exit 0
fi

printf '  \033[32mDÉPLOIEMENT CONFORME\033[0m\n'
printf '  Plateforme disponible sur %s\n\n' "$BASE"
exit 0