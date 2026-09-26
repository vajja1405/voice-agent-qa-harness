"""
pipeline/bus.py
───────────────
A minimal message-bus contract with two interchangeable implementations:

  InMemoryBus  – partitions, per-group offsets and consumer groups in-process (tests, CI, laptops)
  KafkaBus     – the same contract on Apache Kafka via confluent-kafka (docker-compose.kafka.yml)

Semantics shared by both: messages are keyed by call_sid, so every event for one call lands on
the same partition and is processed in order; each consumer group sees every message once; a
member of a group owns a subset of partitions.
"""
from __future__ import annotations

import json
import threading
import zlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

TOPICS = {
    "calls.completed": 4,
    "calls.retry": 4,
    "calls.dlq": 1,
    "results": 4,
}


@dataclass(frozen=True)
class Message:
    topic: str
    partition: int
    offset: int
    key: str
    value: dict


class Bus(Protocol):
    def publish(self, topic: str, key: str, value: dict) -> None: ...
    def poll(self, topic: str, group: str, member: int, members: int, max_messages: int = 100) -> list[Message]: ...
    def commit(self, group: str, messages: Iterable[Message]) -> None: ...


def partition_for(key: str, partitions: int) -> int:
    return zlib.crc32(key.encode()) % partitions


class InMemoryBus:
    def __init__(self, topics: dict[str, int] = TOPICS) -> None:
        self.partitions = dict(topics)
        self._logs: dict[tuple[str, int], list[Message]] = defaultdict(list)
        self._offsets: dict[tuple[str, str, int], int] = defaultdict(int)
        self._lock = threading.Lock()

    def publish(self, topic: str, key: str, value: dict) -> None:
        p = partition_for(key, self.partitions[topic])
        with self._lock:
            log = self._logs[(topic, p)]
            log.append(Message(topic, p, len(log), key, json.loads(json.dumps(value))))

    def _owned(self, topic: str, member: int, members: int) -> list[int]:
        return [p for p in range(self.partitions[topic]) if p % members == member]

    def poll(self, topic, group, member=0, members=1, max_messages=100):
        out: list[Message] = []
        with self._lock:
            for p in self._owned(topic, member, members):
                start = self._offsets[(group, topic, p)]
                out.extend(self._logs[(topic, p)][start:start + max_messages - len(out)])
                if len(out) >= max_messages:
                    break
        return out

    def commit(self, group, messages):
        with self._lock:
            for m in messages:
                k = (group, m.topic, m.partition)
                self._offsets[k] = max(self._offsets[k], m.offset + 1)

    def lag(self, topic: str, group: str) -> int:
        with self._lock:
            return sum(len(self._logs[(topic, p)]) - self._offsets[(group, topic, p)]
                       for p in range(self.partitions[topic]))


class KafkaBus:
    """Same contract on Kafka. Each (group, member) gets its own consumer; Kafka assigns partitions."""

    def __init__(self, bootstrap: str = "localhost:9092") -> None:
        from confluent_kafka import Producer
        from confluent_kafka.admin import AdminClient, NewTopic

        self.bootstrap = bootstrap
        admin = AdminClient({"bootstrap.servers": bootstrap})
        existing = set(admin.list_topics(timeout=10).topics)
        new = [NewTopic(t, num_partitions=n, replication_factor=1) for t, n in TOPICS.items() if t not in existing]
        for f in admin.create_topics(new).values() if new else []:
            f.result()
        self._producer = Producer({"bootstrap.servers": bootstrap, "enable.idempotence": True,
                                   "linger.ms": 5, "acks": "all"})
        self._consumers: dict[tuple[str, str, int], object] = {}
        self._owner: dict[tuple, object] = {}

    def publish(self, topic, key, value):
        self._producer.produce(topic, key=key.encode(), value=json.dumps(value).encode())
        self._producer.poll(0)

    def flush(self):
        self._producer.flush(10)

    def _consumer(self, topic, group, member):
        from confluent_kafka import Consumer
        k = (topic, group, member)
        if k not in self._consumers:
            c = Consumer({"bootstrap.servers": self.bootstrap, "group.id": group,
                          "enable.auto.commit": False, "auto.offset.reset": "earliest",
                          "client.id": f"{group}-{member}"})
            c.subscribe([topic])
            self._consumers[k] = c
        return self._consumers[k]

    def poll(self, topic, group, member=0, members=1, max_messages=100):
        c = self._consumer(topic, group, member)
        out = []
        for m in c.consume(num_messages=max_messages, timeout=0.2):
            if m.error():
                continue
            msg = Message(m.topic(), m.partition(), m.offset(), (m.key() or b"").decode(), json.loads(m.value()))
            self._owner[(group, msg.topic, msg.partition, msg.offset)] = c
            out.append(msg)
        return out

    def commit(self, group, messages):
        from confluent_kafka import TopicPartition
        per_consumer: dict[int, tuple[object, dict]] = {}
        for m in messages:
            c = self._owner.pop((group, m.topic, m.partition, m.offset), None)
            if c is None:
                continue
            _, offs = per_consumer.setdefault(id(c), (c, {}))
            key = (m.topic, m.partition)
            offs[key] = max(offs.get(key, 0), m.offset + 1)
        for c, offs in per_consumer.values():
            c.commit(offsets=[TopicPartition(t, p, o) for (t, p), o in offs.items()], asynchronous=False)

    def close(self):
        self.flush()
        for c in self._consumers.values():
            c.close()
