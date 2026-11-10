"""TTS con Kokoro-82M — plan.md §6 (reemplazo de Piper).

Kokoro corre en CPU (no pelea VRAM con el LLM), genera audio a 24 kHz y suena
mucho más natural que Piper. El pipeline se carga una sola vez (es caro) y se
reutiliza entre llamadas.
"""
from __future__ import annotations

import numpy as np

from . import config
from .textnorm import clean_for_tts  # reexport por compatibilidad

__all__ = ["clean_for_tts", "synth", "synth_to_wav"]

_pipeline = None  # KPipeline perezoso (se carga al primer uso)


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
