"""Process-scoped, fail-closed Codex MCP configuration verification.

Only calls 'mcp list --json' and 'features list' (configuration
introspection). It never starts an MCP server, an app-server, a thread, or a
turn. A source map must be operator-reviewed; this module cannot itself
authenticate config provenance.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .local_codex_discovery import _pairs_no_duplicates
from .storage_hardening import reject_reparse_path

_MAX_JSON = 256 * 1024
_ALLOWED_TRANSPORTS = frozenset({"stdio", "streamable_http", "http", "sse"})
_ALLOWED_SOURCES = frozenset({"user_config", "project_config", "cli", "plugin"})


@dataclass(frozen=True)
class VerifiedMcpArgs:
    """Never print args: they contain local server and plugin identifiers."""

    args: tuple[str, ...]
    server_count: int
    previously_enabled_count: int
    remaining_enabled_count: int

    def sanitized(self) -> dict:
        return {
            "mcp_config_probe_passed": True,
            "mcp_servers_discovered": self.server_count,
            "mcp_servers_initially_enabled": self.previously_enabled_count,
            "mcp_servers_remaining_enabled": self.remaining_enabled_count,
            "process_scoped_only": True,
            "apps_feature_disabled_verified": True,
            "effective_app_server_mcp_checked": False,
            "built_in_tools_absent_verified": False,
            "live_turn_authorized": False,
        }


def _decode_json(raw: str) -> object:
    if type(raw) is not str or not 2 <= len(raw.encode("utf-8")) <= _MAX_JSON:
        raise ValueError("bounded Codex MCP metadata required")
    try:
        return json.loads(raw, object_pairs_hook=_pairs_no_duplicates)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("malformed Codex MCP metadata") from exc


def _safe_name(value: object) -> str:
    if (type(value) is not str or not 1 <= len(value) <= 128
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("invalid MCP name or plugin identifier")
    return value


def parse_mcp_list(raw: str) -> dict[str, bool]:
    """Read effective names and enabled flags, never copy transport values."""
    data = _decode_json(raw)
    if type(data) is dict:
        data = data.get("servers")
    if type(data) is not list or len(data) > 128:
        raise ValueError("Codex MCP list must be a bounded array")
    result: dict[str, bool] = {}
    for item in data:
        if type(item) is not dict:
            raise ValueError("MCP item must be an object")
        name = _safe_name(item.get("name"))
        if name in result:
            raise ValueError("duplicate MCP server identity")
        enabled = item.get("enabled")
        if type(enabled) is not bool:
            raise ValueError("missing or malformed enabled flag")
        transport = item.get("transport")
        kind = transport if type(transport) is str else (
            transport.get("type") if type(transport) is dict else None
        )
        if kind not in _ALLOWED_TRANSPORTS:
            raise ValueError("missing or unknown MCP transport")
        result[name] = enabled
    return result


def _config_key_segment(value: str, *, plugin_id: bool = False) -> str:
    # Codex -c accepts bare config-key segments here; quoted MCP names are
    # accepted by the CLI but silently do not override these effective entries.
    pattern = (
        r"[A-Za-z0-9_-]+(?:@[A-Za-z0-9_-]+)?"
        if plugin_id else r"[A-Za-z0-9_-]+"
    )
    if re.fullmatch(pattern, value) is None:
        raise ValueError("MCP identity cannot be represented as a safe Codex override")
    return value


def _source_map(path: str | Path, actual: dict[str, bool]) -> tuple[str, ...]:
    file = Path(path).expanduser()
    if not file.is_absolute() or not file.is_file() or file.is_symlink():
        raise ValueError("existing absolute MCP source map required")
    reject_reparse_path(file, error_message="MCP source map traverses reparse path")
    if not 2 <= file.stat().st_size <= 32 * 1024:
        raise ValueError("MCP source map exceeds strict size limits")
    data = _decode_json(file.read_text(encoding="utf-8"))
    if (type(data) is not dict or set(data) != {"schema_version", "servers"}
            or data["schema_version"] != 1 or type(data["servers"]) is not list):
        raise ValueError("MCP source map version/structure invalid")
    if len(data["servers"]) != len(actual):
        raise ValueError("MCP source map does not cover exact effective inventory")
    seen: set[str] = set()
    flags: list[str] = []
    for entry in data["servers"]:
        if type(entry) is not dict:
            raise ValueError("MCP provenance entry must be a JSON object")
        name = _safe_name(entry.get("name"))
        origin = entry.get("source")
        if name in seen or name not in actual or origin not in _ALLOWED_SOURCES:
            raise ValueError("unknown, duplicate or unclassified MCP source")
        seen.add(name)
        config_name = _config_key_segment(name)
        if origin == "plugin":
            if set(entry) != {"name", "source", "plugin_id"}:
                raise ValueError("plugin MCP requires exact plugin identity")
            plugin = _config_key_segment(_safe_name(entry.get("plugin_id")), plugin_id=True)
            if actual[name]:
                flags += [
                    "-c", f"plugins.{plugin}.mcp_servers.{config_name}.enabled=false",
                    "-c", f"plugins.{plugin}.enabled=false",
                ]
        else:
            if set(entry) != {"name", "source"}:
                raise ValueError("regular MCP source must not include plugin metadata")
            if actual[name]:
                flags += ["-c", f"mcp_servers.{config_name}.enabled=false"]
    if seen != set(actual):
        raise ValueError("unclassified MCP server in effective inventory")
    return tuple(flags)


def _inspect(exe: Path, cwd: Path, flags: tuple[str, ...], timeout: int) -> dict[str, bool]:
    try:
        proc = subprocess.run(
            [str(exe), *flags, "mcp", "list", "--json"],
            cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Codex MCP configuration probe could not finish") from exc
    if proc.returncode != 0:
        # Do not expose potentially sensitive stderr (transport URL/command).
        raise RuntimeError("Codex MCP configuration rejected the process-scoped policy")
    return parse_mcp_list(proc.stdout)


def _inspect_apps_disabled(
    exe: Path, cwd: Path, flags: tuple[str, ...], timeout: int,
) -> None:
    """Require Codex's effective process-scoped Apps feature to be false."""
    try:
        proc = subprocess.run(
            [str(exe), *flags, "features", "list"],
            cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Codex Apps feature probe could not finish") from exc
    if proc.returncode != 0:
        raise RuntimeError("Codex Apps feature policy could not be verified")
    if type(proc.stdout) is not str or len(proc.stdout) > 64 * 1024:
        raise ValueError("Codex Apps feature output is missing or excessive")
    rows = []
    for line in proc.stdout.splitlines():
        fields = line.split()
        if fields and fields[0] == "apps":
            rows.append(fields)
    if (len(rows) != 1 or len(rows[0]) != 3
            or rows[0][2] not in {"true", "false"}):
        raise ValueError("Codex Apps feature state is missing or malformed")
    if rows[0][2] != "false":
        raise PermissionError("Codex Apps feature remains enabled after process override")


def verify_mcp_disabled(
    executable: str | Path, cwd: str | Path, source_map: str | Path, *,
    timeout: int = 20,
) -> VerifiedMcpArgs:
    """Verify process-local MCP and Apps disablement without starting a server."""
    exe, root = Path(executable).expanduser(), Path(cwd).expanduser()
    if not exe.is_absolute() or not exe.is_file() or exe.suffix.lower() != ".exe":
        raise ValueError("explicit existing native Codex EXE required")
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("explicit existing pilot scratch required")
    if type(timeout) is not int or not 2 <= timeout <= 45:
        raise ValueError("bounded CLI introspection timeout required")
    reject_reparse_path(exe, error_message="Codex binary traverses reparse path")
    reject_reparse_path(root, error_message="scratch traverses reparse path")
    before = _inspect(exe, root, (), timeout)
    flags = (*_source_map(source_map, before), "-c", "features.apps=false")
    after = _inspect(exe, root, flags, timeout)
    if any(after.values()) or any(after.get(name, False) for name in before):
        raise PermissionError("Codex MCPs remain enabled after process overrides")
    _inspect_apps_disabled(exe, root, flags, timeout)
    return VerifiedMcpArgs(flags, len(before), sum(before.values()), 0)
