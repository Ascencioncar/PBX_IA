"""Registro de herramientas (tool calling) + dispatch — plan.md §4.

Config-driven: las herramientas se definen en ``data/tools.json`` (editable desde
la UI web), NO en código. El agente de voz y la UI comparten ese mismo archivo, así
que añadir una API nueva no requiere tocar Python ni reiniciar.

Formato de cada herramienta en el JSON:
    {
      "name": "consultar_factura",
      "description": "…",
      "method": "GET",                      # GET|POST|PUT|DELETE|PATCH
      "url": "{base}/facturas/{numero}",    # {base}=TOOLS_BASE_URL, {param}=param de 'path'
      "auth": "none" | "bearer",            # bearer usa TOOLS_API_KEY (global)
      "headers": [                           # cabeceras propias (p.ej. API key de un servicio externo)
        {"name": "X-API-Key", "value": "abc123"}
      ],
      "parameters": [
        {"name": "numero", "type": "string", "description": "…",
         "required": true, "location": "path" | "query" | "body"}
      ]
    }

La URL puede ser un servicio EXTERNO (full URL, p.ej. "https://api.ejemplo.com/v1/...")
o usar {base} (= TOOLS_BASE_URL). Si usa {base} y TOOLS_BASE_URL está vacío,
dispatch() devuelve una respuesta SIMULADA (para probar sin backend real).
Nota de red (Docker): para llegar a un servicio del PROPIO host usa
"http://host.docker.internal:PUERTO", no "localhost".
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from . import config

CONFIG_PATH = Path(
    os.getenv("TOOLS_CONFIG_PATH", str(config.PROJECT_ROOT / "data" / "tools.json"))
)


# --------------------------------------------------------------------------- #
# Persistencia del registro
# --------------------------------------------------------------------------- #
def load_tool_configs() -> list[dict[str, Any]]:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_tool_configs(tools: list[dict[str, Any]]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(tools, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# Schemas para Ollama (se generan desde el JSON en cada llamada => cambios en vivo)
# --------------------------------------------------------------------------- #
def get_schemas() -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    for t in load_tool_configs():
        props: dict[str, Any] = {}
        required: list[str] = []
        for p in t.get("parameters", []):
            props[p["name"]] = {
                "type": p.get("type", "string"),
                "description": p.get("description", ""),
            }
            if p.get("required"):
                required.append(p["name"])
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            }
        )
    return schemas


# --------------------------------------------------------------------------- #
# Ejecución HTTP real a la API/webhook del usuario
# --------------------------------------------------------------------------- #
def _auth_headers(auth: str) -> dict[str, str]:
    h = {"Accept": "application/json"}
    if auth == "bearer" and config.TOOLS_API_KEY:
        h["Authorization"] = f"Bearer {config.TOOLS_API_KEY}"
    return h


def dispatch(name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """Enruta por nombre y ejecuta la herramienta. Nunca lanza: errores como dict."""
    args = args or {}
    cfg = next((t for t in load_tool_configs() if t.get("name") == name), None)
    if cfg is None:
        return {"estado": "ERROR", "detalle": f"herramienta desconocida: {name}"}

    url_tmpl = cfg.get("url", "")
    uses_base = "{base}" in url_tmpl
    base = config.TOOLS_BASE_URL

    if uses_base and not base:
        return {
            "estado": "SIMULADO",
            "motivo": "TOOLS_BASE_URL no configurado",
            "herramienta": name,
            "args": args,
        }

    url = url_tmpl.replace("{base}", base)
    query: dict[str, Any] = {}
    body: dict[str, Any] = {}
    for p in cfg.get("parameters", []):
        n = p["name"]
        if n not in args:
            continue
        loc = p.get("location", "query")
        if loc == "path":
            url = url.replace("{" + n + "}", str(args[n]))
        elif loc == "body":
            body[n] = args[n]
        else:
            query[n] = args[n]

    # Cabeceras: auth global (bearer) + cabeceras propias de la herramienta.
    headers = _auth_headers(cfg.get("auth", "none"))
    for h in cfg.get("headers", []) or []:
        name = (h.get("name") or "").strip()
        if name:
            headers[name] = h.get("value", "")

    method = cfg.get("method", "GET").upper()
    try:
        r = httpx.request(
            method,
            url,
            params=query or None,
            json=body or None,
            headers=headers,
            timeout=config.TOOLS_TIMEOUT,
        )
        r.raise_for_status()
        try:
            return r.json()
        except ValueError:
            return {"status": r.status_code, "text": r.text}
    except httpx.HTTPError as e:
        return {"estado": "ERROR", "detalle": str(e), "url": url}
