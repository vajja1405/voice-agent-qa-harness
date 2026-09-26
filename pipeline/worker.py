"""
pipeline/worker.py
──────────────────
Consumer runtime with the reliability properties the pipeline depends on:

  • at-least-once delivery + idempotent handlers: a (group, event_id) seen before is skipped
  • bounded retries: a failed event is re-published to `calls.retry` with attempt+1 and
    exponential not-before time; after MAX_ATTEMPTS it goes to `calls.dlq` with the error
  • offsets are committed only after the result (or retry/DLQ record) has been published
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from pipeline.bus import Bus

MAX_ATTEMPTS = 3


class ProcessedStore:
    """Idempotency ledger shared by all workers (SQLite; swap for Postgres/Redis in production)."""

    def __init__(self, path: str = ":memory:") -> None:
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS processed (grp TEXT, event_id TEXT, PRIMARY KEY (grp, event_id))")
        self._lock = threading.Lock()

    def claim(self, group: str, event_id: str) -> bool:
        with self._lock:
            cur = self._db.execute("INSERT OR IGNORE INTO processed VALUES (?, ?)", (group, event_id))
            self._db.commit()
            return cur.rowcount == 1

    def release(self, group: str, event_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM processed WHERE grp=? AND event_id=?", (group, event_id))
            self._db.commit()


@dataclass
class Worker:
    bus: Bus
    stage: str
    handler: Callable[[dict], dict]
    store: ProcessedStore
    member: int = 0
    members: int = 1
    backoff_s: float = 0.05
    clock: Callable[[], float] = time.time
    stats: dict = field(default_factory=lambda: {"processed": 0, "duplicates": 0, "retried": 0, "dead": 0})

    @property
    def group(self) -> str:
        return f"stage-{self.stage}"

    def _handle(self, event: dict) -> None:
        eid = event["event_id"]
        if not self.store.claim(self.group, eid):
            self.stats["duplicates"] += 1
            return
        try:
            out = self.handler(event)
        except Exception as exc:  # noqa: BLE001 — every failure is routed, never swallowed
            self.store.release(self.group, eid)
            attempt = event.get("attempt", 1)
            if attempt >= MAX_ATTEMPTS:
                self.bus.publish("calls.dlq", event["call_sid"], {"stage": self.stage, "event": event,
                                                                   "error": repr(exc), "attempts": attempt})
                self.stats["dead"] += 1
            else:
                retry = event | {"attempt": attempt + 1, "target_stage": self.stage,
                                 "not_before": self.clock() + self.backoff_s * 2 ** (attempt - 1)}
                self.bus.publish("calls.retry", event["call_sid"], retry)
                self.stats["retried"] += 1
            return
        self.bus.publish("results", event["call_sid"], {"event_id": eid, "call_sid": event["call_sid"],
                                                        "stage": self.stage, "produced_at": event["produced_at"],
                                                        "output": out})
        self.stats["processed"] += 1

    def step(self) -> int:
        n = 0
        batch = self.bus.poll("calls.completed", self.group, self.member, self.members)
        for m in batch:
            self._handle(m.value)
        self.bus.commit(self.group, batch)
        n += len(batch)
        retry_group = f"{self.group}-retry"
        batch = self.bus.poll("calls.retry", retry_group, self.member, self.members)
        done = []
        for m in batch:
            ev = m.value
            if ev.get("target_stage") != self.stage:
                done.append(m)
                continue
            if ev.get("not_before", 0) > self.clock():
                break  # keep ordering within the partition; try again next step
            self._handle(ev)
            done.append(m)
        self.bus.commit(retry_group, done)
        return n + len(done)


class Aggregator:
    """Joins the four stage results per event and records end-to-end latency."""

    def __init__(self, bus: Bus, stages: tuple[str, ...], clock: Callable[[], float] = time.time) -> None:
        self.bus, self.stages, self.clock = bus, stages, clock
        self.partial: dict[str, dict] = {}
        self.complete: dict[str, dict] = {}
        self.latencies: list[float] = []

    def step(self) -> int:
        batch = self.bus.poll("results", "aggregator")
        for m in batch:
            r = m.value
            if r["event_id"] in self.complete:
                continue
            row = self.partial.setdefault(r["event_id"], {"call_sid": r["call_sid"]})
            row[r["stage"]] = r["output"]
            if all(s in row for s in self.stages):
                self.complete[r["event_id"]] = self.partial.pop(r["event_id"])
                self.latencies.append(self.clock() - r["produced_at"])
        self.bus.commit("aggregator", batch)
        return len(batch)
