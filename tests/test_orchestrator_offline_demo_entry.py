"""CLI routing and canonical post-provision paths, without native ACL claims."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from chatgpt_web2api.orchestrator import cli, offline_demo


@pytest.mark.parametrize("override", [("--db", "unused.sqlite3"), ("--private-workspace", "other")])
def test_demo_rejects_storage_overrides_before_calling_entry(monkeypatch, capsys, override):
    def forbidden(**kwargs):
        pytest.fail("demo called with an external storage override")
    monkeypatch.setattr(offline_demo, "execute_demo", forbidden)
    assert cli.main([*override, "--json", "demo", "--label", "unit", "--action", "status"]) == 2
    assert "cannot combine" in capsys.readouterr().out


def test_demo_rejects_inherited_database(monkeypatch, capsys):
    monkeypatch.setenv("CHATGPT_ORCHESTRATOR_DB", "unused.sqlite3")
    assert cli.main(["--json", "demo", "--label", "unit", "--action", "init"]) == 2
    assert "DB environment" in capsys.readouterr().out


def test_crash_flag_on_init_fails_before_creating_workspace(monkeypatch):
    monkeypatch.setattr(offline_demo, "create_private_windows_workspace",
                        lambda label: pytest.fail("workspace was created"))
    with pytest.raises(ValueError, match="only supports demo run"):
        offline_demo.execute_demo(action="init", label="unit", crash_after_intent=True)


def test_provision_alias_is_replaced_by_revalidated_canonical_paths(tmp_path, monkeypatch):
    alias = tmp_path / "provision-alias"
    canonical = tmp_path / "canonical"
    alias.mkdir()
    canonical.mkdir()
    (canonical / "blobs").mkdir()
    context = SimpleNamespace(root=canonical, database=canonical / "controller.sqlite3",
                              blobs=canonical / "blobs")

    def require_source(path):
        assert path.parent == canonical
        assert path.exists()

    policy = SimpleNamespace(check=lambda: context, source=require_source)
    monkeypatch.setattr(offline_demo, "create_private_windows_workspace", lambda label:
                        SimpleNamespace(root=alias, database=alias / "controller.sqlite3", blobs=alias / "blobs"))
    monkeypatch.setattr(offline_demo.PrivateStoragePolicy, "open", lambda label: policy)
    monkeypatch.setattr(offline_demo, "_cooperative_lock", lambda policy: nullcontext())

    def store(path, **kwargs):
        assert path == context.database and kwargs["storage_policy"] is policy
        return "owned-store"

    def packages(store, path):
        assert store == "owned-store" and path == context.blobs
        return "owned-packages"

    monkeypatch.setattr(offline_demo, "Store", store)
    monkeypatch.setattr(offline_demo, "TaskPackages", packages)
    monkeypatch.setattr(offline_demo, "MockSandbox", lambda *args, **kwargs:
                        SimpleNamespace(initialize=lambda: None, inspect=lambda: {"status": "ready"}))
    result = offline_demo.execute_demo(action="init", label="unit")
    assert result["workspace"] == str(canonical)
    assert (canonical / ".offline-demo-v1.json").exists()
    assert not (alias / ".offline-demo-v1.json").exists()
