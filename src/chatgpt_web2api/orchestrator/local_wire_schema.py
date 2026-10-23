"""Fail-closed, locally pinned Codex App Server request/response schema checks.

The owner picks EXACTLY which generated schema belongs to each wire message.
All resources come from a previously SHA-256-verified local schema bundle.
No remote refs, subprocess, provider or login is used during this validation.
"""
from __future__ import annotations

from pathlib import Path

from jsonschema import validators

from .schema_fixture_audit import (
    _selected_relative,
    build_local_schema_registry,
    verified_bundle,
)

_PHASES = (
    "thread_params", "thread_result", "turn_params", "turn_result",
)
_TITLES = {
    "thread_params": "ThreadStartParams",
    "thread_result": "ThreadStartResponse",
    "turn_params": "TurnStartParams",
    "turn_result": "TurnStartResponse",
}

# Wrongly selected permissive JSON schemas can otherwise report a fake PASS.
# These are intentionally malformed instances of each *concrete* RPC shape.
# A useful method-specific schema must reject its corresponding probe.
_BAD_SHAPES = {
    "thread_params": {
        "model": "synthetic", "cwd": "C:/scratch",
        "sandbox": 123, "approvalPolicy": "never",
    },
    "thread_result": {"thread": 123},
    "turn_params": {
        "threadId": 123, "input": "not-an-array",
        "sandboxPolicy": {"type": "readOnly"},
    },
    "turn_result": {"turn": 123},
}


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
        registry, bound = build_local_schema_registry(root, documents)
        self._validators = {}
        for phase, name in names.items():
            document = bound[name]
            title = documents[name].get("title")
            if title is not None and title != _TITLES[phase]:
                raise ValueError(f"selected {phase} schema title belongs to another RPC")
            validator_class = validators.validator_for(document)
            validator_class.check_schema(document)
            validator = validator_class(document, registry=registry)
            try:
                accepts_broken = validator.is_valid(_BAD_SHAPES[phase])
            except Exception as exc:
                raise ValueError(
                    f"selected {phase} schema has unresolved local references"
                ) from exc
            if accepts_broken:
                raise ValueError(
                    f"selected {phase} schema accepts malformed RPC shape"
                )
            self._validators[phase] = validator
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
