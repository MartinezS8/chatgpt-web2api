"""Offline cooperative staging: crash recovery, active writers and safe snapshots."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from chatgpt_web2api.orchestrator.stage_maintenance import (
    cleanup_managed_stages,
    create_managed_stage,
    inspect_stages,
    stage_guard,
)
from chatgpt_web2api.orchestrator.store import Store, TaskSpec
from chatgpt_web2api.orchestrator.task_packages import TaskPackages


def test_legacy_stage_files_are_never_deleted(tmp_path):
    names = (".staged-legacy", ".sqlite-snapshot-old")
    for name in names:
        (tmp_path / name).write_bytes(b"do not touch")
    result = cleanup_managed_stages(tmp_path, min_age_seconds=0, dry_run=False)
    assert result["removed"] == []
    assert len(inspect_stages(tmp_path, min_age_seconds=0)) == 2
    assert all((tmp_path / name).exists() for name in names)


def test_hard_exited_process_leaves_recoverable_v2_stage(tmp_path):
    script = (
        "import os,sys\n"
        "from chatgpt_web2api.orchestrator.stage_maintenance import "
        "stage_guard,create_managed_stage\n"
        "with stage_guard(sys.argv[1]):\n"
        " fd,p=create_managed_stage(sys.argv[1],'staged')\n"
        " os.write(fd,b'partial data')\n"
        " os.close(fd)\n"
        " os._exit(0)\n"
    )
    env = dict(os.environ)
    root = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                   check=True, timeout=20, env=env)
    item = next(tmp_path.glob(".staged-v2-*"))
    assert item.read_bytes() == b"partial data"
    assert cleanup_managed_stages(tmp_path, min_age_seconds=0)["removed"] == []
    assert item.exists()
    cleaned = cleanup_managed_stages(tmp_path, min_age_seconds=0, dry_run=False)
    assert cleaned["removed"] == [item.name]
    assert not item.exists()


def test_long_running_cooperative_writer_is_not_cleaned(tmp_path):
    writing = threading.Event()
    release = threading.Event()

    def writer():
        with stage_guard(tmp_path):
            fd, path = create_managed_stage(tmp_path, "sqlite-snapshot")
            os.close(fd)
            writing.set()
            assert release.wait(timeout=12)
            assert path.exists()
            path.unlink()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(writer)
        assert writing.wait(timeout=4)
        second = pool.submit(cleanup_managed_stages, tmp_path,
                             min_age_seconds=0, dry_run=False)
        time.sleep(0.1)
        assert not second.done()
        release.set()
        first.result(timeout=12)
        assert second.result(timeout=12)["removed"] == []


def test_malformed_managed_like_stage_is_not_cleaned(tmp_path):
    (tmp_path / ".staged-v2-not-a-random-id").write_bytes(b"legacy")
    with stage_guard(tmp_path):
        fd, valid = create_managed_stage(tmp_path, "staged")
        os.close(fd)
    result = cleanup_managed_stages(tmp_path, min_age_seconds=0, dry_run=False)
    assert result["removed"] == [valid.name]
    assert (tmp_path / ".staged-v2-not-a-random-id").exists()


def test_source_swapped_after_preflight_is_rejected(tmp_path, monkeypatch):
    store = Store(tmp_path / "controller.sqlite3")
    store.create(TaskSpec("t", "p", "implement", "test"))
    pack = TaskPackages(store, tmp_path / "blobs")
    original = tmp_path / "attachment.txt"
    original.write_bytes(b"known payload")
    real_open = Path.open
    swapped = [False]

    def swap_before_open(path, *args, **kwargs):
        if path == original and args and args[0] == "rb" and not swapped[0]:
            swapped[0] = True
            original.unlink()
            original.write_bytes(b"other payload")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", swap_before_open)
    with pytest.raises(ValueError, match="attachment identity changed"):
        pack.seal("t", "test", [original], allowed_root=tmp_path)
    assert swapped == [True]
    with pytest.raises(ValueError, match="not sealed"):
        pack.read("t")


@pytest.mark.parametrize("kind", ["staged", "sqlite-snapshot"])
def test_new_stage_name_is_recognized_and_requires_explicit_cleanup(tmp_path, kind):
    with stage_guard(tmp_path):
        fd, path = create_managed_stage(tmp_path, kind)
        os.close(fd)
    assert inspect_stages(tmp_path, min_age_seconds=0)[0]["kind"] == "managed_v2"
    assert path.exists()
    assert cleanup_managed_stages(tmp_path, min_age_seconds=0)["removed"] == []
    assert path.exists()


def test_bad_cleanup_age_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        cleanup_managed_stages(tmp_path, min_age_seconds=-1)
