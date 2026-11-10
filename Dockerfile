# Orquestador / agente — Fase 1 (texto + tool calling).
FROM python:3.12-slim

WORKDIR /app

# Dependencias fijadas desde una sola fuente (MejorPBX A7).
COPY requirements-core.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# El código se monta como volumen en dev (docker-compose). El COPY sirve para
# construir una imagen autónoma si algún día se usa sin el bind-mount.
COPY . .

# Hardening (A7): usuario no-root.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

CMD ["python", "-m", "agent.chat_cli"]
