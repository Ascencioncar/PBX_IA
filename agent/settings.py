"""Ajustes del LLM editables en caliente (desde la UI) — `data/settings.json`.

Permite cambiar de proveedor (Ollama local u OpenAI / API compatible) y de modelo
sin tocar código ni reiniciar. Los valores por defecto salen de .env (config).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import config

SETTINGS_PATH = Path(
    os.getenv("SETTINGS_PATH", str(config.PROJECT_ROOT / "data" / "settings.json"))
)

# Prompt del sistema por defecto. Editable en caliente desde la UI (B3); vive aquí
# (no en llm.py) para evitar un import circular settings<->llm.
DEFAULT_SYSTEM_PROMPT = (
    "Eres el asistente telefónico de la empresa. Hablas español de forma natural y cálida. "
    "MUY IMPORTANTE: responde en 1 o 2 frases cortas, como en una llamada telefónica. "
    "NO uses markdown, viñetas, asteriscos ni emojis: tu texto se convierte a voz. "
    "Di los montos y números de forma hablada y breve. "
    "Cuando el usuario pide datos reales (facturas, tickets, etc.), USA las herramientas "
    "en vez de inventar. Si no necesita herramienta, responde directo. "
    "Nunca inventes números de factura, montos ni identificadores: si no los tienes, pídelos. "
    "Cuando el usuario se despida o diga que no necesita nada más, despídete de forma breve y amable "
    "(por ejemplo: 'Gracias por llamar, que tenga un buen día')."
)


def defaults() -> dict[str, Any]:
    return {
        "provider": "ollama",           # ollama | openai
        "model": config.MODEL,
        "ollama_host": config.OLLAMA_HOST,
        "openai_api_key": "",
        "openai_base_url": "https://api.openai.com/v1",
        "num_ctx": config.NUM_CTX,
        "num_predict": config.NUM_PREDICT,
        "think": config.LLM_THINK,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
    }


def system_prompt() -> str:
    """Prompt del sistema vigente (editable en caliente)."""
    return load().get("system_prompt") or DEFAULT_SYSTEM_PROMPT


def load() -> dict[str, Any]:
    d = defaults()
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            d.update(saved)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return d


def save(partial: dict[str, Any]) -> dict[str, Any]:
    cur = load()
    for k, v in partial.items():
        if v is not None:
            cur[k] = v
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cur
