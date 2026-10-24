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

from .mcp_config_snapshot import capture_snapshot, source_fingerprint
from .mcp_process_guard import _decode_json, _inspect
from .storage_hardening import reject_reparse_path


def _read_config(location: Path) -> dict:
    if not location.exists():
        return {}
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
    return contents


def _known_config_names(location: Path) -> set[str]:
    servers = _read_config(location).get("mcp_servers", {})
    if type(servers) is not dict:
        raise ValueError("MCP config servers table invalid")
    return set(servers)


def _plugin_candidates(cache: Path, config: dict) -> tuple[dict[str, list[str]], dict[Path, str], int]:
    """Use exact configured IDs and declared manifest references; never guess versions."""
    candidates: dict[str, list[str]] = {}
    evidence = {}
    rejected = 0
    plugins = config.get("plugins", {})
    if type(plugins) is not dict or len(plugins) > 128:
        raise ValueError("bounded plugin config table required")
    for identity, settings in plugins.items():
        if type(settings) is not dict or settings.get("enabled") is not True:
            continue
        if identity.count("@") != 1:
            continue
        name, marketplace = identity.split("@")
        # These are directory components, never caller-selected relative paths.
        if any(not part or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in part)
               for part in (name, marketplace)):
            continue
        folder = cache / marketplace / name
        reject_reparse_path(folder, error_message="plugin cache traverses reparse point")
        if not folder.exists():
            continue
        versions = list(folder.iterdir())
        if len(versions) > 32:
            raise ValueError("too many plugin versions to inspect safely")
        for root in versions:
            if not root.is_dir():
                continue
            manifest = root / ".codex-plugin" / "plugin.json"
            try:
                manifest_hash = source_fingerprint(manifest)
            except (ValueError, OSError):
                # A redirected/unsupported cache entry is never evidence. Other
                # independent entries can be inspected; its source stays unknown.
                rejected += 1
                continue
            if manifest_hash is None:
                continue
            value = _decode_json(manifest.read_text(encoding="utf-8"))
            if (type(value) is not dict or value.get("name") != name
                    or value.get("mcpServers") not in ("./.mcp.json", ".mcp.json")):
                continue
            mcp = root / ".mcp.json"
            try:
                mcp_hash = source_fingerprint(mcp)
            except (ValueError, OSError):
                rejected += 1
                continue
            if mcp_hash is None:
                continue
            data = _decode_json(mcp.read_text(encoding="utf-8"))
            servers = data.get("mcpServers") if type(data) is dict else None
            if type(servers) is not dict or len(servers) > 128:
                raise ValueError("plugin MCP manifest invalid")
            evidence.update({manifest: manifest_hash, mcp: mcp_hash})
            for server in servers:
                candidates.setdefault(server, []).append(identity)
    if any(source_fingerprint(p) != digest for p, digest in evidence.items()):
        raise ValueError("plugin metadata changed during inventory")
    return candidates, evidence, rejected


def prepare_local_mcp_source_map(
    executable: str | Path, cwd: str | Path, output_path: str | Path, *,
    user_config: str | Path | None = None,
    project_config: str | Path | None = None,
    plugin_cache: str | Path | None = None,
    bind_snapshot: bool = False,
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
    initial_hashes = {str(p): source_fingerprint(p) for p in (config_user, config_project)}
    user_names = _known_config_names(config_user)
    project_names = _known_config_names(config_project)
    # Plugin scanning is explicit, so old callers retain the conservative v1 behavior.
    candidates, evidence, rejected = ({}, {}, 0) if plugin_cache is None else _plugin_candidates(
        Path(plugin_cache).expanduser(), _read_config(config_user),
    )
    sources = [config_user, config_project, *evidence]
    initial_hashes.update({str(p): digest for p, digest in evidence.items()})
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
        entry = {"name": name, "source": source}
        origins = candidates.get(name, [])
        if source == "unknown" and not in_user and not in_project and len(origins) == 1:
            entry.update(source="plugin", plugin_id=origins[0])
        elif origins:
            # An overlapping normal config and plugin manifest is ambiguous.
            entry["source"] = "unknown"
        entries.append(entry)
    value = {"schema_version": 1, "servers": entries}
    if {str(p): source_fingerprint(p) for p in sources} != initial_hashes:
        raise ValueError("MCP configuration changed during inventory; no map written")
    if bind_snapshot:
        value.update(schema_version=2, snapshot=capture_snapshot(exe, working, discovered, sources))
        if ({str(p): source_fingerprint(p) for p in sources} != initial_hashes
                or _inspect(exe, working, (), 20) != discovered):
            raise ValueError("MCP configuration changed during inventory; no map written")
    with output.open("x", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    return {
        "total_server_count": len(entries),
        "from_user_config": sum(s["source"] == "user_config" for s in entries),
        "from_project_config": sum(s["source"] == "project_config" for s in entries),
        "from_plugin_manifest": sum(s["source"] == "plugin" for s in entries),
        "snapshot_bound": bind_snapshot,
        "rejected_plugin_candidates": rejected,
        "unresolved_source_count": sum(s["source"] == "unknown" for s in entries),
        "ready_for_live_guard": all(s["source"] != "unknown" for s in entries),
        "names_or_transport_values_emitted": False,
        "app_server_started": False,
        "provider_turn_started": False,
    }
