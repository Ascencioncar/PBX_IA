"""TTS con Kokoro-82M — plan.md §6 (reemplazo de Piper).

Kokoro corre en CPU (no pelea VRAM con el LLM), genera audio a 24 kHz y suena
mucho más natural que Piper. El pipeline se carga una sola vez (es caro) y se
reutiliza entre llamadas.
"""
from __future__ import annotations

import re

import numpy as np

from . import config

_pipeline = None  # KPipeline perezoso (se carga al primer uso)

# Limpia artefactos que el TTS leería mal: bloques <think>, markdown, viñetas.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_MD_RE = re.compile(r"[*_`#>]+")

# Emojis y pictogramas: Kokoro los leería por su nombre ("cara feliz con ojos
# sonrientes"), así que los eliminamos antes de sintetizar.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # emojis, pictogramas y símbolos suplementarios
    "\U00002600-\U000027BF"  # símbolos misceláneos + dingbats
    "\U00002B00-\U00002BFF"  # símbolos y flechas varias
    "\U0000FE00-\U0000FE0F"  # selectores de variación
    "\U00002122\U00002139\U000024C2"  # ™ ℹ Ⓜ
    "\U0000200D"             # zero-width joiner (emojis compuestos)
    "]+",
    flags=re.UNICODE,
)


def clean_for_tts(text: str) -> str:
    text = _THINK_RE.sub("", text)
    text = _MD_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from kokoro import KPipeline  # import perezoso: la carga es pesada

        _pipeline = KPipeline(lang_code=config.TTS_LANG)
    return _pipeline


def synth(
    text: str,
    *,
    voice: str | None = None,
    speed: float | None = None,
) -> np.ndarray:
    """Sintetiza ``text`` y devuelve audio float32 mono a 24 kHz (TTS_SAMPLE_RATE).

    Kokoro trocea por frases y devuelve varios segmentos; los concatenamos.
    """
    pipeline = _get_pipeline()
    voice = voice or config.TTS_VOICE
    speed = speed if speed is not None else config.TTS_SPEED
    text = clean_for_tts(text)

    chunks: list[np.ndarray] = []
    for _, _, audio in pipeline(text, voice=voice, speed=speed):
        chunks.append(np.asarray(audio, dtype=np.float32))

    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)


def synth_to_wav(text: str, path: str, **kwargs) -> str:
    """Sintetiza y guarda a un WAV de 24 kHz. Devuelve la ruta."""
    import soundfile as sf

    audio = synth(text, **kwargs)
    sf.write(path, audio, config.TTS_SAMPLE_RATE)
    return path
