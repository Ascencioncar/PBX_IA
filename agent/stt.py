"""STT con faster-whisper — plan.md §6.

Transcribe audio español. Por defecto en CPU (int8) para no competir por la
VRAM que usa el LLM; configurable a CUDA vía .env. El modelo se carga una vez.
"""
from __future__ import annotations

import numpy as np

from . import config

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE,
        )
    return _model


def transcribe(audio_16k: np.ndarray, *, language: str = "es") -> str:
    """Transcribe audio float32 mono a 16 kHz y devuelve el texto.

    ``vad_filter`` recorta silencios para acelerar y limpiar.
    """
    model = _get_model()
    audio_16k = np.asarray(audio_16k, dtype=np.float32)
    segments, _info = model.transcribe(audio_16k, language=language, vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments).strip()


def transcribe_wav(path: str, *, language: str = "es") -> str:
    """Carga un WAV (lo resamplea a 16 kHz mono si hace falta) y lo transcribe."""
    import soundfile as sf

    audio, sr = sf.read(path, dtype="float32")
    if audio.ndim > 1:  # estéreo -> mono
        audio = audio.mean(axis=1)
    if sr != 16000:
        import soxr

        audio = soxr.resample(audio, sr, 16000)
    return transcribe(audio, language=language)
