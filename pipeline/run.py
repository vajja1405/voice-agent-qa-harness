"""
Replay recorded calls through the event pipeline and measure throughput and end-to-end latency.

    python -m pipeline.run --bus memory --copies 50 --workers 1
    python -m pipeline.run --bus kafka  --copies 50 --workers 4   # docker compose -f docker-compose.kafka.yml up -d

Each copy of each recorded call becomes a distinct CallCompleted event (unique event_id,
same call_sid key), so partitioning and per-call ordering behave as they would in production.
The judge stage uses dry-run grades unless PIPELINE_LIVE_JUDGE=1 (no API spend by default).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np

from pipeline.bus import InMemoryBus, KafkaBus
from pipeline.stages import STAGES
from pipeline.worker import Aggregator, ProcessedStore, Worker

HERE = Path(__file__).resolve().parents[1]


def recorded_events(copies: int) -> list[dict]:
    events = []
    for path in sorted((HERE / "transcripts").glob("*.json")):
        call = json.loads(path.read_text())
        for c in range(copies):
            events.append({"event_id": f"{call['call_sid']}:{c}", "call_sid": call["call_sid"],
                           "scenario": call["scenario"], "transcript_path": str(path.relative_to(HERE)),
                           "attempt": 1})
    return events


def run(bus, copies: int, workers: int, stage_delay_s: float = 0.0, timeout_s: float = 300) -> dict:
    store = ProcessedStore()
    handlers = dict(STAGES)
    if stage_delay_s:  # model a slow external call (e.g. an LLM judge) without spending on one
        slow = handlers["judge"]
        handlers["judge"] = lambda ev: (time.sleep(stage_delay_s), slow(ev))[1]
    pool = [Worker(bus, s, h, store, member=m, members=workers) for s, h in handlers.items() for m in range(workers)]
    agg = Aggregator(bus, tuple(handlers))
    events = recorded_events(copies)
    stop = threading.Event()

    def loop(w):
        while not stop.is_set():
            if not w.step():
                time.sleep(0.005)

    threads = [threading.Thread(target=loop, args=(w,), daemon=True) for w in pool + [agg]]
    for t in threads:
        t.start()
    t0 = time.time()
    for ev in events:
        bus.publish("calls.completed", ev["call_sid"], ev | {"produced_at": time.time()})
    if hasattr(bus, "flush"):
        bus.flush()
    while len(agg.complete) < len(events) and time.time() - t0 < timeout_s:
        time.sleep(0.02)
    elapsed = time.time() - t0
    stop.set()
    for t in threads:
        t.join(timeout=2)
    lat = np.array(agg.latencies) * 1000
    return {"events": len(events), "completed": len(agg.complete), "workers_per_stage": workers,
            "elapsed_s": round(elapsed, 2), "events_per_s": round(len(agg.complete) / elapsed, 1),
            "e2e_ms": {"p50": round(float(np.percentile(lat, 50)), 1), "p95": round(float(np.percentile(lat, 95)), 1),
                       "p99": round(float(np.percentile(lat, 99)), 1)} if len(lat) else None,
            "duplicates_skipped": sum(w.stats["duplicates"] for w in pool),
            "dead_lettered": sum(w.stats["dead"] for w in pool),
            "flagged_for_review": sum(r["safety"]["needs_review"] for r in agg.complete.values())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bus", choices=["memory", "kafka"], default="memory")
    ap.add_argument("--copies", type=int, default=50)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--stage-delay-ms", type=float, default=0)
    a = ap.parse_args()
    bus = KafkaBus() if a.bus == "kafka" else InMemoryBus()
    out = run(bus, a.copies, a.workers, a.stage_delay_ms / 1000) | {"bus": a.bus, "judge_delay_ms": a.stage_delay_ms}
    if hasattr(bus, "close"):
        bus.close()
    print(json.dumps(out))


if __name__ == "__main__":
    main()
