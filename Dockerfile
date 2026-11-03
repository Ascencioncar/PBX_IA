# Orquestador / agente — Fase 1 (texto + tool calling).
# Imagen ligera; las dependencias de voz (Fase 2) se añaden cuando lleguemos a ella.
FROM python:3.12-slim

WORKDIR /app

# Dependencias núcleo de Fase 1 (ver requirements.txt para el set completo).
RUN pip install --no-cache-dir \
    "ollama>=0.4.0" \
    "httpx>=0.27" \
    "python-dotenv>=1.0"

# El código se monta como volumen en dev (docker-compose). El COPY sirve para
# construir una imagen autónoma si algún día se usa sin el bind-mount.
COPY . .

CMD ["python", "-m", "agent.chat_cli"]
