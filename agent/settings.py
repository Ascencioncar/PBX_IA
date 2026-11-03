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
    }


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
