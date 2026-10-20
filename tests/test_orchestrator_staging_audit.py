"""Read-only staging inspection; intentionally never deletes any file."""
from __future__ import annotations

from pathlib import Path

import pytest

from chatgpt_web2api.orchestrator.staging_audit import inspect_staging_directory


def test_candidates_are_only_observed(tmp_path):
    a = tmp_path / ".staged-old"
    a.write_bytes(b"private")
    b = tmp_path / ".sqlite-snapshot-old"
    b.write_bytes(b"backup")
    (tmp_path / "unrelated").write_bytes(b"safe")
    found = inspect_staging_directory(tmp_path)
    assert [Path(item.path).name for item in found] == [
        ".sqlite-snapshot-old", ".staged-old",
    ]
    assert all(item.disposition == "manual_review_only" for item in found)
    assert a.read_bytes() == b"private"
    assert b.read_bytes() == b"backup"


def test_symlink_is_not_a_candidate(tmp_path):
    source = tmp_path / "secret"
    source.write_text("data")
    link = tmp_path / ".staged-link"
    try:
        link.symlink_to(source)
    except (NotImplementedError, OSError):
        pytest.skip("symlink unavailable")
    assert inspect_staging_directory(tmp_path) == ()


def test_missing_folder_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        inspect_staging_directory(tmp_path / "missing")


def test_nested_candidate_is_not_scanned(tmp_path):
    child = tmp_path / "child"
    child.mkdir()
    (child / ".staged-nested").write_text("data")
    assert inspect_staging_directory(tmp_path) == ()


def test_active_writer_candidate_not_removed(tmp_path):
    candidate = tmp_path / ".staged-active"
    with candidate.open("wb") as handle:
        handle.write(b"live")
        handle.flush()
        seen = inspect_staging_directory(tmp_path)
        assert len(seen) == 1
        assert seen[0].disposition == "manual_review_only"
        assert candidate.exists()
    assert candidate.read_bytes() == b"live"
