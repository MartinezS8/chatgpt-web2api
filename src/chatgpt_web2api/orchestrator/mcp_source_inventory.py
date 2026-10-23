"""Prepare a metadata-only local Codex MCP source map, without starting servers.

This helper is deliberately incomplete when source layers are ambiguous:
unknown origins remain "unknown" and are REJECTED by the live config guard.
Never print/read transport payloads, credentials or process arguments.
"""
from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

from .mcp_process_guard import _inspect
from .storage_hardening import reject_reparse_path


def _known_config_names(location: Path) -> set[str]:
    if not location.exists():
        return set()
    if location.is_symlink() or not location.is_file():
        raise ValueError("MCP config must be a regular local TOML file")
    reject_reparse_path(location, error_message="MCP config traverses reparse point")
    if location.stat().st_size > 1024 * 1024:
        raise ValueError("MCP config too large for bounded inventory")
    try:
        contents = tomllib.loads(location.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("MCP config TOML syntax could not be inspected") from exc
    if type(contents) is not dict:
        raise ValueError("MCP config format invalid")
    servers = contents.get("mcp_servers", {})
    if type(servers) is not dict:
        raise ValueError("MCP config servers table invalid")
    return set(servers)


def prepare_local_mcp_source_map(
    executable: str | Path, cwd: str | Path, output_path: str | Path, *,
    user_config: str | Path | None = None,
    project_config: str | Path | None = None,
) -> dict:
    exe, working = Path(executable).expanduser(), Path(cwd).expanduser()
    output = Path(output_path).expanduser()
    if (not exe.is_absolute() or exe.suffix.lower() != ".exe"
            or not exe.is_file() or not working.is_absolute()
            or not working.is_dir()):
        raise ValueError("native absolute EXE and existing CWD required")
    if not output.is_absolute() or output.exists() or not output.parent.is_dir():
        raise ValueError("MCP source map must be a new absolute file")
    reject_reparse_path(output.parent, error_message="MCP source map folder redirected")
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    config_user = Path(user_config).expanduser() if user_config else home / "config.toml"
    config_project = (
        Path(project_config).expanduser() if project_config
        else working / ".codex" / "config.toml"
    )
    user_names = _known_config_names(config_user)
    project_names = _known_config_names(config_project)
    discovered = _inspect(exe, working, (), 20)
    entries = []
    for name in sorted(discovered):
        # When the SAME name is in two layers, its effective origin cannot be
        # inferred from a name comparison alone.
        in_user, in_project = name in user_names, name in project_names
        source = (
            "unknown" if in_user == in_project else
            "user_config" if in_user else "project_config"
        )
        entries.append({"name": name, "source": source})
    value = {"schema_version": 1, "servers": entries}
    with output.open("x", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    return {
        "total_server_count": len(entries),
        "from_user_config": sum(s["source"] == "user_config" for s in entries),
        "from_project_config": sum(s["source"] == "project_config" for s in entries),
        "unresolved_source_count": sum(s["source"] == "unknown" for s in entries),
        "ready_for_live_guard": all(s["source"] != "unknown" for s in entries),
        "names_or_transport_values_emitted": False,
        "app_server_started": False,
        "provider_turn_started": False,
    }
