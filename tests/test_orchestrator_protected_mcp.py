"""Invalid private configuration must never select a legacy MCP route."""
import pytest

from chatgpt_web2api.orchestrator import mcp_control


def test_empty_private_label_cannot_fall_back_to_environment_db(monkeypatch):
    monkeypatch.setenv("CHATGPT_ORCHESTRATOR_DB", "synthetic-legacy.sqlite3")
    monkeypatch.setattr("sys.argv", ["observer", "--private-workspace", ""])
    calls = []
    monkeypatch.setattr(mcp_control, "run_server", lambda *a, **kw: calls.append(a))
    with pytest.raises(SystemExit):
        mcp_control.main()
    assert calls == []
