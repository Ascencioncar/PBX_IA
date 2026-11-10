from agent import textnorm


def test_clean_for_tts_strips_emoji_and_markdown():
    out = textnorm.clean_for_tts("Claro 😊, aquí tienes **tu** factura 👍")
    assert "😊" not in out and "👍" not in out
    assert "*" not in out
    assert "Claro, aquí tienes tu factura" == out


def test_pop_sentences_keeps_decimals_and_splits():
    done, rest = textnorm.pop_sentences("Hola mundo. Tu factura 53.380 está pendiente. Y ")
    assert done == ["Hola mundo.", "Tu factura 53.380 está pendiente."]
    assert rest.strip() == "Y"


def test_pop_sentences_waits_at_buffer_end():
    # Un punto al final del buffer no corta (podría seguir el token).
    done, rest = textnorm.pop_sentences("Son 53.")
    assert done == []
    assert rest == "Son 53."


def test_split_sentences_full_text():
    assert textnorm.split_sentences("Una. Dos! Tres") == ["Una.", "Dos!", "Tres"]


def test_is_farewell_true():
    for s in ["adiós, gracias", "hasta luego", "eso es todo", "chao", "que tenga un buen día"]:
        assert textnorm.is_farewell(s), s


def test_is_farewell_false():
    for s in ["necesito una factura", "no, dime más", "quiero pagar"]:
        assert not textnorm.is_farewell(s), s
