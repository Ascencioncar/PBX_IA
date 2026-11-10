from pathlib import Path

from agent import settings


def test_load_defaults_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    d = settings.load()
    assert d["provider"] == "ollama"
    assert "system_prompt" in d


def test_save_merges_and_persists(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    settings.save({"model": "qwen3:8b", "provider": None})  # None no debe pisar
    d = settings.load()
    assert d["model"] == "qwen3:8b"
    assert d["provider"] == "ollama"  # se mantuvo el default
    assert Path(path).exists()


def test_save_second_call_keeps_previous(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    settings.save({"model": "a"})
    settings.save({"num_ctx": 4096})
    d = settings.load()
    assert d["model"] == "a" and d["num_ctx"] == 4096


def test_system_prompt_helper(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    assert settings.system_prompt() == settings.DEFAULT_SYSTEM_PROMPT
    settings.save({"system_prompt": "Eres un bot de pruebas."})
    assert settings.system_prompt() == "Eres un bot de pruebas."
