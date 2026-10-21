"""Exercise ONLY the installed wheel's synthetic demo and read-only MCP server."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path


def _safe_env():
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"PATH", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP",
                              "LOCALAPPDATA", "USERPROFILE", "APPDATA"}}
    return {**env, "W2A_E2E_RUN": "0"}


def _call(label, action, steps, *, expected=0, crash=False):
    command = [sys.executable, "-I", "-m", "chatgpt_web2api.orchestrator", "--json",
               "demo", "--label", label, "--action", action]
    if crash:
        command.append("--crash-after-intent")
    start = time.monotonic()
    result = subprocess.run(command, env=_safe_env(), capture_output=True, text=True, timeout=1200)
    step = {"label": label, "action": action, "exit_code": result.returncode,
            "expected_exit": expected, "seconds": round(time.monotonic() - start, 2)}
    steps.append(step)
    if result.returncode != expected:
        raise RuntimeError(f"demo {action} exit {result.returncode}, expected {expected}: {result.stderr[-1000:]}")
    if crash:
        print("synthetic child stopped after durable intent (exit 17)", flush=True)
        return None
    document = json.loads(result.stdout)
    raw = json.dumps(document)
    if any(key in raw for key in ("claim_token", "session_key", "OFFLINE SYNTHETIC DEMO ONLY")):
        raise AssertionError("demo exposed a prompt or internal credential field")
    data = document["data"]
    assert data["production_finalization_permitted"] is False
    assert data["remote_send_permitted"] is False
    step["data"] = data
    print(f"demo {action}: {data['status']} ({step['seconds']}s)", flush=True)
    return data


async def _mcp(label):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=[
        "-I", "-m", "chatgpt_web2api.orchestrator.mcp_control", "--private-workspace", label], env=_safe_env())
    arguments = {
        "orchestrator_capabilities": {}, "orchestrator_status": {"project_id": "offline-demo"},
        "orchestrator_events": {}, "orchestrator_callbacks": {},
        "orchestrator_workers": {"account_id": "offline-demo"},
        "orchestrator_reviews": {"target_task_id": "01-a"},
        "orchestrator_proposals": {"target_task_id": "01-a"},
        "orchestrator_evidence": {"task_id": "01-a"},
    }
    replies = {}
    async with asyncio.timeout(240):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                assert {tool.name for tool in tools} == set(arguments)
                assert all(tool.inputSchema["additionalProperties"] is False for tool in tools)
                for name, args in arguments.items():
                    result = await client.call_tool(name, args)
                    assert not result.isError, name
                    raw = result.content[0].text
                    assert all(key not in raw for key in ("claim_token", "session_key", "OFFLINE SYNTHETIC"))
                    replies[name] = json.loads(raw)
                assert (await client.call_tool("orchestrator_approve", {})).isError
    assert replies["orchestrator_status"]["states"] == {"verified": 5}
    assert len(replies["orchestrator_workers"]["workers"]) == 5
    assert len(replies["orchestrator_callbacks"]["callbacks"]) == 5
    assert replies["orchestrator_evidence"]["evidence"]["assurance"] == "offline_mock_only"
    assert replies["orchestrator_reviews"]["reviews"][0]["assurance"] == "offline_mock_only"
    events = replies["orchestrator_events"]["events"]
    assert len(events) == 15
    for source, target in (("01-a", "03-review-a"), ("02-b", "04-review-b"),
                           ("03-review-a", "05-summary"), ("04-review-b", "05-summary")):
        completed = next(event["id"] for event in events if event["task_id"] == source and event["kind"] == "turn.completed")
        dispatched = next(event["id"] for event in events if event["task_id"] == target and event["kind"] == "dispatch.intent")
        assert completed < dispatched
    return {"tools": sorted(arguments), "handshake": True, "forbidden_rejected": True,
            "dag_event_order_verified": True, "replies": replies}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    repo = Path(__file__).resolve().parents[1]
    if output.is_relative_to(repo) or output.exists():
        raise ValueError("use a NEW receipt path outside the checkout")
    import chatgpt_web2api
    if sys.version_info[:2] != (3, 12) or os.name != "nt":
        raise RuntimeError("Windows CPython 3.12 required")
    if not Path(chatgpt_web2api.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("smoke must use a fresh installed wheel, not editable source")
    receipt = {"status": "FAIL", "python": sys.version, "installed_module": chatgpt_web2api.__file__,
               "steps": [], "provider_calls": False, "production_approval": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        label = "wheel-demo-" + uuid.uuid4().hex[:12]
        receipt["demo_label"] = label
        assert _call(label, "init", receipt["steps"])["status"] == "ready"
        completed = _call(label, "run", receipt["steps"])
        assert completed["status"] == "demo_complete" and completed["mock_completed"] == 5
        assert completed["workers_used"] == 5 and completed["callback_count"] == 5
        assert len({worker["session_sha256"] for worker in completed["workers"]}) == 5
        assert {a["session_sha256"] for a in completed["attempts"]} == {
            w["session_sha256"] for w in completed["workers"]}
        assert len(completed["packages"]) == len(completed["mock_upload_receipts"]) == 5
        assert all(part["state"] == "acked" and part["remote_id"].startswith("fake:")
                   for part in completed["mock_upload_receipts"])
        assert len(completed["reviews"]) == 2
        assert all(review["implement_worker_id"] != review["reviewer_worker_id"] for review in completed["reviews"])
        assert {task["state"] for task in completed["tasks"]} == {"verified"}
        assert not completed["production_locks_released"]
        again = _call(label, "run", receipt["steps"])
        assert again["attempts"] == completed["attempts"]
        assert again["event_cursor"] == completed["event_cursor"] == 15
        assert _call(label, "doctor", receipt["steps"])["status"] == "demo_complete"
        receipt["mcp"] = asyncio.run(_mcp(label))
        crash_label = "wheel-crash-" + uuid.uuid4().hex[:12]
        receipt["crash_label"] = crash_label
        _call(crash_label, "init", receipt["steps"])
        _call(crash_label, "run", receipt["steps"], expected=17, crash=True)
        quarantined = _call(crash_label, "run", receipt["steps"], expected=2)
        assert quarantined["status"] == "needs_human"
        assert len(quarantined["attempts"]) == 1 and quarantined["attempts"][0]["status"] == "unknown"
        repeat = _call(crash_label, "run", receipt["steps"], expected=2)
        assert repeat["attempts"] == quarantined["attempts"]
        assert repeat["event_cursor"] == quarantined["event_cursor"]
        receipt["status"] = "PASS"
    finally:
        with output.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
