"""Local, read-only orchestrator test gate with exact Git HEAD preflight.

No provider/browser calls are directly made here. However pytest can contain
network-capable tests: this program does NOT enforce operating-system network
isolation, and never represents a local run as a signed CI attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_SHA = re.compile(r"[0-9a-f]{40}\Z")


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        timeout=15, check=False,
    )
    if result.returncode:
        raise ValueError("Git metadata unavailable; no tests were executed")
    return result.stdout.strip()


def _preflight(root: Path, expected_sha: str | None, strict: bool) -> dict:
    if not (root / "pyproject.toml").is_file() or not (root / "src").is_dir():
        raise ValueError("--repo must point to a chatgpt-web2api working tree")
    if expected_sha is not None and not _SHA.fullmatch(expected_sha):
        raise ValueError("--expected-sha must be an exact lowercase 40-character Git SHA")
    if strict and expected_sha is None:
        raise ValueError("--strict requires --expected-sha")
    top = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    if top != root:
        raise ValueError("--repo must be the Git working tree root")
    head = _git(root, "rev-parse", "--verify", "HEAD")
    if not _SHA.fullmatch(head):
        raise ValueError("Git HEAD is not a valid commit SHA")
    clean = not bool(_git(root, "status", "--porcelain=v1", "--untracked-files=all"))
    if expected_sha is not None and head != expected_sha:
        raise ValueError("Git HEAD differs from --expected-sha; tests not started")
    if strict and not clean:
        raise ValueError("Git working tree is dirty; strict tests not started")
    return {"head_sha": head, "expected_sha": expected_sha,
            "sha_matched": expected_sha is not None,
            "worktree_clean_at_start": clean,
            "strict_preflight": strict}


def _invoke(name: str, command: list[str], root: Path, env: dict,
            timeout: int, diagnostics: bool) -> dict:
    start = time.monotonic()
    try:
        result = subprocess.run(
            command, cwd=root, capture_output=True, text=True,
            timeout=timeout, check=False, env=env,
        )
        out, err, code = result.stdout, result.stderr, result.returncode
        entry = {"name": name, "exit_code": code,
                 "duration_seconds": round(time.monotonic() - start, 2),
                 "stdout_sha256": hashlib.sha256(out.encode()).hexdigest(),
                 "stderr_sha256": hashlib.sha256(err.encode()).hexdigest()}
        if diagnostics:
            # Diagnostics can contain test data or secrets: opt in explicitly.
            entry["stdout_tail"] = out[-3000:]
            entry["stderr_tail"] = err[-1500:]
        return entry
    except subprocess.TimeoutExpired:
        return {"name": name, "exit_code": 124,
                "duration_seconds": round(time.monotonic() - start, 2),
                "error_type": "timeout"}
    except OSError:
        return {"name": name, "exit_code": 127,
                "duration_seconds": round(time.monotonic() - start, 2),
                "error_type": "unavailable_command"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local non-E2E validation, not a CI attestation")
    parser.add_argument("--full", action="store_true", help="Entire non-E2E pytest suite")
    parser.add_argument("--skip-lint", action="store_true", help="Smoke-only mode; never a complete gate")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--expected-sha", help="Exact Git HEAD required for this run")
    parser.add_argument("--strict", action="store_true", help="Require exact SHA, clean tree and Ruff")
    parser.add_argument("--diagnostics", action="store_true", help="Include raw output tails (may contain secrets)")
    args = parser.parse_args(argv)
    root = args.repo.expanduser().resolve()
    metadata = {"mode": "full-non-e2e" if args.full else "orchestrator-only",
                "validation": "local_unattested",
                "network_isolation_verified": False,
                "live_provider_capabilities_verified": False,
                "start_utc": datetime.now(UTC).isoformat(),
                "platform": platform.system(), "python": platform.python_version(),
                "diagnostics_enabled": args.diagnostics}
    try:
        if not 5 <= args.timeout <= 3600:
            raise ValueError("--timeout must be between 5 and 3600 seconds")
        if args.strict and args.skip_lint:
            raise ValueError("--strict cannot be combined with --skip-lint")
        metadata.update(_preflight(root, args.expected_sha, args.strict))
        tests = sorted((root / "tests").glob("test_orchestrator*.py"))
        if not args.full and not tests:
            raise ValueError("no orchestrator tests found")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({**metadata, "ok": False, "tests_started": False,
                          "error": str(exc)}, sort_keys=True))
        return 2

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(root / "src"),
                                                      env.get("PYTHONPATH", "")]))
    # Even if the operator has globally opted into live E2E, this gate cannot
    # forward that opt-in. The pytest marker excludes e2e a second time.
    env["W2A_E2E_RUN"] = "0"
    commands = [
        ("compileall", [sys.executable, "-m", "compileall", "-q", "src"]),
        ("pytest", [sys.executable, "-m", "pytest", "-q", "-m", "not e2e"] +
         ([] if args.full else [str(t.relative_to(root)) for t in tests])),
    ]
    if not args.skip_lint:
        commands.append(("ruff", [sys.executable, "-m", "ruff", "check", "src/", "tests/"]))
    checks = [_invoke(n, cmd, root, env, args.timeout, args.diagnostics)
              for n, cmd in commands]
    passed = all(entry["exit_code"] == 0 for entry in checks)
    complete = passed and args.strict and args.full and not args.skip_lint
    print(json.dumps({**metadata, "ok": passed,
                      "local_gate_complete": complete,
                      "tests_started": True, "checks": checks,
                      "skipped_checks": ["ruff"] if args.skip_lint else [],
                      "note": "Local Git state only; independent GitHub CI/review still required"},
                     ensure_ascii=False, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
