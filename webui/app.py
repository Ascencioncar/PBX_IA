"""Backend FastAPI: CRUD de herramientas + probar + chat de prueba.

Sirve también el frontend React compilado (en WEBUI_DIST). El agente de voz
comparte el mismo data/tools.json, así que los cambios aquí aplican a las llamadas.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import config, settings, tools
from agent.llm import SYSTEM_PROMPT, run_conversation

app = FastAPI(title="PBX IA — Configuración de herramientas")


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #
class Param(BaseModel):
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    location: str = "query"  # path | query | body


class Header(BaseModel):
    name: str
    value: str = ""


class Tool(BaseModel):
    name: str
    description: str = ""
    method: str = "GET"
    url: str = ""
    auth: str = "none"  # none | bearer
    headers: list[Header] = []
    parameters: list[Param] = []


class TestReq(BaseModel):
    args: dict = {}


class ChatMsg(BaseModel):
    role: str
    content: str


class ChatReq(BaseModel):
    message: str
    history: list[ChatMsg] = []


class SettingsReq(BaseModel):
    provider: str | None = None
    model: str | None = None
    ollama_host: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    num_ctx: int | None = None
    num_predict: int | None = None
    think: bool | None = None


# --------------------------------------------------------------------------- #
# Info / estado
# --------------------------------------------------------------------------- #
@app.get("/api/info")
def info():
    s = settings.load()
    return {
        "provider": s.get("provider"),
        "model": s.get("model"),
        "tools_base_url": config.TOOLS_BASE_URL or None,
        "tools_base_url_set": bool(config.TOOLS_BASE_URL),
        "api_key_set": bool(config.TOOLS_API_KEY),
    }


def _masked_settings() -> dict:
    s = settings.load()
    key = s.pop("openai_api_key", "")
    s["openai_api_key_set"] = bool(key)
    return s


@app.get("/api/settings")
def get_settings():
    return _masked_settings()


@app.put("/api/settings")
def put_settings(req: SettingsReq):
    partial = req.model_dump()
    # No sobreescribir la API key con vacío (el front manda "" si no la tocan).
    if not partial.get("openai_api_key"):
        partial.pop("openai_api_key", None)
    settings.save(partial)
    return _masked_settings()


@app.get("/api/models")
def list_models():
    """Modelos locales de Ollama + sugerencias de OpenAI."""
    s = settings.load()
    ollama_models: list[str] = []
    try:
        import ollama

        data = ollama.Client(host=s.get("ollama_host") or config.OLLAMA_HOST).list()
        items = data.get("models", []) if isinstance(data, dict) else getattr(data, "models", [])
        for m in items:
            name = m.get("model") or m.get("name") if isinstance(m, dict) else getattr(m, "model", None)
            if name:
                ollama_models.append(name)
    except Exception:  # noqa: BLE001
        pass
    return {
        "ollama": sorted(ollama_models),
        "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1", "o4-mini"],
    }


# --------------------------------------------------------------------------- #
# CRUD de herramientas
# --------------------------------------------------------------------------- #
@app.get("/api/tools")
def list_tools():
    return tools.load_tool_configs()


def _find(cfgs, name):
    return next((i for i, t in enumerate(cfgs) if t.get("name") == name), -1)


@app.post("/api/tools")
def create_tool(tool: Tool):
    cfgs = tools.load_tool_configs()
    if _find(cfgs, tool.name) >= 0:
        raise HTTPException(409, f"Ya existe una herramienta llamada '{tool.name}'")
    cfgs.append(tool.model_dump())
    tools.save_tool_configs(cfgs)
    return tool


@app.put("/api/tools/{name}")
def update_tool(name: str, tool: Tool):
    cfgs = tools.load_tool_configs()
    i = _find(cfgs, name)
    if i < 0:
        raise HTTPException(404, f"No existe '{name}'")
    # Si renombran, evitar colisión con otra existente.
    j = _find(cfgs, tool.name)
    if j >= 0 and j != i:
        raise HTTPException(409, f"Ya existe '{tool.name}'")
    cfgs[i] = tool.model_dump()
    tools.save_tool_configs(cfgs)
    return tool


@app.delete("/api/tools/{name}")
def delete_tool(name: str):
    cfgs = tools.load_tool_configs()
    i = _find(cfgs, name)
    if i < 0:
        raise HTTPException(404, f"No existe '{name}'")
    removed = cfgs.pop(i)
    tools.save_tool_configs(cfgs)
    return removed


@app.post("/api/tools/{name}/test")
def test_tool(name: str, req: TestReq):
    result = tools.dispatch(name, req.args)
    return {"result": result}


# --------------------------------------------------------------------------- #
# Chat de prueba (texto) — muestra qué herramientas se invocan
# --------------------------------------------------------------------------- #
@app.post("/api/chat")
def chat(req: ChatReq):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in req.history:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": req.message})

    calls: list[dict] = []
    try:
        _, reply = run_conversation(
            messages, on_tool=lambda n, a, r: calls.append({"name": n, "args": a, "result": r})
        )
    except Exception as e:  # noqa: BLE001 — devolver el error a la UI
        raise HTTPException(500, f"Error del LLM: {e}")
    return {"reply": reply, "tool_calls": calls}


# --------------------------------------------------------------------------- #
# Frontend estático (React compilado). Debe ir al final (captura '/').
# --------------------------------------------------------------------------- #
_DIST = os.getenv("WEBUI_DIST", "/opt/webui/dist")
if Path(_DIST).is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="static")
else:
    @app.get("/")
    def _no_dist():
        return JSONResponse(
            {"detail": f"Frontend no compilado en {_DIST}. Reconstruye la imagen webui."},
            status_code=200,
        )
