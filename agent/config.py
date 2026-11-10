"""Configuración centralizada: lee variables de entorno desde .env.

Nada de rutas/puertos/IPs hardcodeados (ver plan.md §11 portabilidad).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Carga .env desde la raíz del proyecto (un nivel por encima de agent/).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# --- LLM (Ollama) ---
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL: str = os.getenv("MODEL", "qwen3:8b")
MODEL_SMOKE: str = os.getenv("MODEL_SMOKE", "llama3.2:3b")
NUM_CTX: int = int(os.getenv("NUM_CTX", "8192"))
# qwen3 razona por defecto (<think>...), lo que dispara la latencia. Para voz
# en tiempo real lo apagamos. Poner LLM_THINK=true solo para depurar.
LLM_THINK: bool = os.getenv("LLM_THINK", "false").lower() in {"1", "true", "yes", "si", "sí"}
# Tope de tokens de respuesta: respuestas cortas = menos latencia de LLM y de TTS.
NUM_PREDICT: int = int(os.getenv("NUM_PREDICT", "200"))
# Mantener el modelo cargado en memoria para no pagar la recarga (clave en voz:
# una llamada tras inactividad no debe esperar 30-60s a que Ollama recargue).
OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

# --- STT (faster-whisper) ---
WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", "cpu")      # cpu | cuda
WHISPER_COMPUTE: str = os.getenv("WHISPER_COMPUTE", "int8")   # int8 (cpu) | int8_float16 (cuda)

# --- TTS (Kokoro-82M, corre en CPU) ---
TTS_LANG: str = os.getenv("TTS_LANG", "e")            # 'e' = español en Kokoro
TTS_VOICE: str = os.getenv("TTS_VOICE", "ef_dora")    # voz española por defecto
TTS_SPEED: float = float(os.getenv("TTS_SPEED", "1.0"))
TTS_SAMPLE_RATE: int = 24000                          # Kokoro genera a 24 kHz

# --- Herramientas del usuario (APIs/webhooks) ---
TOOLS_BASE_URL: str = os.getenv("TOOLS_BASE_URL", "").rstrip("/")
TOOLS_API_KEY: str = os.getenv("TOOLS_API_KEY", "")
TOOLS_TIMEOUT: float = float(os.getenv("TOOLS_TIMEOUT", "10"))

# --- Telefonía (Fase 3) ---
AUDIOSOCKET_HOST: str = os.getenv("AUDIOSOCKET_HOST", "127.0.0.1")
AUDIOSOCKET_PORT: int = int(os.getenv("AUDIOSOCKET_PORT", "9000"))


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "si", "sí"}


# --- Voz: streaming y barge-in (MejorPBX A1/A2) ---
# Streaming de TTS por frases (menor time-to-first-audio). Apagar => camino clásico.
VOICE_STREAMING: bool = _flag("VOICE_STREAMING", "true")
# Barge-in: permitir interrumpir al agente hablando. Experimental; apagado por defecto.
BARGE_IN: bool = _flag("BARGE_IN", "false")

# --- Historial de la llamada (A3): ventana deslizante ---
# Nº máximo de turnos (user+assistant) que se conservan además del system.
HISTORY_MAX_TURNS: int = int(os.getenv("HISTORY_MAX_TURNS", "8"))

# --- Topes de turno/llamada (A5) ---
MAX_UTTERANCE_MS: int = int(os.getenv("MAX_UTTERANCE_MS", "15000"))
MAX_CALL_SECONDS: int = int(os.getenv("MAX_CALL_SECONDS", "600"))

# --- Observabilidad (A6) ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_JSON: bool = _flag("LOG_JSON", "false")
# Carpeta para persistir transcripciones de llamadas (vacío = desactivado, privacidad).
CALL_LOG_DIR: str = os.getenv("CALL_LOG_DIR", "")

# --- Seguridad del dispatch de herramientas (A8, anti-SSRF) ---
# Lista blanca de hosts permitidos (coma-separada). Vacío = sin restricción.
TOOLS_ALLOWED_HOSTS: list[str] = [
    h.strip().lower() for h in os.getenv("TOOLS_ALLOWED_HOSTS", "").split(",") if h.strip()
]
# Bloquear IPs privadas/loopback/metadata salvo que se habiliten explícitamente.
TOOLS_ALLOW_PRIVATE: bool = _flag("TOOLS_ALLOW_PRIVATE", "false")

# --- Autenticación de la webui (B1) ---
WEBUI_USER: str = os.getenv("WEBUI_USER", "admin")
WEBUI_PASSWORD_HASH: str = os.getenv("WEBUI_PASSWORD_HASH", "")
# Contraseña en claro SOLO para arranque/lab: si no hay hash, se usa esta.
WEBUI_PASSWORD: str = os.getenv("WEBUI_PASSWORD", "")
WEBUI_SECRET: str = os.getenv("WEBUI_SECRET", "")
WEBUI_SESSION_HOURS: int = int(os.getenv("WEBUI_SESSION_HOURS", "12"))

PROJECT_ROOT = _PROJECT_ROOT
DATA_DIR = _PROJECT_ROOT / "data"
