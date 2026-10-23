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
        {"data": [{
            "name": "fixture", "authStatus": "unsupported",
            "resourceTemplates": [], "resources": [], "tools": {},
            "runtimeStatus": None,
        }], "nextCursor": None},
        {"apps": [{"id": "fixture", "enabled": False, "callable": False}]},
    )
    assert data["mcp_status_entries"] == 1 and data["installed_app_count"] == 1


@pytest.mark.parametrize("result", [
    {"data": [{
        "name": "fixture", "authStatus": "unsupported",
        "resourceTemplates": [], "resources": [],
        "tools": {"bad": {"name": "bad"}},
    }], "nextCursor": None},
    {"data": [{
        "name": "fixture", "authStatus": "unsupported",
        "resourceTemplates": [], "resources": [], "tools": [],
    }], "nextCursor": None},
    {"data": [{
        "name": "fixture", "authStatus": "unsupported",
        "resourceTemplates": [], "resources": [], "tools": {},
        "runtimeStatus": "connected",
    }], "nextCursor": None},
    {"data": [{
        "name": "fixture", "authStatus": "unsupported",
        "resourceTemplates": [], "resources": [], "tools": {},
        "runtimeStatus": "failed",
    }], "nextCursor": None},
    {"data": [], "nextCursor": "more"},
    {"data": "invalid"},
])
def test_unknown_or_enabled_mcp_is_rejected(result):
    with pytest.raises((PermissionError, ValueError)):
        require_external_tools_disabled(result, {"apps": []})


@pytest.mark.parametrize("result", [
    {"data": [{"name": "fixture", "authStatus": "unsupported",
               "resourceTemplates": [], "resources": [], "tools": {"bad": 1}}],
     "nextCursor": None},
    {"data": [{"name": "fixture", "authStatus": "unsupported",
               "resourceTemplates": [], "resources": [{"uri": "x"}], "tools": {}}],
     "nextCursor": None},
    {"data": [{"name": "fixture", "authStatus": "unknown",
               "resourceTemplates": [1], "resources": [], "tools": {}}],
     "nextCursor": None},
    {"data": [{"name": "fixture", "authStatus": "unsupported",
               "resourceTemplates": [], "resources": [], "tools": {},
               "runtimeStatus": "futureState"}], "nextCursor": None},
    {"data": [{"name": "fixture", "authStatus": [],
               "resourceTemplates": [], "resources": [], "tools": {}}],
     "nextCursor": None},
    {"data": [{"name": "fixture", "authStatus": "unsupported",
               "resourceTemplates": [], "resources": [], "tools": {},
               "runtimeStatus": {}}], "nextCursor": None},
])
def test_malformed_or_nonempty_schema_catalog_fails_closed(result):
    with pytest.raises((PermissionError, ValueError)):
        require_external_tools_disabled(result, {"apps": []})


@pytest.mark.parametrize("apps", [
    {"apps": [{"enabled": True, "callable": True}]},
    {"apps": [{"id": "fixture", "enabled": False}]},
    {"apps": [{"id": "fixture", "enabled": True, "callable": False}]},
    {"apps": [{"id": "fixture", "enabled": False, "callable": True}]},
    {"apps": "unavailable"},
])
def test_unknown_or_callable_apps_are_rejected(apps):
    with pytest.raises((PermissionError, ValueError)):
        require_external_tools_disabled({"data": [], "nextCursor": None}, apps)
