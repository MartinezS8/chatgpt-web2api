"""Consolidated observer metadata and conservative recovery boundaries."""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from chatgpt_web2api.orchestrator.cli import build_parser, execute
from chatgpt_web2api.orchestrator.stage_maintenance import (
    cleanup_managed_stages,
    inspect_stages,
)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -1])
@pytest.mark.parametrize("dry_run", [True, False])
def test_invalid_age_never_creates_lock(tmp_path, value, dry_run):
    with pytest.raises(ValueError, match="finite"):
        cleanup_managed_stages(tmp_path, min_age_seconds=value, dry_run=dry_run)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_invalid_clock_is_rejected_before_mutation(tmp_path, value):
    with pytest.raises(ValueError, match="finite"):
        cleanup_managed_stages(tmp_path, now=value, dry_run=False)
    assert list(tmp_path.iterdir()) == []


def test_readonly_cli_observes_open_legacy_writer_without_db_or_writes(tmp_path, monkeypatch):
    candidate = tmp_path / ".staged-active"
    with candidate.open("wb") as writer:
        writer.write(b"synthetic")
        writer.flush()
        before = candidate.stat()

        def forbidden(*args, **kwargs):
            raise AssertionError("read-only inventory attempted a write")

        monkeypatch.setattr(os, "open", forbidden)
        monkeypatch.setattr(Path, "unlink", forbidden)
        result = execute(build_parser().parse_args(["staging-audit", "--root", str(tmp_path)]))
        item = result["inventory"][0]
        assert item["size_bytes"] == 9
        assert item["mtime_ns"] == before.st_mtime_ns
        assert item["disposition"] == "manual_review_only"
        assert item["entry_type"] == "regular_file"
        assert str(tmp_path) not in str(result)
        assert result["removed"] == []
        assert result["remote_actions_permitted"] is False
    assert candidate.read_bytes() == b"synthetic"
    assert list(tmp_path.iterdir()) == [candidate]


def test_disappearing_candidate_is_skipped(tmp_path, monkeypatch):
    candidate = tmp_path / ".staged-gone"
    candidate.touch()
    real_lstat = Path.lstat

    def disappear(path, *args, **kwargs):
        if path == candidate:
            raise FileNotFoundError(path)
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", disappear)
    assert inspect_stages(tmp_path) == []


def test_permission_failure_is_not_a_successful_inventory(tmp_path, monkeypatch):
    candidate = tmp_path / ".staged-denied"
    candidate.touch()
    real_lstat = Path.lstat

    def denied(path, *args, **kwargs):
        if path == candidate:
            raise PermissionError(path)
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", denied)
    with pytest.raises(PermissionError):
        inspect_stages(tmp_path)


def test_nonregular_managed_name_cannot_be_cleaned(tmp_path):
    directory = tmp_path / (".staged-v2-" + "a" * 32)
    directory.mkdir()
    result = cleanup_managed_stages(tmp_path, min_age_seconds=0, dry_run=False)
    assert result["removed"] == []
    assert result["inventory"][0]["entry_type"] == "non_regular"
    assert directory.is_dir()


def test_symlink_is_manual_review_only(tmp_path):
    target = tmp_path / "target"
    target.write_bytes(b"untouched")
    link = tmp_path / (".staged-v2-" + "b" * 32)
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink permission unavailable")
    result = cleanup_managed_stages(tmp_path, min_age_seconds=0, dry_run=False)
    assert result["removed"] == []
    assert result["inventory"][0]["entry_type"] == "non_regular"
    assert target.read_bytes() == b"untouched"


def test_separate_active_process_is_not_cleaned(tmp_path):
    script = (
        "import os,sys\n"
        "from chatgpt_web2api.orchestrator.stage_maintenance import stage_guard,create_managed_stage\n"
        "with stage_guard(sys.argv[1]):\n"
        " fd,path=create_managed_stage(sys.argv[1],'staged')\n"
        " os.write(fd,b'active'); os.close(fd)\n"
        " print('ready',flush=True)\n"
        " sys.stdin.readline()\n"
        " assert path.read_bytes()==b'active'\n"
        " path.unlink()\n"
    )
    child = subprocess.Popen([sys.executable, "-c", script, str(tmp_path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    try:
        # Parent observes the stage while its owner holds the lifetime lock.
        assert child.stdout.readline().strip() == "ready"
        assert inspect_stages(tmp_path, min_age_seconds=0)[0]["size_bytes"] == 6
        with ThreadPoolExecutor(max_workers=1) as pool:
            cleanup = pool.submit(cleanup_managed_stages, tmp_path,
                                  min_age_seconds=0, dry_run=False)
            try:
                assert not cleanup.done()
            finally:
                child.stdin.write("release\n")
                child.stdin.flush()
            assert cleanup.result(timeout=15)["removed"] == []
        assert child.wait(timeout=15) == 0, child.stderr.read()
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=15)
