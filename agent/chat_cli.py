"""CLI de texto para la Fase 1 — plan.md §5.

Uso (dentro de WSL, con el venv activado):
    python -m agent.chat_cli                # conversación interactiva
    python -m agent.chat_cli --verbose      # muestra las tool_calls
    python -m agent.chat_cli --model llama3.2:3b   # smoke test
    python -m agent.chat_cli --once "¿cuál es el estado de la factura 53380?"

Mantiene el historial de la conversación entre turnos (memoria de contexto).
"""
from __future__ import annotations

import argparse
import sys

from . import config
from .llm import SYSTEM_PROMPT, run_conversation


def main() -> int:
    parser = argparse.ArgumentParser(description="Agente telefónico (Fase 1, texto).")
    parser.add_argument("--model", default=config.MODEL, help="Modelo de Ollama a usar.")
    parser.add_argument("--verbose", action="store_true", help="Mostrar tool_calls y resultados.")
    parser.add_argument("--once", metavar="TEXTO", help="Un solo turno y salir (para pruebas).")
    args = parser.parse_args()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if args.once:
        messages.append({"role": "user", "content": args.once})
        _, final = run_conversation(messages, model=args.model, verbose=args.verbose)
        print(final)
        return 0

    print(f"Agente listo (modelo: {args.model}, Ollama: {config.OLLAMA_HOST}).")
    print("Escribe tu mensaje. Ctrl-C o 'salir' para terminar.\n")
    while True:
        try:
            user = input("Tú> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if user.lower() in {"salir", "exit", "quit"}:
            return 0
        if not user:
            continue
        messages.append({"role": "user", "content": user})
        _, final = run_conversation(messages, model=args.model, verbose=args.verbose)
        print(f"Agente> {final}\n")


if __name__ == "__main__":
    sys.exit(main())
