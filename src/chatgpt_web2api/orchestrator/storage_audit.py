"""Disposable diagnostics; successful execution is never Model-2 acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

SURFACES = (
    "ancestor", "root", "main", "wal", "shm", "migration_journal",
    "hot_recovery_journal", "attachment_source", "stage_lock", "blob_publish",
    "backup_publish", "content_write", "second_user",
)


def security_gate(rows):
    """Missing, duplicate, unknown and untested surfaces cannot grant acceptance."""
    return (
        len(rows) == len(SURFACES)
        and {row["surface"] for row in rows} == set(SURFACES)
        and all(row["status"] == "BLOCKED" for row in rows)
    )


def classify(*, reached, winerror, marker_changed, protected_changed, error=None):
    if marker_changed or protected_changed:
        return "REPRODUCED_UNSAFE"
    if reached and winerror == 32 and error is None:
        return "BLOCKED"
    return "NOT_TESTED"


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _probe(surface):
    from .storage_hardening import create_private_windows_workspace
    from .storage_policy import PrivateStoragePolicy
    from .store import Store

    workspace = create_private_windows_workspace("audit-" + uuid.uuid4().hex)
    try:
        workspace.blobs.mkdir()
        policy = PrivateStoragePolicy.open(workspace.root.name)
        if surface == "hot_recovery_journal":
            seeded = sqlite3.connect(policy.context.database)
            try:
                seeded.execute("CREATE TABLE payloads(payload BLOB)")
                seeded.executemany("INSERT INTO payloads VALUES(zeroblob(1200))", [()] * 6000)
                seeded.commit()
            finally:
                seeded.close()
            subprocess.run(
                [sys.executable, "-c", "import os,sqlite3,sys; "
                 "db=sqlite3.connect(sys.argv[1],isolation_level=None); "
                 "db.execute('PRAGMA cache_size=5'); "
                 "db.execute('BEGIN IMMEDIATE'); "
                 "db.execute('UPDATE payloads SET payload=zeroblob(2500)'); os._exit(23)",
                 str(policy.context.database)],
                capture_output=True, timeout=30,
            )
            journal = Path(str(policy.context.database) + "-journal")
            if not journal.read_bytes().startswith(bytes.fromhex("d9d505f920a163d7")):
                raise ValueError("probe did not create a genuine hot journal")
        suffix = {"main": "", "wal": "-wal", "shm": "-shm",
                  "migration_journal": "-journal", "hot_recovery_journal": "-journal",
                  "content_write": ""}[surface]
        target = Path(str(policy.context.database) + suffix)
        with tempfile.TemporaryDirectory(prefix="w2a-audit-marker-") as external:
            marker = Path(external).resolve() / "synthetic-marker.bin"
            marker.write_bytes(b"SYNTHETIC OUTSIDE MARKER")
            before = _digest(marker)
            observations = []
            original = sqlite3.connect

            def before_open(*args, **kwargs):
                if str(args[0]) == str(policy.context.database) and not observations:
                    protected_before = _digest(target)
                    program = '''import json, pathlib, sys
target, marker = map(pathlib.Path, sys.argv[1:3])
unlinked = False
try:
    if sys.argv[3] == "content_write":
        with target.open("r+b") as stream:
            stream.write(b"SYNTHETIC CONTENT CHANGE")
    else:
        target.unlink()
        unlinked = True
        target.symlink_to(marker)
    print(json.dumps({"winerror": None, "unlinked": unlinked}))
except OSError as error:
    print(json.dumps({"winerror": getattr(error, "winerror", None), "unlinked": unlinked}))
'''
                    child = subprocess.run(
                        [sys.executable, "-c", program, str(target), str(marker), surface],
                        capture_output=True, text=True, timeout=20, check=True,
                    )
                    observation = json.loads(child.stdout)
                    try:
                        protected_after = _digest(target)
                    except OSError:
                        protected_after = None
                    observation.update(
                        protected_before=protected_before,
                        protected_after=protected_after,
                    )
                    observations.append(observation)
                return original(*args, **kwargs)

            error = None
            try:
                with patch("sqlite3.connect", before_open):
                    Store(policy.context.database, storage_policy=policy)
            except Exception as exc:
                # Errors do not establish prevention: a marker may already differ.
                error = type(exc).__name__
            after = _digest(marker)
            observation = observations[0] if observations else {}
            rollback_lost = False
            if surface == "hot_recovery_journal" and observations:
                try:
                    checked = sqlite3.connect(policy.context.database)
                    try:
                        observed_size = checked.execute(
                            "SELECT sum(length(payload)) FROM payloads"
                        ).fetchone()[0]
                    finally:
                        checked.close()
                    observation["recovered_payload_bytes"] = observed_size
                    observation["expected_payload_bytes"] = 6000 * 1200
                    rollback_lost = observed_size != 6000 * 1200
                except sqlite3.Error:
                    observation["recovery_inspection"] = "inconclusive"
            status = classify(
                reached=bool(observations),
                winerror=(None if observation.get("unlinked")
                          else observation.get("winerror")),
                marker_changed=before != after,
                protected_changed=(rollback_lost or (surface == "content_write" and
                                   observation.get("protected_before")
                                   != observation.get("protected_after"))),
                error=error,
            )
            hook = ("before_sqlite_journal_recovery" if surface == "hot_recovery_journal"
                    else "before_sqlite_open")
            return dict(surface=surface, status=status, hook=hook,
                        outside_before=before, outside_after=after,
                        operation_error=error, **observation)
    finally:
        # Only the freshly provisioned UUID workspace is removed.
        shutil.rmtree(workspace.root)


def audit():
    rows = []
    for surface in SURFACES:
        if os.name != "nt" or surface not in (
            "main", "wal", "shm", "migration_journal", "hot_recovery_journal", "content_write",
        ):
            rows.append(dict(surface=surface, status="NOT_TESTED",
                             reason="native probe not implemented or Windows unavailable"))
            continue
        try:
            rows.append(_probe(surface))
        except Exception as exc:
            rows.append(dict(surface=surface, status="NOT_TESTED",
                             reason=type(exc).__name__))
    return {"model": "hostile_same_user", "second_user_authorized": False,
            "surfaces": rows, "model2_accepted": security_gate(rows)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostic", action="store_true",
                        help="exit zero after reporting; never an acceptance gate")
    args = parser.parse_args(argv)
    result = audit()
    print(json.dumps(result, sort_keys=True))
    return 0 if args.diagnostic or result["model2_accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
