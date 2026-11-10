"""Backend FastAPI: panel de administración del agente PBX.

- Autenticación por sesión (B1): todo /api/* exige sesión salvo el login.
- CRUD de herramientas con secretos enmascarados (B2).
- Estado de servicios y system prompt editable (B3).
- Chat de prueba que muestra qué herramientas invoca el agente.
Sirve además el frontend React compilado (WEBUI_DIST). El agente de voz comparte
data/tools.json y data/settings.json, así que los cambios aquí aplican a las llamadas.
"""
from __future__ import annotations

import os
import socket
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import config, settings, tools
from agent.llm import run_conversation
from webui import auth

app = FastAPI(title="PBX IA — Panel de administración")

AUDIOSOCKET_SVC = os.getenv("AUDIOSOCKET_SVC", "audiosocket")
ASTERISK_SVC = os.getenv("ASTERISK_SVC", "asterisk")

_PUBLIC_PATHS = {"/api/login", "/api/logout"}


# --------------------------------------------------------------------------- #
# Middleware de autenticación (B1): protege todas las rutas /api/*
# --------------------------------------------------------------------------- #
@app.middleware("http")
async def require_session(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in _PUBLIC_PATHS:
        user = auth.validate_token(request.cookies.get(auth.COOKIE_NAME))
        if not user:
            return JSONResponse({"detail": "No autenticado"}, status_code=401)
    return await call_next(request)


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
    system_prompt: str | None = None


class LoginReq(BaseModel):
    user: str
    password: str


# --------------------------------------------------------------------------- #
# Autenticación
# --------------------------------------------------------------------------- #
@app.post("/api/login")
def login(req: LoginReq, request: Request, response: Response):
    ip = request.client.host if request.client else "-"
    if auth.is_rate_limited(ip):
        raise HTTPException(429, "Demasiados intentos. Espera unos minutos.")
    if not auth.verify_credentials(req.user, req.password, ip):
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    token = auth.make_token(req.user)
    response.set_cookie(
        auth.COOKIE_NAME, token, httponly=True, samesite="lax",
        max_age=config.WEBUI_SESSION_HOURS * 3600,
    )
    return {"ok": True, "user": req.user}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@app.get("/api/auth/me")
def me(request: Request):
    user = auth.validate_token(request.cookies.get(auth.COOKIE_NAME))
    if not user:
        raise HTTPException(401, "No autenticado")
    return {"user": user, "default_password": auth.using_default_password()}


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


def _tcp_ok(host: str, port: int, timeout: float = 1.0) -> bool:
    """True solo si acepta la conexión TCP (para servidores TCP como audiosocket)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _host_up(host: str, port: int, timeout: float = 1.0) -> bool:
    """True si el host está alcanzable aunque rechace el puerto (Asterisk sirve SIP
    por UDP; un 'connection refused' en TCP igual indica que el contenedor está vivo)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except ConnectionRefusedError:
        return True
    except OSError:
        return False


@app.get("/api/status")
def status():
    """Estado de servicios para el Dashboard (B3)."""
    s = settings.load()
    ollama_ok = False
    try:
        import ollama

        ollama.Client(host=s.get("ollama_host") or config.OLLAMA_HOST).list()
        ollama_ok = True
    except Exception:  # noqa: BLE001
        ollama_ok = s.get("provider") == "openai"  # con OpenAI no dependemos de ollama local
    return {
        "services": {
            "ollama": ollama_ok,
            "audiosocket": _tcp_ok(AUDIOSOCKET_SVC, config.AUDIOSOCKET_PORT),
            "asterisk": _host_up(ASTERISK_SVC, 5060),
        },
        "provider": s.get("provider"),
        "model": s.get("model"),
        "tools_count": len(tools.load_tool_configs()),
        "streaming": config.VOICE_STREAMING,
        "barge_in": config.BARGE_IN,
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
    if not partial.get("openai_api_key"):   # no pisar la key con vacío
        partial.pop("openai_api_key", None)
    settings.save(partial)
    return _masked_settings()


@app.get("/api/models")
def list_models():
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
# CRUD de herramientas (con enmascarado de secretos — B2)
# --------------------------------------------------------------------------- #
_SECRET_HDR = ("key", "token", "secret", "auth", "api")


def _is_secret_header(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in _SECRET_HDR)


def _mask_tool(t: dict) -> dict:
    """No devolver valores de cabeceras sensibles en claro (B2)."""
    t = {**t, "headers": [dict(h) for h in t.get("headers", [])]}
    for h in t["headers"]:
        if h.get("value") and _is_secret_header(h.get("name", "")):
            h["value"] = ""
            h["value_set"] = True
    return t


def _merge_secret_headers(new: dict, old: dict | None) -> dict:
    """Al guardar: si una cabecera sensible llega vacía, conserva la guardada."""
    if not old:
        return new
    old_by_name = {h.get("name"): h.get("value", "") for h in old.get("headers", [])}
    for h in new.get("headers", []):
        if _is_secret_header(h.get("name", "")) and not h.get("value"):
            prev = old_by_name.get(h.get("name"))
            if prev:
                h["value"] = prev
        h.pop("value_set", None)
    return new


@app.get("/api/tools")
def list_tools():
    return [_mask_tool(t) for t in tools.load_tool_configs()]


def _find(cfgs, name):
    return next((i for i, t in enumerate(cfgs) if t.get("name") == name), -1)


@app.post("/api/tools")
def create_tool(tool: Tool):
    cfgs = tools.load_tool_configs()
    if _find(cfgs, tool.name) >= 0:
        raise HTTPException(409, f"Ya existe una herramienta llamada '{tool.name}'")
    cfgs.append(tool.model_dump())
    tools.save_tool_configs(cfgs)
    return _mask_tool(tool.model_dump())


@app.put("/api/tools/{name}")
def update_tool(name: str, tool: Tool):
    cfgs = tools.load_tool_configs()
    i = _find(cfgs, name)
    if i < 0:
        raise HTTPException(404, f"No existe '{name}'")
    j = _find(cfgs, tool.name)
    if j >= 0 and j != i:
        raise HTTPException(409, f"Ya existe '{tool.name}'")
    merged = _merge_secret_headers(tool.model_dump(), cfgs[i])
    cfgs[i] = merged
    tools.save_tool_configs(cfgs)
    return _mask_tool(merged)


@app.delete("/api/tools/{name}")
def delete_tool(name: str):
    cfgs = tools.load_tool_configs()
    i = _find(cfgs, name)
    if i < 0:
        raise HTTPException(404, f"No existe '{name}'")
    removed = cfgs.pop(i)
    tools.save_tool_configs(cfgs)
    return _mask_tool(removed)


@app.post("/api/tools/{name}/test")
def test_tool(name: str, req: TestReq):
    import time

    t0 = time.perf_counter()
    result = tools.dispatch(name, req.args)
    return {"result": result, "ms": round((time.perf_counter() - t0) * 1000)}


# --------------------------------------------------------------------------- #
# Telefonía (solo lectura, B3): resumen del dialplan/endpoints sin secretos
# --------------------------------------------------------------------------- #
@app.get("/api/telephony")
def telephony():
    return {
        "extensions": [
            {"exten": "100", "destino": "Agente IA (AudioSocket)"},
            {"exten": "600", "destino": "Eco (prueba de audio)"},
        ],
        "sip_endpoint": "1001",
        "audiosocket": f"{AUDIOSOCKET_SVC}:{config.AUDIOSOCKET_PORT}",
        "trunk_doc": "docs/PLAN_TRONCAL_ELASTIX.md",
    }


# --------------------------------------------------------------------------- #
# Chat de prueba (texto) — usa el system prompt vigente y muestra tool_calls
# --------------------------------------------------------------------------- #
@app.post("/api/chat")
def chat(req: ChatReq):
    messages = [{"role": "system", "content": settings.system_prompt()}]
    for m in req.history:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": req.message})

    calls: list[dict] = []
    try:
        _, reply = run_conversation(
            messages, on_tool=lambda n, a, r: calls.append({"name": n, "args": a, "result": r})
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Error del LLM: {e}") from e
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
