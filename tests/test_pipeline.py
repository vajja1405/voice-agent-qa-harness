"""Event pipeline: fan-out, idempotency, retries, dead-lettering, partition ordering (in-memory bus)."""
import time

from pipeline.bus import InMemoryBus, partition_for
from pipeline.run import recorded_events, run
from pipeline.stages import STAGES, safety
from pipeline.worker import Aggregator, ProcessedStore, Worker


def _drive(workers, agg, rounds=200):
    for _ in range(rounds):
        busy = sum(w.step() for w in workers) + agg.step()
        if not busy:
            time.sleep(0.001)


def test_every_recorded_call_is_evaluated_by_all_four_stages():
    out = run(InMemoryBus(), copies=1, workers=2)
    assert out["events"] == 12 and out["completed"] == 12 and out["dead_lettered"] == 0


def test_same_call_always_maps_to_one_partition():
    assert len({partition_for("CA123", 4) for _ in range(20)}) == 1


def test_duplicate_delivery_is_processed_once():
    bus, store = InMemoryBus(), ProcessedStore()
    ev = recorded_events(1)[0] | {"produced_at": time.time()}
    bus.publish("calls.completed", ev["call_sid"], ev)
    bus.publish("calls.completed", ev["call_sid"], ev)          # redelivery of the same event
    w = Worker(bus, "transcript", STAGES["transcript"], store)
    w.step()
    assert w.stats == {"processed": 1, "duplicates": 1, "retried": 0, "dead": 0}


def test_transient_failure_is_retried_then_succeeds():
    bus, store, calls = InMemoryBus(), ProcessedStore(), {"n": 0}

    def flaky(ev):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("judge API timed out")
        return {"ok": True}

    ev = recorded_events(1)[0] | {"produced_at": time.time()}
    bus.publish("calls.completed", ev["call_sid"], ev)
    w = Worker(bus, "judge", flaky, store, backoff_s=0)
    agg = Aggregator(bus, ("judge",))
    _drive([w], agg)
    assert w.stats["retried"] == 1 and w.stats["processed"] == 1 and len(agg.complete) == 1


def test_poison_event_goes_to_dead_letter_queue_after_three_attempts():
    bus, store = InMemoryBus(), ProcessedStore()
    ev = recorded_events(1)[0] | {"produced_at": time.time()}
    bus.publish("calls.completed", ev["call_sid"], ev)
    w = Worker(bus, "audio", lambda e: 1 / 0, store, backoff_s=0)
    _drive([w], Aggregator(bus, ("audio",)))
    dlq = bus.poll("calls.dlq", "ops")
    assert w.stats["dead"] == 1 and w.stats["retried"] == 2
    assert dlq[0].value["attempts"] == 3 and "ZeroDivisionError" in dlq[0].value["error"]


def test_consumer_groups_are_isolated():
    bus = InMemoryBus()
    bus.publish("calls.completed", "k", {"x": 1})
    assert len(bus.poll("calls.completed", "g1")) == 1
    bus.commit("g1", bus.poll("calls.completed", "g1"))
    assert bus.poll("calls.completed", "g1") == [] and len(bus.poll("calls.completed", "g2")) == 1


def test_safety_signals_on_recorded_emergency_call():
    ev = next(e for e in recorded_events(1) if e["scenario"] == "emergency_escalation")
    out = safety(ev)
    assert out["signals"]["emergency_referral"] is True and out["needs_review"] is False
