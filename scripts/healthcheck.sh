#!/usr/bin/env bash
# Chequeo del entorno dockerizado (MejorPBX C1). Ejecutar desde la raíz.
# Detecta macOS (Ollama nativo) vs Windows/Linux (Ollama en contenedor).
set -u

cd "$(dirname "$0")/.."
if [ "$(uname -s)" = "Darwin" ]; then
  DC="docker compose -f docker-compose.yml -f docker-compose.mac.yml"
  NATIVE_OLLAMA=1
else
  DC="docker compose"
  NATIVE_OLLAMA=0
fi

echo "=== Ollama ==="
if [ "$NATIVE_OLLAMA" = "1" ]; then
  if curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "Ollama nativo OK en :11434"
    ollama ls 2>/dev/null
  else
    echo "Ollama nativo NO responde (arranca con: ollama serve)"
  fi
else
  nvidia-smi --query-gpu=name,memory.used --format=csv 2>/dev/null || echo "(sin nvidia-smi en host)"
  docker exec pbx-ollama ollama ls 2>/dev/null || echo "contenedor pbx-ollama no accesible"
  docker exec pbx-ollama ollama ps 2>/dev/null
fi

echo
echo "=== Servicios ==="
$DC ps

echo
echo "=== Webui (:8000) ==="
if curl -fsS http://localhost:8000/api/info >/dev/null 2>&1; then
  echo "webui OK -> http://localhost:8000"
else
  echo "webui NO responde (revisa: $DC logs webui)"
fi
