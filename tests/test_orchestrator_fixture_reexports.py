"""Guard pytest fixture re-exports against F401 'safe' auto-removal.

The imported fixture is not referenced directly by each test function:
Pytest discovers it in the consuming module's globals.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "name",
    (
        "test_orchestrator_implementer_provenance",
        "test_orchestrator_task_review_evidence",
        "test_orchestrator_workflow_pin_ledger",
    ),
)
def test_cross_module_store_fixture_is_registered(name):
    provider = importlib.import_module("test_orchestrator_provider_evidence")
    consumer = importlib.import_module(name)
    assert callable(provider.store)
    assert consumer.store is provider.store


def test_task_state_still_serializes_as_value():
    from chatgpt_web2api.orchestrator.store import TaskState

    assert TaskState.RESERVED.value == "reserved"
    assert TaskState.RESERVED == "reserved"
    assert str(TaskState.RESERVED) == "reserved"
