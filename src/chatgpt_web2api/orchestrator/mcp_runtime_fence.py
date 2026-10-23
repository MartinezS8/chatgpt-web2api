"""Read-only, fail-closed App Server MCP/app response validation.

The MCP status shape follows the versioned App Server schema: tools are an
object keyed by tool name, and status rows do not carry an ``enabled`` field.
Callers must first verify process-scoped MCP and Apps configuration before
asking for status, since status discovery can initialize MCP connections.
"""
from __future__ import annotations

_AUTH_STATUSES = frozenset({"unknown", "unsupported", "notLoggedIn", "bearerToken", "oAuth"})
_INACTIVE_RUNTIME_STATUSES = frozenset({"notStarted", "disabled"})
_RUNTIME_STATUSES = _INACTIVE_RUNTIME_STATUSES | frozenset({
    "starting", "connected", "authenticationRequired", "failed", "cancelled",
})


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
        name = row.get("name")
        if not isinstance(name, str) or not name or len(name) > 128:
            raise ValueError("MCP status identity missing or malformed")
        auth_status = row.get("authStatus")
        if type(auth_status) is not str or auth_status not in _AUTH_STATUSES:
            raise ValueError("MCP auth status missing or malformed")
        tools = row.get("tools")
        if type(tools) is not dict:
            raise ValueError("MCP tool catalog does not match App Server schema")
        if tools:
            raise PermissionError("MCP status includes unverified callable server or tools")
        resources = row.get("resources")
        templates = row.get("resourceTemplates")
        if type(resources) is not list or type(templates) is not list:
            raise ValueError("MCP resource catalog does not match App Server schema")
        if resources or templates:
            raise PermissionError("MCP status includes unverified resources")
        runtime = row.get("runtimeStatus")
        if (runtime is not None
                and (type(runtime) is not str or runtime not in _RUNTIME_STATUSES)):
            raise ValueError("MCP runtime status missing or unknown")
        if runtime is not None and runtime not in _INACTIVE_RUNTIME_STATUSES:
            raise PermissionError("MCP status reports an active or uncertain runtime")
        if row.get("toolsError") is not None:
            raise PermissionError("MCP tool discovery did not return a verified catalog")
    return {
        "mcp_status_checked": True,
        "mcp_callables_found": False,
        "mcp_status_entries": len(rows),
    }


def check_installed_apps(result: dict) -> dict:
    if type(result) is not dict or type(result.get("apps")) is not list:
        raise ValueError("installed app state could not be verified")
    if len(result["apps"]) > 128:
        raise ValueError("app inventory is unexpectedly large")
    for app in result["apps"]:
        if (type(app) is not dict or not isinstance(app.get("id"), str)
                or not app["id"] or type(app.get("enabled")) is not bool
                or type(app.get("callable")) is not bool):
            raise ValueError("installed app state is missing required schema fields")
        if app["enabled"] is not False or app["callable"] is not False:
            raise PermissionError("app is enabled or callable")
    return {"installed_apps_checked": True, "callable_apps_found": False,
            "enabled_apps_found": False,
            "installed_app_count": len(result["apps"]),
            "built_in_tools_absent_verified": False}


def require_external_tools_disabled(mcp: dict, apps: dict) -> dict:
    app_state = check_installed_apps(apps)
    return {**check_mcp_status(mcp), **app_state,
            "strict_zero_tools_verified": False,
            "readonly_builtin_tool_risk_remains": True}
