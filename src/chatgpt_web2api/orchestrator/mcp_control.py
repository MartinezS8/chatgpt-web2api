"""Dedicated stdio MCP *read-only* Codex observer. No browser/remote dispatch.

Compatible with the repository's pinned MCP 1.x API. The SDK import is lazy;
this module can be inspected/tested without starting any MCP server.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from .observer import Observer

_TOOL_PARAMS = {
    "orchestrator_capabilities": (),
    "orchestrator_status": ("project_id",),
    "orchestrator_events": (),
    "orchestrator_callbacks": (),
    "orchestrator_workers": ("account_id",),
    "orchestrator_reviews": ("target_task_id",),
    "orchestrator_proposals": ("target_task_id",),
    "orchestrator_evidence": ("task_id",),
}


def dispatch_observer(observer: Observer, name: str, arguments: dict | None = None) -> dict:
    """Whitelist-only dispatch; ignore no unknown or mutating verbs."""
    args = arguments or {}
    if name not in _TOOL_PARAMS:
        raise ValueError("unknown or forbidden MCP tool")
    allowed = set(_TOOL_PARAMS[name])
    if name in ("orchestrator_events", "orchestrator_callbacks"):
        allowed |= {"after", "limit"}
    if set(args) - allowed:
        raise ValueError("unsupported tool arguments")
    if name == "orchestrator_capabilities":
        return observer.capabilities()
    if name == "orchestrator_status":
        return observer.status(args["project_id"])
    if name == "orchestrator_workers":
        return observer.workers(args["account_id"])
    if name == "orchestrator_reviews":
        return observer.reviews(args["target_task_id"])
    if name == "orchestrator_proposals":
        return observer.proposals(args["target_task_id"])
    if name == "orchestrator_evidence":
        return observer.evidence(args["task_id"])
    if name == "orchestrator_events":
        return observer.events(after=args.get("after",0),limit=args.get("limit",100))
    if name == "orchestrator_callbacks":
        return observer.callbacks(after=args.get("after",0),limit=args.get("limit",100))
    raise ValueError("forbidden MCP operation")


def create_server(database: str | Path, *, storage_policy=None):
    from mcp import types as mcp_types
    from mcp.server import Server

    observer=Observer(database, storage_policy=storage_policy)
    server=Server("chatgpt-orchestrator-observer")

    @server.list_tools()
    async def list_tools() -> list:
        out=[]
        for name,required in _TOOL_PARAMS.items():
            props={key:{"type":"string"} for key in required}
            if name in ("orchestrator_events","orchestrator_callbacks"):
                props.update({"after":{"type":"integer","minimum":0},"limit":{"type":"integer","minimum":1,"maximum":200}})
            out.append(mcp_types.Tool(name=name,description="Read-only local orchestration state; no remote actions",
                inputSchema={"type":"object","properties":props,"required":list(required),"additionalProperties":False}))
        return out

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        result=dispatch_observer(observer,name,arguments)
        return [mcp_types.TextContent(type="text",text=json.dumps(result,sort_keys=True,ensure_ascii=False))]
    return server


async def run_server(database: str | Path, *, storage_policy=None):
    from mcp.server.stdio import stdio_server
    server=create_server(database, storage_policy=storage_policy)
    async with stdio_server() as (read,write):
        await server.run(read,write,server.create_initialization_options(),raise_exceptions=True)


def main():
    parser=argparse.ArgumentParser(description="Read-only Codex orchestrator MCP stdio observer")
    parser.add_argument("--db",default=os.environ.get("CHATGPT_ORCHESTRATOR_DB"))
    parser.add_argument("--private-workspace")
    args=parser.parse_args()
    if args.private_workspace is not None:
        if args.db:
            parser.error("--private-workspace cannot be combined with --db or DB environment")
        from .storage_policy import PrivateStoragePolicy
        policy = PrivateStoragePolicy.open(args.private_workspace)
        asyncio.run(run_server(policy.context.database, storage_policy=policy))
        return
    if not args.db:
        parser.error("--db or CHATGPT_ORCHESTRATOR_DB required")
    asyncio.run(run_server(args.db))


if __name__ == "__main__":
    main()

