"""Cliente de Ollama + bucle de tool calling — plan.md §4.

El bucle: se envían los mensajes al modelo con el array ``tools``. Si el modelo
devuelve ``tool_calls``, se ejecuta cada uno vía tools.dispatch() (HTTP real a
las APIs del usuario) y se reinyecta el resultado como mensaje ``role=tool``.
Se repite hasta que el modelo responde sin pedir más herramientas.

NOTA (plan §4): los nombres de campos de la librería ``ollama`` han variado
entre versiones. Este módulo normaliza la respuesta con ``_extract_tool_calls``
para no depender de un formato exacto. Si algo falla, revisar ahí primero.
"""
from __future__ import annotations

import json
from typing import Any

import ollama

from . import config, settings, tools

SYSTEM_PROMPT = (
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


def _client(host: str) -> ollama.Client:
    return ollama.Client(host=host)


def _as_dict(obj: Any) -> Any:
    """Convierte objetos pydantic de ollama a estructuras planas (dict/list)."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _as_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_as_dict(v) for v in obj]
    return obj


def _extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Devuelve [{'name': str, 'arguments': dict}, ...] desde el mensaje del modelo."""
    raw = message.get("tool_calls") or []
    out: list[dict[str, Any]] = []
    for call in raw:
        fn = call.get("function", call) if isinstance(call, dict) else call
        name = fn.get("name")
        args = fn.get("arguments", {})
        if isinstance(args, str):  # algunas versiones devuelven JSON como texto
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if name:
            out.append({"name": name, "arguments": args or {}})
    return out


def run_conversation(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    verbose: bool = False,
    max_iterations: int = 8,
    on_tool=None,
) -> tuple[list[dict[str, Any]], str]:
    """Ejecuta el bucle de tool calling. Elige proveedor (Ollama/OpenAI) según los
    ajustes en caliente (`data/settings.json`). ``messages`` se muta in-place.

    ``on_tool(name, args, result)`` se invoca por cada herramienta ejecutada.
    """
    s = settings.load()
    model = model or s.get("model") or config.MODEL
    if s.get("provider") == "openai":
        return _run_openai(messages, s, model, max_iterations, verbose, on_tool)
    return _run_ollama(messages, s, model, max_iterations, verbose, on_tool)


def _run_ollama(messages, s, model, max_iterations, verbose, on_tool):
    client = _client(s.get("ollama_host") or config.OLLAMA_HOST)
    for _ in range(max_iterations):
        kwargs = dict(
            model=model,
            messages=messages,
            tools=tools.get_schemas(),
            options={"num_ctx": s.get("num_ctx"), "num_predict": s.get("num_predict")},
        )
        try:
            # qwen3: desactivar reasoning = mucha menos latencia.
            resp = client.chat(think=bool(s.get("think")), **kwargs)
        except (TypeError, ollama.ResponseError):
            resp = client.chat(**kwargs)
        message = _as_dict(resp.get("message") if isinstance(resp, dict) else resp["message"])
        messages.append(message)

        calls = _extract_tool_calls(message)
        if not calls:
            return messages, (message.get("content") or "").strip()

        for call in calls:
            name, args = call["name"], call["arguments"]
            if verbose:
                print(f"  [tool] {name}({args})")
            result = tools.dispatch(name, args)
            if verbose:
                print(f"  [tool] -> {result}")
            if on_tool is not None:
                on_tool(name, args, result)
            messages.append(
                {
                    "role": "tool",
                    "tool_name": name,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
    return messages, "(se alcanzó el máximo de iteraciones de herramientas)"


def _run_openai(messages, s, model, max_iterations, verbose, on_tool):
    from openai import OpenAI

    client = OpenAI(
        api_key=s.get("openai_api_key") or "none",
        base_url=s.get("openai_base_url") or "https://api.openai.com/v1",
    )
    schemas = tools.get_schemas()
    for _ in range(max_iterations):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=schemas or None,
            max_tokens=s.get("num_predict") or None,
        )
        m = resp.choices[0].message
        tool_calls = m.tool_calls or []
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": m.content or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]
        messages.append(assistant_msg)

        if not tool_calls:
            return messages, (m.content or "").strip()

        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if verbose:
                print(f"  [tool] {name}({args})")
            result = tools.dispatch(name, args)
            if on_tool is not None:
                on_tool(name, args, result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
    return messages, "(se alcanzó el máximo de iteraciones de herramientas)"


def new_messages(user_text: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]


def ask(user_text: str, *, model: str | None = None, verbose: bool = False) -> str:
    """Atajo de un solo turno: pregunta -> respuesta final (texto)."""
    _, final = run_conversation(new_messages(user_text), model=model, verbose=verbose)
    return final
