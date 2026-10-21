"""Single supported interpreter and Windows diagnostic workflow contract."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_package_and_linter_support_only_python312():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["requires-python"] == ">=3.12,<3.13"
    classifiers = config["project"]["classifiers"]
    assert "Programming Language :: Python :: 3.12" in classifiers
    assert "Programming Language :: Python :: 3.11" not in classifiers
    assert config["tool"]["ruff"]["target-version"] == "py312"


def test_both_workflows_keep_windows_strict_build_and_secret_scan():
    for name in ("ci.yml", "orchestrator-branch-validation.yml"):
        workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "windows-latest" in workflow
        for unsupported in ("ubuntu-latest", "macos-latest", "3.11", "matrix."):
            assert unsupported not in workflow
        assert "--full --strict" in workflow
        assert "--expected-sha" in workflow
        assert "scan_secrets_windows.ps1" in workflow
        assert "python -m build" in workflow
        assert "3.12" in workflow
