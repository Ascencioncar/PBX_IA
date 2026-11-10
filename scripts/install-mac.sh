#!/usr/bin/env bash
# Instalación en un comando para Mac (Apple Silicon) — MejorPBX C1.
# Ollama corre NATIVO (Metal); el resto en Docker hablándole por host.docker.internal.
# Idempotente: puedes correrlo varias veces sin romper nada.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.mac.yml)
MODEL="${MODEL:-qwen3:8b}"
SMOKE="${MODEL_SMOKE:-llama3.2:3b}"

say() { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[!]\033[0m %s\n" "$*"; }
die() { printf "\033[1;31m[x]\033[0m %s\n" "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# 1) Plataforma
say "Comprobando plataforma…"
[ "$(uname -s)" = "Darwin" ] || die "Este script es solo para macOS. En Windows usa docs/DESPLIEGUE_WINDOWS.md."
[ "$(uname -m)" = "arm64" ] || warn "No es Apple Silicon (arm64); el rendimiento no será el esperado."

# 2) Prerrequisitos
if ! have brew; then
  warn "Homebrew no está instalado. Instálalo desde https://brew.sh y vuelve a ejecutar."
  die "Falta Homebrew."
fi
have ollama || { say "Instalando Ollama…"; brew install ollama; }
have espeak-ng || { say "Instalando espeak-ng…"; brew install espeak-ng || true; }
have docker || die "Falta Docker (Docker Desktop, Colima u OrbStack). Instálalo y reintenta."
docker info >/dev/null 2>&1 || die "El demonio de Docker no responde. Abre Docker Desktop/Colima y reintenta."

# 3) Ollama nativo + modelos
if ! curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
  say "Arrancando Ollama (brew services)…"
  brew services start ollama >/dev/null 2>&1 || (ollama serve >/tmp/ollama.log 2>&1 &)
  for _ in $(seq 1 30); do curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done
fi
curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1 || die "Ollama no responde en :11434."
say "Descargando modelos (idempotente)…"
ollama pull "$MODEL"
ollama pull "$SMOKE" || warn "No se pudo descargar $SMOKE (opcional)."

# 4) .env con valores de Mac + secretos generados
if [ ! -f .env ]; then
  say "Generando .env desde .env.example…"
  cp .env.example .env
  # OLLAMA_HOST -> host.docker.internal (los contenedores llegan al Ollama nativo)
  /usr/bin/sed -i '' 's|^OLLAMA_HOST=.*|OLLAMA_HOST=http://host.docker.internal:11434|' .env
else
  say ".env ya existe; no lo toco."
fi

# 5) Build (necesario antes de hashear la contraseña con la imagen webui)
say "Construyendo imágenes…"
"${COMPOSE[@]}" build

# Secreto de sesión y contraseña de la webui (solo si no están configurados)
if ! grep -q '^WEBUI_SECRET=.\+' .env; then
  SECRET="$(openssl rand -hex 32)"
  /usr/bin/sed -i '' "s|^WEBUI_SECRET=.*|WEBUI_SECRET=${SECRET}|" .env
fi
WEBUI_PW=""
if ! grep -q '^WEBUI_PASSWORD_HASH=.\+' .env; then
  WEBUI_PW="$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-14)"
  say "Generando hash de la contraseña de la webui…"
  HASH="$("${COMPOSE[@]}" run --rm --no-deps -T webui python -c "import bcrypt,sys;print(bcrypt.hashpw(sys.argv[1].encode(),bcrypt.gensalt()).decode())" "$WEBUI_PW")"
  /usr/bin/sed -i '' "s|^WEBUI_PASSWORD_HASH=.*|WEBUI_PASSWORD_HASH=${HASH}|" .env
fi

# 6) Levantar y chequear
say "Levantando servicios…"
"${COMPOSE[@]}" up -d
say "Esperando a la webui…"
for _ in $(seq 1 30); do curl -fsS http://localhost:8000/api/info >/dev/null 2>&1 && break; sleep 2; done

echo
say "Estado:"
"${COMPOSE[@]}" ps
curl -fsS http://localhost:8000/api/info >/dev/null 2>&1 && say "webui OK en http://localhost:8000" || warn "La webui aún no responde; revisa 'logs webui'."

# 7) Resumen
echo
printf "\033[1;32m================ LISTO ================\033[0m\n"
echo "Panel web:   http://localhost:8000"
echo "Usuario:     $(grep '^WEBUI_USER=' .env | cut -d= -f2)"
if [ -n "$WEBUI_PW" ]; then
  echo "Contraseña:  $WEBUI_PW   (guárdala; está hasheada en .env)"
else
  echo "Contraseña:  (la que ya tenías configurada en .env)"
fi
echo "Softphone:   registra 1001 / pbxlab1001 contra 127.0.0.1:5060; marca 100 (agente) o 600 (eco)."
echo "Comandos:    make up | make down | make logs | make health | make test"
