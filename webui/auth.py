"""Autenticación de la webui (MejorPBX B1).

Login usuario+contraseña (hash bcrypt) + sesión por cookie firmada (itsdangerous).
Credenciales iniciales por .env: WEBUI_USER + WEBUI_PASSWORD_HASH (o, solo para
laboratorio, WEBUI_PASSWORD en claro). Rate limiting básico del login.
"""
from __future__ import annotations

import hashlib
import time

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from agent import config

COOKIE_NAME = "webui_session"
_SALT = "webui-session-v1"

# Intentos fallidos por IP: (ventana simple en memoria).
_MAX_FAILS = 5
_WINDOW_S = 300
_fails: dict[str, list[float]] = {}


def _password_hash() -> bytes:
    if config.WEBUI_PASSWORD_HASH:
        return config.WEBUI_PASSWORD_HASH.encode()
    # Fallback de laboratorio: hashea la contraseña en claro (o 'admin' por defecto).
    pw = config.WEBUI_PASSWORD or "admin"
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt())


_PW_HASH = _password_hash()


def _secret() -> str:
    if config.WEBUI_SECRET:
        return config.WEBUI_SECRET
    # Estable entre reinicios sin configurar nada: derivado del hash de la clave.
    return hashlib.sha256(b"pbxia-" + _PW_HASH).hexdigest()


_serializer = URLSafeTimedSerializer(_secret(), salt=_SALT)


def using_default_password() -> bool:
    """True si no hay hash ni contraseña propia (aviso de seguridad)."""
    return not config.WEBUI_PASSWORD_HASH and not config.WEBUI_PASSWORD


# --- Rate limiting ---
def _too_many(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _fails.get(ip, []) if now - t < _WINDOW_S]
    _fails[ip] = hits
    return len(hits) >= _MAX_FAILS


def _record_fail(ip: str) -> None:
    _fails.setdefault(ip, []).append(time.time())


def _clear_fails(ip: str) -> None:
    _fails.pop(ip, None)


# --- API de autenticación ---
def verify_credentials(user: str, password: str, ip: str = "-") -> bool:
    if _too_many(ip):
        return False
    ok = user == config.WEBUI_USER and bcrypt.checkpw(password.encode(), _PW_HASH)
    if ok:
        _clear_fails(ip)
    else:
        _record_fail(ip)
    return ok


def is_rate_limited(ip: str) -> bool:
    return _too_many(ip)


def make_token(user: str) -> str:
    return _serializer.dumps({"u": user})


def validate_token(token: str | None) -> str | None:
    """Devuelve el usuario si el token es válido y no expiró; si no, None."""
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=config.WEBUI_SESSION_HOURS * 3600)
        return data.get("u")
    except (BadSignature, SignatureExpired):
        return None
