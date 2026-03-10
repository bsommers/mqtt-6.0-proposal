# MQTT v6.0 Performance Analysis: High-Volume Use Cases

> **Focus:** Large distributed energy providers (DEPs), grid SCADA, and industrial IoT at scale — characterised by millions of sensors, sub-second telemetry, burst fault events, and mandatory regulatory audit trails.

---

## 1. Workload Profile

| Dimension | Typical DEP Scale |
|-----------|------------------|
| Sensors / endpoints | 1M–10M (smart meters, PMUs, RTUs, substations) |
| Steady-state throughput | 500k–3M msg/sec cluster-wide |
| Burst (fault/storm event) | 10×–50× steady state for 30–120 seconds |
| Message size | 64–512 bytes (telemetry); 1–50KB (commands, recipes) |
| Latency requirement | <10ms for control commands; 100–500ms acceptable for telemetry |
| Retention | 90 days regulatory minimum; 7 years for audit |
| Consumer count | 10–200 competing consumers per queue (analytics pipelines) |

---

## 2. Performance Bottlenecks in the Current Proposal

### 2.1 CAS Counter Contention at Scale

**Mechanism:** The Distributed Sequence Counter requires an atomic CAS increment on the cluster data grid for every `$queue/` PUBLISH. Under contention, CAS degrades from O(1) to O(retries × RTT) as threads spin on the atomic variable.

**Impact at DEP scale:** A single `$queue/scada/events` receiving 500k msg/sec from 50k RTUs means ~10k CAS operations per second per broker node competing for the same counter. At 1ms inter-node RTT, contention-driven retry cycles will cap throughput well below the theoretical maximum.

**Proposed fix — Partitioned Sequence Spaces:**

Assign each broker node a pre-allocated sequence range of size `W` (the "window size"). Nodes increment locally without cross-node CAS until they exhaust their window, then claim the next window atomically.

```
Node 1 window: Seq 1 – 1,000,000        (local counter, no CAS)
Node 2 window: Seq 1,000,001 – 2,000,000 (local counter, no CAS)
Node 3 window: Seq 2,000,001 – 3,000,000 (local counter, no CAS)
```

- Window claiming (CAS) is amortized across `W` messages — at W=1M and 500k msg/sec, each node claims a new window every ~2 seconds.
- Gaps between windows are valid: Seq 1,000,000 → 1,000,001 is a valid "gap" — consumers must tolerate intra-window ordering while the global order is maintained at window boundaries.
- Window size `W` should be a configurable queue property (`v6-seq-window-size`).

**New spec normative:** The Stream Sequence Number MUST be monotonically increasing within a node's assigned window. Global monotonicity across windows is RECOMMENDED but not REQUIRED — consumers MUST treat any Seq > HWM as processable regardless of gap size when the queue uses partitioned sequence windows.

---

### 2.2 High-Watermark Inadequacy Under Burst

**Current spec:** Consumer maintains a single `High-Watermark` integer (last processed Seq). Works for ordered, serial consumption.

**Problem at DEP scale:** During a grid fault event, 50 competing consumers receive messages in parallel. In-flight Seq values span a wide range simultaneously:

```
Consumer 1: processing Seq 10,001 (slow — database write)
Consumer 2: processing Seq 10,050 (fast)
Consumer 3: processing Seq 10,100 (fast)
```

If Consumer 2 and 3 finish before Consumer 1, their HWM would advance past Consumer 1's in-flight message. If Consumer 1 then crashes, the group HWM is ambiguous — "did we process 10,001?"

**Proposed fix — Sliding Window HWM:**

Replace the single HWM integer with a **min/max window** tracked per consumer group at the broker:

```
Group HWM = {
  committed:  10,000   (all Seq ≤ this are acknowledged by all group members)
  in_flight:  [10,001, 10,002, ..., 10,150]  (dispatched, awaiting PUBACK)
  max_dispatched: 10,150
}
```

- `committed` advances only when all Seq below the next gap are acknowledged.
- The broker tracks in-flight locks as a bitset bounded by `Receive Maximum`.
- Consumer crash recovery: any in-flight Seq belonging to the crashed consumer is re-dispatched to the next available consumer.
- Client-side HWM for exactly-once deduplication remains a single integer (`committed`), not the full window.

**New spec normative:** Brokers implementing SQMC competing consumer mode MUST track a per-group `committed_hwm` (the highest Seq for which all lower Seqs are acknowledged) in addition to the per-consumer in-flight lock set.

---

### 2.3 Quorum Write Latency vs. Real-Time Telemetry

**Current spec:** All `$queue/` PUBLISH operations require a quorum write before PUBACK. At replication factor 2 and 1ms inter-node RTT, this adds 2–5ms per message.

**Impact at DEP scale:** PMU (Phasor Measurement Unit) data arrives at 60 samples/sec per device. A 2–5ms PUBACK delay is acceptable. But for 50k PMUs generating 3M msg/sec total, quorum write serialisation creates head-of-line blocking in the broker's replication pipeline — effective throughput drops by 40–60% compared to async replication.

**Proposed fix — Durability Tier Namespaces:**

Split the `$queue/` namespace into three tiers with different durability contracts:

| Namespace | Durability | Write Path | Use Case |
|-----------|-----------|------------|----------|
| `$queue/` | Synchronous quorum | PUBACK after N replicas | Commands, audit, SECS/GEM S2F21 |
| `$stream/` | Async replication | PUBACK after local write; replication in background | High-frequency telemetry, PMU data |
| `$log/` | Append-only, eventual | PUBACK immediately; batched replication | FDC data, bulk sensor history |

