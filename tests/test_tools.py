import httpx
import pytest

from agent import config, tools

FACTURA = {
    "name": "consultar_factura",
    "description": "x",
    "method": "GET",
    "url": "{base}/facturas/{numero}",
    "auth": "none",
    "parameters": [{"name": "numero", "location": "path", "required": True}],
}
CREAR = {
    "name": "crear_ticket",
    "method": "POST",
    "url": "{base}/tickets",
    "parameters": [
        {"name": "asunto", "location": "body"},
        {"name": "prioridad", "location": "query"},
    ],
}


@pytest.fixture
def one(monkeypatch):
    def _set(cfg, base=""):
        monkeypatch.setattr(tools, "load_tool_configs", lambda: [cfg])
        monkeypatch.setattr(config, "TOOLS_BASE_URL", base)
    return _set


def test_unknown_tool(monkeypatch):
    monkeypatch.setattr(tools, "load_tool_configs", lambda: [])
    r = tools.dispatch("nope", {})
    assert r["estado"] == "ERROR"


def test_simulated_when_base_empty(one):
    one(FACTURA, base="")
    r = tools.dispatch("consultar_factura", {"numero": "42"})
    assert r["estado"] == "SIMULADO"


def test_path_param_and_real_request(one, monkeypatch):
    one(FACTURA, base="https://api.test")
    captured = {}

    def fake_request(method, url, **kw):
        captured.update(method=method, url=url, **kw)
        return httpx.Response(200, json={"ok": True}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    r = tools.dispatch("consultar_factura", {"numero": "42"})
    assert r == {"ok": True}
    assert captured["url"] == "https://api.test/facturas/42"


def test_query_and_body_routing(one, monkeypatch):
    one(CREAR, base="https://api.test")
    captured = {}

    def fake_request(method, url, **kw):
        captured.update(method=method, url=url, **kw)
        return httpx.Response(200, json={}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    tools.dispatch("crear_ticket", {"asunto": "hola", "prioridad": "alta"})
    assert captured["json"] == {"asunto": "hola"}
    assert captured["params"] == {"prioridad": "alta"}


def test_check_url_allowed_without_list():
    assert tools.check_url_allowed("http://169.254.169.254/") is None


def test_check_url_allowed_blocks_host_outside_list(monkeypatch):
    monkeypatch.setattr(config, "TOOLS_ALLOWED_HOSTS", ["api.ejemplo.com"])
    assert tools.check_url_allowed("http://malicioso.com/") is not None
    assert tools.check_url_allowed("https://api.ejemplo.com/x") is None
