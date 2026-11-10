"""Observabilidad (MejorPBX A6): logging estructurado + métricas de latencia.

- Un ``call_id`` por llamada (derivado del UUID de AudioSocket) viaja en cada línea
  vía ``contextvars`` (aislado por hilo, que es como atiende el servidor).
- ``stage(logger, "stt")`` mide el tiempo de una etapa y lo registra como métrica.
- Formato texto legible por defecto; JSON si ``LOG_JSON=true``.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
from contextlib import contextmanager

from . import config

_call_id: contextvars.ContextVar[str] = contextvars.ContextVar("call_id", default="-")
_configured = False


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        cid = _call_id.get()
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:5} [{cid}] {record.getMessage()}"
        metric = getattr(record, "metric", None)
        if metric:
            extra = " ".join(f"{k}={v}" for k, v in metric.items())
            base += f"  {extra}"
        return base


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "call_id": _call_id.get(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        metric = getattr(record, "metric", None)
        if metric:
            data.update(metric)
        return json.dumps(data, ensure_ascii=False)


def setup() -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if config.LOG_JSON else _TextFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))
    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup()
    return logging.getLogger(name)


def set_call_id(cid: str) -> None:
    _call_id.set(cid or "-")


def metric(logger: logging.Logger, msg: str, **fields) -> None:
    """Registra una línea con métricas estructuradas (p. ej. seconds por etapa)."""
    logger.info(msg, extra={"metric": fields})


@contextmanager
def stage(logger: logging.Logger, name: str, **fields):
    """Context manager que mide la duración de una etapa y la registra."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        metric(logger, f"{name} listo", stage=name, seconds=round(dt, 3), **fields)
