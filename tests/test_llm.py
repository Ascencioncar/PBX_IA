from agent import llm


def test_extract_tool_calls_nested_function():
    msg = {"tool_calls": [{"function": {"name": "f", "arguments": {"a": 1}}}]}
    assert llm._extract_tool_calls(msg) == [{"name": "f", "arguments": {"a": 1}}]


def test_extract_tool_calls_string_arguments():
    msg = {"tool_calls": [{"function": {"name": "f", "arguments": '{"a": 1}'}}]}
    assert llm._extract_tool_calls(msg) == [{"name": "f", "arguments": {"a": 1}}]


def test_extract_tool_calls_bad_json_yields_empty_args():
    msg = {"tool_calls": [{"function": {"name": "f", "arguments": "no-json"}}]}
    assert llm._extract_tool_calls(msg) == [{"name": "f", "arguments": {}}]


def test_extract_tool_calls_none():
    assert llm._extract_tool_calls({"content": "hola"}) == []


def _mk(system=True, turns=0):
    msgs = [{"role": "system", "content": "s"}] if system else []
    for i in range(turns):
        msgs.append({"role": "user", "content": f"u{i}"})
        msgs.append({"role": "assistant", "content": f"a{i}"})
    return msgs


def test_trim_history_keeps_last_n_turns():
    msgs = _mk(turns=12)
    llm.trim_history(msgs, max_turns=4)
    users = [m for m in msgs if m["role"] == "user"]
    assert len(users) == 4
    assert msgs[0]["role"] == "system"
    assert users[0]["content"] == "u8"


def test_trim_history_noop_when_short():
    msgs = _mk(turns=3)
    before = list(msgs)
    llm.trim_history(msgs, max_turns=8)
    assert msgs == before


def test_trim_history_does_not_leave_orphan_tool():
    msgs = [{"role": "system", "content": "s"}]
    msgs += [{"role": "user", "content": "u0"}, {"role": "assistant", "content": "", "tool_calls": [1]},
             {"role": "tool", "content": "r"}, {"role": "assistant", "content": "a0"}]
    msgs += [{"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"}]
    llm.trim_history(msgs, max_turns=1)
    # el primer mensaje tras system debe ser el user más reciente (no un tool huérfano)
    assert msgs[1]["role"] == "user" and msgs[1]["content"] == "u1"
