#!/usr/bin/env bash
# Chequeo rápido del entorno dockerizado. Ejecutar desde la raíz del proyecto.
set -u

echo "=== GPU (host) ==="
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv 2>/dev/null \
  || echo "nvidia-smi no disponible en el host"

echo
echo "=== GPU (dentro del contenedor ollama) ==="
docker exec pbx-ollama nvidia-smi --query-gpu=name,memory.used --format=csv 2>/dev/null \
  || echo "contenedor pbx-ollama no accesible"

echo
echo "=== Modelos Ollama ==="
docker exec pbx-ollama ollama ls 2>/dev/null || echo "ollama no responde"

echo
echo "=== Modelos cargados (GPU/CPU) ==="
docker exec pbx-ollama ollama ps 2>/dev/null

echo
echo "=== Estado de servicios ==="
docker compose ps
