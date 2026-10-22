"""Explicit, offline Codex CLI version and generated App Server schema inspection.

Does not start app-server, log in, call model/list, create threads, or send turns.
A trusted operator must select the absolute native executable path deliberately.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from .storage_hardening import reject_reparse_path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_codex_schema(
    executable: str | Path, output_directory: str | Path, *,
    expected_version: str | None = None,
) -> dict:
    """Only run '--version' and 'app-server generate-json-schema' on a native exe.

    No process is started using an ambient PATH lookup, shell, fallbacks,
    remote UI sessions, model queries, or authentication commands.
    The output directory must be new; existing files are never replaced.
    """
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise OSError("Codex readiness requires native Windows and Python 3.12")
    exe = Path(executable).expanduser()
    target = Path(output_directory).expanduser()
    if (not exe.is_absolute() or exe.suffix.lower() != ".exe"
            or not exe.is_file() or exe.is_symlink()):
        raise ValueError("absolute native Codex .exe path required")
    reject_reparse_path(exe, error_message="Codex executable traverses reparse point")
    if (not target.is_absolute() or target.exists() or target.is_symlink()
            or not target.parent.is_dir()):
        raise ValueError("output must be a NEW directory under an existing parent")
    reject_reparse_path(
        target, error_message="Codex schema output traverses reparse point",
    )

    version_run = subprocess.run(
        [str(exe), "--version"], capture_output=True, text=True,
        check=True, timeout=20,
    )
    version = version_run.stdout.strip()
    if (not version or len(version) > 200 or "\n" in version
            or not version.lower().startswith("codex")):
        raise ValueError("unrecognized Codex executable version response")
    if expected_version is not None and version != expected_version:
        raise ValueError("installed Codex version differs from explicitly expected version")

    binary_sha = _file_sha256(exe)
    target.mkdir(exist_ok=False)
    subprocess.run(
        [str(exe), "app-server", "generate-json-schema", "--out", str(target)],
        capture_output=True, text=True, check=True, timeout=120,
    )
    schema_files = sorted(target.rglob("*.json"))
    if not 1 <= len(schema_files) <= 300:
        raise ValueError("Codex schema output missing or unexpectedly large")
    manifest = []
    for file in schema_files:
        reject_reparse_path(file, error_message="generated schema traverses reparse point")
        if not file.is_file() or file.stat().st_size > 25_000_000:
            raise ValueError("invalid generated Codex schema file")
        with file.open("r", encoding="utf-8") as stream:
            parsed = json.load(stream)
        if type(parsed) is not dict:
            raise ValueError("Codex output is not a JSON Schema object")
        manifest.append({
            "path": file.relative_to(target).as_posix(),
            "sha256": _file_sha256(file),
        })

    report = {
        "codex_version": version,
        "codex_binary_sha256": binary_sha,
        "generated_json_schema": manifest,
        "installed_schema_inspected": True,
        "account_available_models_checked": False,
        "available_thinking_efforts_checked": False,
        "no_silent_model_fallback_permitted": True,
        "real_codex_worker_started": False,
        "live_provider_authorized": False,
        "production_authorized": False,
    }
    (target / "offline-readiness.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8",
    )
    return report