- The same FETCH, Seq, and Epoch semantics apply to all three tiers.
- `$stream/` and `$log/` topics carry a `Durability` property (`0x43`) in PUBLISH indicating the tier: `0x01` = sync quorum, `0x02` = async, `0x03` = eventual.
- Consumers subscribing to `$stream/` or `$log/` MUST tolerate occasional Seq gaps (due to async write failures) and SHOULD NOT use exactly-once semantics based on Seq alone.

---

### 2.4 FETCH Batch Size Tuning for Burst Recovery

**Current spec:** `Batch Size` is a fixed integer per FETCH request.

**Problem:** During burst recovery (after a 60-second grid storm event), a consumer with a 10M-message backlog issuing `batch=100` requests requires 100k round-trips to drain the queue. At 10ms RTT, that is 16 minutes of drain time.

**Proposed fix — Adaptive Batch Size:**

Add two optional FETCH properties:

- `v6-batch-max`: Upper bound on batch size the consumer will accept (consumer protection).
- `v6-batch-target-ms`: Target delivery window in milliseconds. The broker calculates the batch size needed to fill the window based on queue throughput, bounded by `v6-batch-max`.

For a consumer that wants "deliver as many as I can process in 500ms", the broker calculates:

```
batch = min(v6-batch-max, queue_throughput_per_ms × 500)
```

This eliminates the need for consumers to manually tune batch sizes as queue depth fluctuates.

---

### 2.5 Rate Limiting Granularity

**Current spec:** Throughput Limit (Property `0x41`) is per-connection in KB/s.

**Problem for DEPs:** A DEP SCADA system has thousands of client connections sharing the same broker. A per-connection limit cannot prevent a single rogue data pipeline from saturating broker NIC bandwidth while legitimate control traffic is dropped.

**Proposed fixes:**

1. **Per-queue rate limit:** Add a `v6-queue-rate-limit` User Property to SUBSCRIBE, specifying max msgs/sec the broker will release from that queue to this consumer group — independent of connection-level limits.

2. **Priority-based admission:** High-priority messages (`v6-priority: 255`) bypass the rate limiter. This ensures S2F21 (process start) commands are never delayed by FDC data storms.

3. **Credit-based flow control:** Replace the token-bucket CONNACK approach with an explicit credit system:
   - Broker sends `CREDIT {queue_name, msgs_per_sec}` in CONNACK or a new control topic.
   - Consumer sends `CREDIT_RETURN` when it can accept more.
   - This is analogous to AMQP 1.0's link credits and prevents both flooding and starvation.

---

### 2.6 Epoch Reset Thundering Herd

**Current spec:** On Epoch reset, all consumers connected to the affected queue simultaneously discard their HWMs and begin full resyncs.

**Problem at DEP scale:** With 200 competing consumers on `$queue/grid/events`, a single partition event triggers 200 simultaneous full resyncs — each reading the queue from Seq=0. This is a thundering herd that can exhaust broker I/O for minutes.

**Proposed fix — Staggered Resync:**

Add a `v6-resync-jitter-ms` property to DISCONNECT (Reason Code 0xA0). Each consumer receives a different jitter value (e.g., uniformly distributed over 0–30,000ms). Consumers delay their CONNECT retry and resync by this value. The broker staggers the resyncs, preventing I/O saturation.

For the broker to generate useful jitter values:
```
jitter_for_consumer_i = (consumer_group_size × resync_window_ms / N) × i
```
where `i` is the consumer's ordinal within the group (known from SQMC group membership).

---

## 3. Updated Property Table

| ID | Name | Type | Packets | Purpose |
|----|------|------|---------|---------|
| `0x30` | Stream Sequence | 4B Int | PUBLISH | Monotonic message ID |
| `0x35` | Stream Epoch | 2B Int | PUBLISH, CONNACK | Cluster era |
| `0x41` | Throughput Limit | 4B Int (KB/s) | CONNACK | Per-connection rate cap |
| `0x42` | Batch Size | 4B Int | FETCH | Max messages per batch |
| `0x43` | **Durability Tier** | 1B Enum | PUBLISH | `0x01` sync, `0x02` async, `0x03` eventual |
| `0x44` | **Batch Target Ms** | 2B Int | FETCH | Target delivery window for adaptive batching |
| `0x45` | **Resync Jitter Ms** | 2B Int | DISCONNECT (0xA0) | Staggered resync delay |

---

## 4. Namespace Additions

| Namespace | Durability | Sequence | Exactly-Once |
|-----------|-----------|----------|--------------|
| `$queue/` | Sync quorum | Strict monotonic | Supported |
| `$stream/` | Async replicated | Best-effort monotonic | Not guaranteed |
| `$log/` | Eventual / append | Monotonic within node | Not supported |
| `$SYS/queues/*/fetch` | N/A (control) | N/A | N/A |

---

## 5. Summary: Adaptations for DEP Scale

| Problem | Scale Trigger | Fix |
|---------|--------------|-----|
| CAS counter contention | >100k msg/sec per queue | Partitioned sequence windows (`v6-seq-window-size`) |
| Single-integer HWM inadequate | >10 competing consumers | Sliding window HWM — committed + in-flight bitset |
| Quorum write latency | >1M msg/sec telemetry | Durability tier namespaces (`$stream/`, `$log/`) |
| Slow backlog drain | Post-burst recovery | Adaptive batch size (`v6-batch-target-ms`) |
| Per-connection rate limit too coarse | Thousands of connections | Per-queue rate limit + priority admission bypass |
| Epoch reset thundering herd | >50 consumers, partition event | Staggered resync with `v6-resync-jitter-ms` |
