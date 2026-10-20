"""CLI staging inspection does not touch files without explicit opt-in."""
from __future__ import annotations

import os

import pytest

from chatgpt_web2api.orchestrator.cli import build_parser, execute
from chatgpt_web2api.orchestrator.stage_maintenance import create_managed_stage, stage_guard


def test_staging_cli_defaults_read_only_and_preserves_legacy(tmp_path):
    with stage_guard(tmp_path):
        fd, staged = create_managed_stage(tmp_path, "staged")
        os.close(fd)
    legacy = tmp_path / ".staged-legacy-data"
    legacy.write_bytes(b"unknown")
    parser = build_parser()
    result = execute(parser.parse_args([
        "staging-audit", "--root", str(tmp_path), "--older-than-hours", "0"
    ]))
    assert result["dry_run"] is True
    assert result["removed"] == []
    assert staged.exists() and legacy.exists()
    assert result["remote_actions_permitted"] is False


def test_staging_cli_rejects_zero_age_deletion(tmp_path):
    parser = build_parser()
    args = parser.parse_args([
        "staging-audit", "--root", str(tmp_path), "--older-than-hours", "0",
        "--delete-managed-v2"
    ])
    with pytest.raises(ValueError, match="minimum age"):
        execute(args)


@pytest.mark.skipif(os.name != "nt", reason="Windows NTFS long-path probe only")
def test_windows_long_path_is_probed_without_changing_user_data(tmp_path):
    """Reports unsupported native long paths explicitly rather than claiming support."""
    nested = tmp_path
    try:
        while len(str(nested)) < 270:
            nested = nested / ("long_segment_" + "x" * 20)
        nested.mkdir(parents=True)
        probe = nested / "probe.txt"
        probe.write_text("synthetic", encoding="utf-8")
        assert probe.read_text(encoding="utf-8") == "synthetic"
    except OSError as exc:
        pytest.skip(f"Windows long paths unavailable on this runner: {exc}")
