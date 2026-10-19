"""Offline-only developer smoke gate for the stacked orchestrator branches.

No external installations, API calls, browser actions, provider writes or E2E
account tests are triggered. Run from any location after installing dev deps.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline orchestrator validation (no E2E)")
    parser.add_argument("--full", action="store_true", help="Run entire upstream non-E2E pytest suite")
    parser.add_argument("--skip-lint", action="store_true", help="Skip Ruff if environment lacks it")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)
    root = args.repo.resolve()
    if not (root / "pyproject.toml").is_file() or not (root / "src").is_dir():
        parser.error("--repo must point at the chatgpt-web2api working tree")
    if not 5 <= args.timeout <= 3600:
        parser.error("timeout must be between 5 and 3600 seconds")

    tests = sorted((root / "tests").glob("test_orchestrator*.py"))
    if not args.full and not tests:
        parser.error("no orchestrator tests found")
    commands: list[tuple[str, list[str]]] = [
        ("compileall", [sys.executable, "-m", "compileall", "-q", "src"]),
        ("pytest", [sys.executable, "-m", "pytest", "-q", "-m", "not e2e"] +
         ([] if args.full else [str(t.relative_to(root)) for t in tests])),
    ]
    if not args.skip_lint:
        commands.append(("ruff", [sys.executable, "-m", "ruff", "check", "src/", "tests/"]))

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(root / "src"), env.get("PYTHONPATH", "")]))
    results = []
    for name, command in commands:
        start = time.monotonic()
        try:
            result = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                    timeout=args.timeout, check=False, env=env)
            entry = {"name": name, "exit_code": result.returncode,
                     "seconds": round(time.monotonic() - start, 2),
                     "stdout_tail": result.stdout[-3000:], "stderr_tail": result.stderr[-1500:]}
        except subprocess.TimeoutExpired:
            entry = {"name": name, "exit_code": 124,
                     "seconds": round(time.monotonic() - start, 2), "error": "timeout"}
        results.append(entry)
    ok = all(x["exit_code"] == 0 for x in results)
    print(json.dumps({"ok": ok, "mode": "full-non-e2e" if args.full else "orchestrator-only",
                      "network_actions": False, "results": results}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

