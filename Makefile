# Atajos de operación (MejorPBX C1). En macOS usa automáticamente el override.
.PHONY: mac up down logs health test build ps

ifeq ($(shell uname -s),Darwin)
DC = docker compose -f docker-compose.yml -f docker-compose.mac.yml
else
DC = docker compose
endif

mac:            ## Instala y levanta todo en Mac (un comando)
	./scripts/install-mac.sh

build:          ## Construye las imágenes
	$(DC) build

up:             ## Levanta la pila
	$(DC) up -d

down:           ## Detiene la pila
	$(DC) down

ps:             ## Estado de los servicios
	$(DC) ps

logs:           ## Logs del servidor de voz (Ctrl+C para salir)
	$(DC) logs -f audiosocket

health:         ## Chequeo del entorno
	./scripts/healthcheck.sh

test:           ## Lint (ruff) + tests (pytest) en una imagen limpia
	docker run --rm -v "$(CURDIR):/app" -w /app python:3.12-slim \
	  sh -c "pip install -q -r requirements-core.txt ruff pytest && ruff check . && pytest"
