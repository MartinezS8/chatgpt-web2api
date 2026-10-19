"""Read-only replay over the existing persisted outbox event stream.

Never treats progress messages, worker heartbeats or local event acknowledgments
as independently verified provider completion.
"""
from __future__ import annotations

from .store import Store


class EventReader:
    def __init__(self, store: Store, outbox):
        if store.path != outbox.store.path:
            raise ValueError("event reader and outbox must share authority")
        self.store = store
        self.outbox = outbox

    def unread(self, consumer_id: str, *, limit: int = 100) -> list[dict]:
        if not consumer_id or not 1 <= limit <= 250:
            raise ValueError("invalid consumer/limit")
        rows = self.outbox.consumer_events(consumer_id, limit=limit)
        # Most model controllers only need metadata; no prompts are ever stored
        # in the event stream, but payload may include identifiers. Redact by
        # default and provide monotonically increasing cursor IDs.
        return [{"id":r["id"],"task_id":r["task_id"],"attempt_id":r["attempt_id"],
                 "kind":r["kind"],"at":r["at"]} for r in rows]

    def ack(self, consumer_id: str, event_id: int) -> bool:
        return self.outbox.acknowledge_event(consumer_id,event_id)