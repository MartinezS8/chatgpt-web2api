"""Fail-closed, locally pinned Codex App Server request/response schema checks.

The owner picks EXACTLY which generated schema belongs to each wire message.
All resources come from a previously SHA-256-verified local schema bundle.
No remote refs, subprocess, provider or login is used during this validation.
"""
from __future__ import annotations

from pathlib import Path

from jsonschema import validators
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from .schema_fixture_audit import _selected_relative, verified_bundle

_PHASES = (
    "thread_params", "thread_result", "turn_params", "turn_result",
)


class LocalWireSchemas:
    """Four explicit schema selectors; never guess names across Codex versions."""

    def __init__(self, bundle_root: str | Path, *, selections: dict[str, str]):
        if type(selections) is not dict or set(selections) != set(_PHASES):
            raise ValueError("four explicit wire schema selectors are required")
        names = {
            phase: _selected_relative(selections[phase]).as_posix()
            for phase in _PHASES
        }
        if len(set(names.values())) != 4:
            raise ValueError("wire schemas must be four distinct captured files")
        report, documents = verified_bundle(bundle_root)
        if any(name not in documents for name in names.values()):
            raise ValueError("selected wire schema is absent from pinned bundle")
        root = Path(bundle_root).expanduser().resolve()
        resources = []
        for relative, document in documents.items():
            resource = Resource.from_contents(document, default_specification=DRAFT202012)
            resources.append(((root / relative).as_uri(), resource))
            schema_id = document.get("$id")
            if isinstance(schema_id, str) and schema_id:
                resources.append((schema_id, resource))
        registry = Registry().with_resources(resources)
        self._validators = {}
        for phase, name in names.items():
            document = documents[name]
            validator_class = validators.validator_for(document)
            validator_class.check_schema(document)
            self._validators[phase] = validator_class(document, registry=registry)
        self.selections = names
        self.codex_version = report["codex_version"]

    def require(self, phase: str, instance: dict) -> None:
        """No sensitive payloads in the error; no fallback to older fixtures."""
        if phase not in self._validators or type(instance) is not dict:
            raise ValueError("invalid wire schema validation phase/payload")
        try:
            # Iterate once: the caller only needs pass/fail, not raw input values.
            invalid = next(self._validators[phase].iter_errors(instance), None)
        except Exception as exc:
            raise ValueError("wire schema requires uncaptured or invalid references") from exc
        if invalid is not None:
            raise ValueError(f"Codex {phase} does not match pinned local JSON schema")
