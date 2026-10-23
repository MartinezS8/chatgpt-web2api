"""No real app-server/tool invocation in MCP/app readiness tests."""
from __future__ import annotations

import pytest

from chatgpt_web2api.orchestrator.mcp_runtime_fence import require_external_tools_disabled


def test_no_external_tools_is_not_complete_built_in_tool_proof():
    a = require_external_tools_disabled(
        {"data": [], "nextCursor": None}, {"apps": []},
    )
    assert a["mcp_status_checked"] is True
    assert a["installed_apps_checked"] is True
    assert a["strict_zero_tools_verified"] is False
    assert a["readonly_builtin_tool_risk_remains"] is True


def test_explicitly_disabled_mcp_and_non_callable_apps_are_accepted():
    data = require_external_tools_disabled(
        {"data": [{"enabled": False, "tools": []}], "nextCursor": None},
        {"apps": [{"enabled": False, "callable": False}]},
    )
    assert data["mcp_status_entries"] == 1 and data["installed_app_count"] == 1


@pytest.mark.parametrize("result", [
    {"data": [{"enabled": True, "tools": []}], "nextCursor": None},
    {"data": [{"tools": []}], "nextCursor": None},
    {"data": [{"enabled": False, "tools": [{"name": "bad"}]}], "nextCursor": None},
    {"data": [], "nextCursor": "more"},
    {"data": "invalid"},
])
def test_unknown_or_enabled_mcp_is_rejected(result):
    with pytest.raises((PermissionError, ValueError)):
        require_external_tools_disabled(result, {"apps": []})


@pytest.mark.parametrize("apps", [
    {"apps": [{"enabled": True, "callable": True}]},
    {"apps": [{"enabled": False}]},
    {"apps": "unavailable"},
])
def test_unknown_or_callable_apps_are_rejected(apps):
    with pytest.raises((PermissionError, ValueError)):
        require_external_tools_disabled({"data": [], "nextCursor": None}, apps)
