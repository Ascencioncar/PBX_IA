"""Normalización de texto para voz (sin dependencias pesadas).

Vive aparte de ``tts.py`` a propósito: ``tts`` importa numpy/kokoro, pero este
módulo solo usa ``re``. Así ``llm.py`` (y el contenedor webui, que no tiene numpy)
pueden trocear/limpiar texto sin arrastrar el stack de audio.
"""
from __future__ import annotations

import re
import unicodedata

# Artefactos que el TTS leería mal: bloques <think>, markdown, emojis.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_MD_RE = re.compile(r"[*_`#>]+")

# Emojis y pictogramas: Kokoro los leería por su nombre ("cara feliz...").
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

# Fin de frase: puntuación terminal seguida de espacio (o fin de texto).
_SENT_PUNCT = re.compile(r"[.!?…]")


def clean_for_tts(text: str) -> str:
    """Quita <think>, markdown y emojis; colapsa espacios."""
    text = _THINK_RE.sub("", text)
    text = _MD_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    # Evita un espacio colgando antes de puntuación tras quitar emojis.
    text = re.sub(r"\s+([,.;:!?…])", r"\1", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    """Trocea un texto COMPLETO en frases (para el camino no-streaming)."""
    sentences, rest = pop_sentences(text)
    tail = rest.strip()
    if tail:
        sentences.append(tail)
    return [s for s in (clean_for_tts(s) for s in sentences) if s]


# --- Detección de despedida (para colgar la llamada) ---
_FAREWELL_HINTS = (
    "adios", "hasta luego", "hasta pronto", "hasta la proxima", "hasta la vista",
    "nos vemos", "chao", "chau", "me despido",
    "eso es todo", "eso seria todo", "con eso es todo",
    "nada mas gracias", "nada mas, gracias",
    "gracias eso es todo", "gracias, eso es todo",
    "que tengas buen dia", "que tenga buen dia",
    "que tengas un buen dia", "que tenga un buen dia",
)


def normalize(text: str) -> str:
    """Minúsculas y sin acentos, para comparar de forma robusta."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def is_farewell(text: str) -> bool:
    t = normalize(text)
    return any(h in t for h in _FAREWELL_HINTS)


def pop_sentences(buf: str) -> tuple[list[str], str]:
    """Para streaming: devuelve (frases_completas, resto_sin_terminar).

    Solo corta en puntuación terminal SEGUIDA de espacio, así "53.380" o un punto
    al final del buffer (que puede continuar en el siguiente token) no parten mal.
    """
    out: list[str] = []
    last = 0
    for m in _SENT_PUNCT.finditer(buf):
        end = m.end()
        # exige que lo siguiente sea un espacio: si es fin de buffer o un dígito,
        # esperamos más tokens (puede ser un decimal o una frase incompleta).
        if end >= len(buf) or not buf[end].isspace():
            continue
        frag = buf[last:end].strip()
        if frag:
            out.append(frag)
        last = end
    return out, buf[last:]
