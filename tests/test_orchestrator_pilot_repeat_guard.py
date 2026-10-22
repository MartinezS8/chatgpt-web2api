"""SQLite one-turn replay reservations cannot silently overwrite an attempt."""
from __future__ import annotations

import pytest

from chatgpt_web2api.orchestrator.pilot_repeat_guard import reserve_local_pilot_once


def test_duplicated_fingerprint_refused_across_different_receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cwd = tmp_path / "scratch"
    cwd.mkdir()
    args = {
        "cwd": cwd, "model_slug": "model", "effort": "high",
        "prompt_sha256": "a" * 64, "codex_binary_sha256": "b" * 64,
    }
    reserve_local_pilot_once(receipt_dir=tmp_path / "one", **args)
    with pytest.raises(PermissionError, match="already recorded"):
        reserve_local_pilot_once(receipt_dir=tmp_path / "two", **args)
    reserve_local_pilot_once(
        receipt_dir=tmp_path / "different-prompt",
        **{**args, "prompt_sha256": "c" * 64},
    )
