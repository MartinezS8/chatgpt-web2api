"""Private-workspace CLI contract: no arbitrary file/db/blob storage path bypass.

These portable tests stub the native Windows DACL loader and cover *only*
routing/containment. They do not claim effective Windows ACL or TOCTOU proof.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import chatgpt_web2api.orchestrator.cli as cli
from chatgpt_web2api.orchestrator.private_workspace import PrivateStorageContext
from chatgpt_web2api.orchestrator.store import Store


@pytest.fixture
def private(tmp_path, monkeypatch):
    monkeypatch.delenv("CHATGPT_ORCHESTRATOR_DB", raising=False)
    root = tmp_path / "private"
    root.mkdir()
    blobs = root / "blobs"
    blobs.mkdir()
    ctx = PrivateStorageContext(root, root / "controller.sqlite3", blobs)

    def trusted_loader(label):
        assert label == "test"
        return ctx

    monkeypatch.setattr(cli, "load_private_workspace", trusted_loader)
    return ctx


def _run(*args):
    return cli.execute(cli.build_parser().parse_args([
        "--private-workspace", "test", *args,
    ]))


def test_protected_mode_binds_database_and_existing_blobs(private):
    prompt = private.root / "prompt.txt"
    prompt.write_text("synthetic private prompt", encoding="utf-8")
    created = _run("create-task", "--id", "t", "--project", "p",
                   "--role", "implement", "--prompt-file", str(prompt))
    assert created["created"] is True
    assert private.database.is_file()
    assert not (private.root / "orchestrator_blobs").exists()

    attachment = private.root / "note.txt"
    attachment.write_text("synthetic attachment", encoding="utf-8")
    package = _run("seal-task", "--id", "t", "--prompt-file", str(prompt),
                   "--attachment", str(attachment))
    assert package["attachments"][0]["size"] == len(b"synthetic attachment")
    assert _run("task-package", "--id", "t")["package_sha256"] == package["package_sha256"]
    assert any(private.blobs.iterdir())


def test_outside_prompt_rejected_before_db_open(private, tmp_path):
    foreign = tmp_path / "outside.txt"
    foreign.write_text("outside", encoding="utf-8")
    with pytest.raises(ValueError, match="inside the private workspace"):
        _run("create-task", "--id", "t", "--project", "p", "--role",
             "implement", "--prompt-file", str(foreign))
    assert not private.database.exists()


def test_relative_source_refused_before_db_open(private, monkeypatch):
    with pytest.raises(ValueError, match="absolute"):
        _run("create-task", "--id", "t", "--project", "p", "--role",
             "implement", "--prompt-file", "prompt.txt")
    assert not private.database.exists()


def test_file_symlink_outside_is_rejected(private, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    alias = private.root / "prompt.txt"
    try:
        alias.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not enabled on this host")
    with pytest.raises(ValueError, match="reparse point"):
        _run("create-task", "--id", "t", "--project", "p",
             "--role", "implement", "--prompt-file", str(alias))
    assert not private.database.exists()


def test_external_worker_blob_root_is_refused(private, tmp_path):
    with pytest.raises(ValueError, match="inside the private workspace"):
        _run("worker-claim", "--account", "a", "--project", "p",
             "--blob-root", str(tmp_path / "outside"))
    assert not private.database.exists()


def test_worker_blob_root_cannot_be_workspace_root(private):
    with pytest.raises(ValueError, match="does not match workspace"):
        _run("worker-claim", "--account", "a", "--project", "p",
             "--blob-root", str(private.root))
    assert not private.database.exists()


def test_staging_cleanup_cannot_escape_private_root(private, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError, match="inside the private workspace"):
        _run("staging-audit", "--root", str(outside), "--delete-managed-v2")
    assert list(outside.iterdir()) == []
    ok = _run("staging-audit", "--root", str(private.blobs))
    assert ok["dry_run"] is True
    assert ok["removed"] == []


def test_staging_subdirectory_not_a_supported_root(private):
    sub = private.blobs / "nested"
    sub.mkdir()
    with pytest.raises(ValueError, match="requires workspace root or blobs"):
        _run("staging-audit", "--root", str(sub))


def test_db_override_cannot_mix_with_private_label(private):
    args = cli.build_parser().parse_args([
        "--db", str(private.root / "wrong.sqlite3"),
        "--private-workspace", "test", "claim", "--project", "p",
    ])
    with pytest.raises(ValueError, match="cannot be combined"):
        cli.execute(args)
    assert not (private.root / "wrong.sqlite3").exists()


def test_env_db_override_cannot_mix_with_private_label(private, monkeypatch):
    monkeypatch.setenv("CHATGPT_ORCHESTRATOR_DB", "arbitrary.sqlite3")
    with pytest.raises(ValueError, match="cannot be combined"):
        _run("claim", "--project", "p")
    assert not private.database.exists()


def test_attachment_outside_rejected_before_store_mutation(private, tmp_path):
    prompt = private.root / "prompt.txt"
    prompt.write_text("synthetic", encoding="utf-8")
    outsider = tmp_path / "outside.md"
    outsider.write_text("foreign", encoding="utf-8")
    with pytest.raises(ValueError, match="inside the private workspace"):
        _run("seal-task", "--id", "missing", "--prompt-file", str(prompt),
             "--attachment", str(outsider), "--allowed-root", str(private.root))
    assert not private.database.exists()


def test_attachment_allowed_root_outside_rejected(private, tmp_path):
    prompt = private.root / "prompt.txt"
    prompt.write_text("synthetic", encoding="utf-8")
    with pytest.raises(ValueError, match="inside the private workspace"):
        _run("seal-task", "--id", "missing", "--prompt-file", str(prompt),
             "--allowed-root", str(tmp_path))
    assert not private.database.exists()


def test_protected_backup_uses_only_fixed_database(private):
    Store(private.database)
    result = _run("backup-local-db", "--filename", "before-upgrade.sqlite3")
    backup = private.root / "before-upgrade.sqlite3"
    assert Path(result["backup"]) == backup
    assert backup.exists()
    with pytest.raises(FileExistsError):
        _run("backup-local-db", "--filename", "before-upgrade.sqlite3")


def test_legacy_cli_remains_explicitly_offline_and_compatible(private, tmp_path):
    legacy = tmp_path / "legacy.sqlite3"
    result = cli.execute(cli.build_parser().parse_args([
        "--db", str(legacy), "claim", "--project", "p",
    ]))
    assert result["project"] == "p"
    assert legacy.is_file()
    assert cli._capabilities()["legacy_db_paths_private_assurance"] is False


def test_reject_directory_as_protected_attachment(private):
    with pytest.raises(ValueError, match="regular file"):
        private.require_path(private.root)


def test_reject_symlinked_staging_root(private, tmp_path):
    alias = private.root / "alias"
    try:
        alias.symlink_to(private.blobs, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="reparse"):
        private.require_staging_root(alias)


@pytest.mark.skipif(__import__("os").name != "nt",
                    reason="requires native Windows private workspace provisioning")
def test_native_existing_workspace_loader_roundtrip():
    import shutil
    import uuid

    from chatgpt_web2api.orchestrator.private_workspace import load_private_workspace
    from chatgpt_web2api.orchestrator.storage_hardening import create_private_windows_workspace

    label = "gate-private-" + uuid.uuid4().hex[:12]
    created = create_private_windows_workspace(label)
    try:
        loaded = load_private_workspace(label)
        assert loaded.root == created.root
        assert loaded.database == created.database
        assert loaded.blobs == created.blobs
        loaded.blobs.mkdir()
        Store(loaded.database)
        # The existing DB and child blob directory must remain acceptable,
        # even with OS-specific ordinary inherited child ACE flags.
        loaded_again = load_private_workspace(label)
        assert loaded_again == loaded
    finally:
        shutil.rmtree(created.root)


def test_existing_child_acl_rejects_extra_trustee(tmp_path, monkeypatch):
    import chatgpt_web2api.orchestrator.private_workspace as protected

    child = tmp_path / "controller.sqlite3"
    child.write_bytes(b"synthetic")
    sid = "S-1-5-21-1-2-3-1001"
    monkeypatch.setattr(protected, "read_windows_descriptor", lambda path: {
        "owner_sid": sid, "aces": [
            {"sid": sid, "type": 0, "mask": 0x1F01FF},
            {"sid": "S-1-5-18", "type": 0, "mask": 0x1F01FF},
            {"sid": "S-1-1-0", "type": 0, "mask": 1},
        ],
    })
    with pytest.raises(PermissionError, match="unexpected access"):
        protected._check_child_acl(child, sid)


def test_existing_child_acl_rejects_wrong_owner(tmp_path, monkeypatch):
    import chatgpt_web2api.orchestrator.private_workspace as protected

    child = tmp_path / "blobs"
    child.mkdir()
    monkeypatch.setattr(protected, "read_windows_descriptor", lambda path: {
        "owner_sid": "S-1-5-18",
        "aces": [],
    })
    with pytest.raises(PermissionError, match="unexpected owner"):
        protected._check_child_acl(child, "S-1-5-21-1-2-3-1001")


def test_dotdot_escape_is_rejected_before_database_open(private, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("synthetic")
    escape = private.root / ".." / "outside.txt"
    with pytest.raises(ValueError, match="inside the private workspace"):
        _run("create-task", "--id", "t", "--project", "p", "--role",
             "implement", "--prompt-file", str(escape))
    assert not private.database.exists()
