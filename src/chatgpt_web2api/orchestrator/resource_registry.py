"""Canonical resource identities and operator-asserted aliases.

This module intentionally does *not* perform remote provider verification or grant
permissions. A binding is an operator assertion until a future provider adapter
independently verifies it. Callers must NOT treat a registered binding as proof
that live writes are authorized.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, replace

from .store import Store, TaskSpec, canonical_scope

_GH_REPO_ID = re.compile(r"^[1-9][0-9]{0,18}$")
_SB_REF = re.compile(r"^[a-z0-9]{8,64}$")
_VERCEL_ID = re.compile(r"^[a-zA-Z0-9_-]{3,128}$")
_ENV = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ALIAS = re.compile(r"^[a-z][a-z0-9_.:/-]{1,127}$")
_SEGMENT = re.compile(r"^[a-zA-Z0-9_.-]+$")


@dataclass(frozen=True)
class ResourceIdentity:
    provider: str
    authority_id: str
    environment: str | None = None

    def key(self) -> str:
        provider = self.provider.lower()
        if provider == "github":
            if self.environment is not None or not _GH_REPO_ID.fullmatch(self.authority_id):
                raise ValueError("GitHub requires a numeric repository ID and no environment")
            return canonical_scope(f"github:repo/{self.authority_id}")
        if provider == "supabase":
            if not _SB_REF.fullmatch(self.authority_id.lower()) or not self.environment or not _ENV.fullmatch(self.environment.lower()):
                raise ValueError("Supabase requires project ref and explicit environment")
            return canonical_scope(f"supabase:project/{self.authority_id.lower()}/env/{self.environment.lower()}")
        if provider == "vercel":
            if not _VERCEL_ID.fullmatch(self.authority_id) or not self.environment or not _ENV.fullmatch(self.environment.lower()):
                raise ValueError("Vercel requires project ID and explicit environment")
            return canonical_scope(f"vercel:project/{self.authority_id.lower()}/env/{self.environment.lower()}")
        raise ValueError(f"unsupported provider: {self.provider}")


def _alias_name(alias: str) -> str:
    if not isinstance(alias, str) or alias != alias.strip() or not _ALIAS.fullmatch(alias.lower()):
        raise ValueError("invalid alias")
    if "//" in alias or ".." in alias or alias.endswith(("/", ":")) or "\\" in alias:
        raise ValueError("ambiguous alias")
    return alias.casefold()


def _relative_path(relative_path: str | None) -> str:
    if relative_path is None or relative_path == "":
        return ""
    if not isinstance(relative_path, str) or relative_path != relative_path.strip() or "\\" in relative_path:
        raise ValueError("invalid resource subpath")
    segments = relative_path.split("/")
    if any(segment in ("", ".", "..") or not _SEGMENT.fullmatch(segment) for segment in segments):
        raise ValueError("invalid resource subpath")
    return "/" + "/".join(segments).casefold()


class ResourceRegistry:
    """DB-shared alias authority; a single SQLite file is mandatory for locks."""

    def __init__(self, store: Store):
        self.store = store
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_resource_bindings (
                alias TEXT PRIMARY KEY, canonical_id TEXT NOT NULL,
                operator TEXT NOT NULL, provenance TEXT NOT NULL,
                registered_at REAL NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS ix_resource_canonical ON orchestrator_resource_bindings(canonical_id)")

    def register(self, alias: str, identity: ResourceIdentity, *, operator: str,
                 provenance: str = "operator_assertion") -> str:
        """Bind a human-friendly alias to a stable ID; never silently rebind.

        ``provenance`` records an assertion, *not* a provider-verified grant.
        Do not accept a forged 'provider_verified' string as authorization.
        """
        key = _alias_name(alias)
        canonical_id = identity.key()
        if not isinstance(operator, str) or not operator.strip() or len(operator) > 128:
            raise ValueError("operator must be supplied")
        if provenance != "operator_assertion":
            raise ValueError("provider evidence cannot be self-asserted through this interface")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT canonical_id FROM orchestrator_resource_bindings WHERE alias=?", (key,)).fetchone()
            if current:
                if current["canonical_id"] != canonical_id:
                    raise ValueError("alias rebinding forbidden; must be reconciled out-of-band")
                return canonical_id
            db.execute("INSERT INTO orchestrator_resource_bindings(alias, canonical_id,operator,provenance,registered_at) VALUES (?,?,?,?,?)",
                       (key, canonical_id, operator.strip(), provenance, time.time()))
        return canonical_id

    def resolve(self, alias: str, relative_path: str | None = None) -> str:
        key = _alias_name(alias)
        with self.store._connect() as db:
            row = db.execute("SELECT canonical_id FROM orchestrator_resource_bindings WHERE alias=?", (key,)).fetchone()
            if row is None:
                raise ValueError(f"unknown resource alias: {alias}")
            return canonical_scope(row["canonical_id"] + _relative_path(relative_path))

    def task_with_resolved_scopes(self, spec: TaskSpec,
                                  bindings: tuple[tuple[str, str | None], ...]) -> TaskSpec:
        if spec.write_scopes:
            raise ValueError("do not combine unbound legacy scopes with resolved resource scopes")
        scopes = tuple(self.resolve(alias, path) for alias, path in bindings)
        if len(set(scopes)) != len(scopes):
            raise ValueError("duplicate resource scopes")
        return replace(spec, write_scopes=scopes)

    def list_bindings(self) -> list[dict]:
        with self.store._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM orchestrator_resource_bindings ORDER BY alias")]

    @staticmethod
    def provider_write_authorized(*_, **__) -> bool:
        """A future provider-auth/capability gate must override this deny-all."""
        return False