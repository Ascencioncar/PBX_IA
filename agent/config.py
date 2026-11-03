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

PROJECT_ROOT = _PROJECT_ROOT
