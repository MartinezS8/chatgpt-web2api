"""Read-only, fail-closed App Server MCP/app response validation.

These methods query the running process before thread/start. On supported
versions the actual responses may contain disabled entries, but a version
whose returned data cannot prove disabled tools MUST be investigated locally
rather than silently accepted as an empty tool set.
"""
from __future__ import annotations


def check_mcp_status(result: dict) -> dict:
    if type(result) is not dict or type(result.get("data")) is not list:
        raise ValueError("unexpected MCP status response: cannot prove tool absence")
    if result.get("nextCursor") is not None:
        raise ValueError("paginated MCP status cannot establish completeness")
    rows = result["data"]
    if len(rows) > 128:
        raise ValueError("MCP status exceeds allowed inventory")
    for row in rows:
        if type(row) is not dict:
            raise ValueError("malformed MCP status entry")
        # Empty result is the straightforward case. Nonempty disabled
        # entries need BOTH explicit disabled state and empty tools.
        if row.get("enabled") is not False or row.get("tools") != []:
            raise PermissionError("MCP status includes unverified callable server or tools")
    return {"mcp_status_checked": True, "mcp_callables_found": False,
            "mcp_status_entries": len(rows)}


def check_installed_apps(result: dict) -> dict:
    if type(result) is not dict or type(result.get("apps")) is not list:
        raise ValueError("installed app state could not be verified")
    if len(result["apps"]) > 128:
        raise ValueError("app inventory is unexpectedly large")
    for app in result["apps"]:
        if (type(app) is not dict or type(app.get("callable")) is not bool
                or app["callable"] is not False):
            raise PermissionError("app is callable or its tool state is unknown")
    return {"installed_apps_checked": True, "callable_apps_found": False,
            "installed_app_count": len(result["apps"]),
            "built_in_tools_absent_verified": False}


def require_external_tools_disabled(mcp: dict, apps: dict) -> dict:
    return {**check_mcp_status(mcp), **check_installed_apps(apps),
            "strict_zero_tools_verified": False,
            "readonly_builtin_tool_risk_remains": True}
