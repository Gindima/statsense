PY = backend/.venv/bin/python
MANAGE = $(PY) backend/manage.py

.PHONY: up down migrate seed append controle dev shell admin backup reset

## Démarre PostgreSQL et attend qu'il réponde
up:
	docker compose up -d
	@until docker compose exec -T db pg_isready -U statsense >/dev/null 2>&1; \
		do echo "  attente de PostgreSQL..."; sleep 1; done
	@echo "PostgreSQL prêt sur le port 5433"

down:
	docker compose down

## Applique les migrations
migrate:
	$(MANAGE) makemigrations geography catalog observations
	$(MANAGE) migrate

## Vide et recharge toutes les données
seed:
	$(PY) data/seed/run.py --rebuild

## Charge uniquement les fichiers nouveaux ou modifiés
append:
	$(PY) data/seed/run.py --append

## Contrôles de cohérence sans écriture
controle:
	$(PY) data/seed/run.py --controle

dev:
	$(MANAGE) runserver

shell:
	$(MANAGE) shell

## Crée le compte administrateur
admin:
	$(MANAGE) createsuperuser

## Sauvegarde horodatée de la base
backup:
	@mkdir -p data/backups
	docker compose exec -T db pg_dump -U statsense statsense \
		| gzip > data/backups/statsense_$$(date +%Y%m%d_%H%M).sql.gz
	@echo "sauvegarde écrite dans data/backups/"

## Remise à zéro complète (base + migrations)
reset:
	docker compose down -v
	find backend -path "*/migrations/*.py" -not -name "__init__.py" -delete
	$(MAKE) up
	$(MAKE) migrate
	$(MAKE) seed


# À AJOUTER À LA FIN DE TON Makefile EXISTANT
#
# Je n'ai pas ton Makefile, donc je ne te le rends pas en entier : colle ce
# bloc à la fin. Attention aux tabulations — make exige une VRAIE tabulation
# en début de chaque ligne de commande, pas des espaces. Si tu obtiens
# « missing separator », c'est ça.

DUMP := data/backups/statsense.dump
TAR_MODELE := data/backups/ollama.tar

.PHONY: dump restaure docker-up docker-down docker-logs docker-rebuild \
        modele-export modele-import

# --- sauvegarde et restauration de la base ---------------------------------

dump:            ## Sauvegarde la base chargée, pour un démarrage sans seed
	@mkdir -p data/backups
	@docker exec statsense_db pg_dump \
	    --username=statsense --dbname=statsense \
	    --format=custom --data-only --no-owner --no-privileges \
	    > $(DUMP)
	@echo "  $(DUMP) — $$(du -h $(DUMP) | cut -f1)"
	@echo "  À committer : c'est lui qui évite trois minutes de chargement"
	@echo "  au démarrage du conteneur."

restaure:        ## Restaure le dump dans la base locale
	@PGPASSWORD=statsense pg_restore \
	    --host=localhost --port=5433 \
	    --username=statsense --dbname=statsense \
	    --data-only --disable-triggers --no-owner --no-privileges \
	    $(DUMP)

# --- pile complète ---------------------------------------------------------

docker-up:       ## Démarre tout : base, modèle, application sur :8000
	docker compose up --build -d
	@echo "  http://localhost:8000"
	@echo "  suivre le démarrage : make docker-logs"

docker-down:     ## Arrête tout, en conservant les données
	docker compose down

docker-logs:     ## Journal de l'application, en continu
	docker compose logs -f app

docker-rebuild:  ## Reconstruit l'image après un changement de code
	docker compose up --build -d app

# --- modèle hors ligne -----------------------------------------------------
#
# Le modèle pèse 2 Go et `ollama pull` a besoin du réseau. Sur un lieu de
# hackathon, le wifi n'est pas une hypothèse de travail : ces deux cibles
# transportent le volume Ollama dans une archive.

modele-export:   ## Exporte le modèle téléchargé, pour une machine hors ligne
	@mkdir -p data/backups
	@docker run --rm -v statsense_ollama:/from -v $$(pwd)/data/backups:/to \
	    alpine tar -cf /to/ollama.tar -C /from .
	@echo "  $(TAR_MODELE) — $$(du -h $(TAR_MODELE) | cut -f1)"

modele-import:   ## Importe le modèle depuis l'archive, avant le premier up
	@docker volume create statsense_ollama >/dev/null
	@docker run --rm -v statsense_ollama:/to -v $$(pwd)/data/backups:/from \
	    alpine tar -xf /from/ollama.tar -C /to
	@echo "  modèle en place, docker compose up peut démarrer sans réseau"