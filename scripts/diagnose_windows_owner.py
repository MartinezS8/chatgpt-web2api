"""Inspect ownership only on a new disposable workspace; never relax policy."""
import argparse
import json
import shutil
import uuid

from chatgpt_web2api.orchestrator.storage_hardening import create_private_windows_workspace
from chatgpt_web2api.orchestrator.storage_policy import _current_windows_sid
from chatgpt_web2api.orchestrator.windows_acl import read_windows_descriptor

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--require-user-owner", action="store_true")
args = parser.parse_args()
workspace = create_private_windows_workspace("owner-" + uuid.uuid4().hex[:12])
try:
    workspace.blobs.mkdir()
    source = workspace.root / "synthetic.txt"
    source.write_text("synthetic", encoding="utf-8")
    sid = _current_windows_sid()
    result = {path.name: {
        "owner_is_user": (owner := read_windows_descriptor(path)["owner_sid"]) == sid,
        "owner_is_administrators": owner == "S-1-5-32-544",
    } for path in (workspace.root, workspace.blobs, source)}
    print(json.dumps(result))
    if args.require_user_owner and not all(row["owner_is_user"] for row in result.values()):
        raise PermissionError("CI process must create user-owned private children")
finally:
    shutil.rmtree(workspace.root)
