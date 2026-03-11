# Executive Summary: MQTT Version 6.0

## What Is This?

**MQTT v6.0** is a proposed evolutionary extension to the MQTT v5.0 protocol that adds **targeted industrial queuing primitives** to the broker tier — without changing the edge protocol that millions of devices already run.

It is **not** a general-purpose upgrade. It is **not** "MQTT trying to become Kafka." It targets a specific tier of deployment: **semiconductor manufacturing ([SECS/GEM](https://en.wikipedia.org/wiki/SECS/GEM)), energy grid SCADA ([IEC 61850](https://en.wikipedia.org/wiki/IEC_61850)), and large-scale industrial IoT** — environments where MQTT v5.0 is already deployed at the edge but operators are forced to bolt on Kafka or AMQP at the broker tier to get durable queuing, ordered delivery, and consumer group semantics. v6.0 eliminates that bridge.

**Why standardize now rather than ship vendor extensions first?** Because the extension-first path leads to fragmentation — just as `$SYS/` was implemented differently by every broker and remains unstandardized 15 years later. Standardizing these patterns at the protocol level before vendors fragment gives the ecosystem a single interoperable wire representation. See [Why Standardize Now](rebuttals.md#why-standardize-now--not-ship-an-extension-first) for the full argument.

For a detailed response to criticisms including "v5.0 already does this" and "this should be application-level," see [Addressing Criticisms](rebuttals.md).

---

## The Problem

MQTT v5.0 is excellent for lightweight telemetry and command delivery. However, it has structural limitations that force enterprise users to embed reliability logic inside application payloads — a pattern already codified by [Eclipse Sparkplug B](https://sparkplug.eclipse.org/specification/) with its application-layer sequence numbers, and replicated ad-hoc by every industrial MQTT deployment that needs message ordering guarantees:

- **No global message ordering.** The 16-bit Packet Identifier is per-session, transient, and recycled — making it impossible for a consumer to detect gaps caused by broker restarts or cluster failovers.
- **Push-only delivery.** The broker pushes all messages to consumers as fast as they arrive. A slow consumer cannot apply backpressure without complex out-of-band coordination.
- **Session-bound queues.** Messages are only held for a client while its session exists. There is no way to create a durable queue that outlives client connections.
- **Loose shared subscription semantics.** MQTT's `$share/` mechanism provides load balancing but lacks strict exclusive-consumer and message-locking semantics needed for transactional processing.
- **No cluster-aware consistency.** When a HiveMQ node fails and a client reconnects to a new node, the protocol has no mechanism to detect what was lost or resume from an exact point.

These gaps are currently "solved" by embedding sequence numbers, idempotency keys, and acknowledgment logic in message payloads — a non-standard, non-interoperable approach.

---

## The Solution

MQTT v6.0 introduces five targeted additions to the protocol, all backward-compatible with existing v5.0 parsers:

### 1. 32-bit Stream Sequence Numbers
A new Property (`0x30`) carrying a monotonic, cluster-wide 32-bit integer is attached to every message in the `$queue/` namespace. This allows consumers to detect gaps (`received Seq 1002 but expected 1001`), perform deduplication, and implement application-level exactly-once processing without embedding logic in payloads.

### 2. Stream Epoch
A new Property (`0x35`) that tracks the "era" of a queue. When a HiveMQ cluster suffers a catastrophic failure and cannot guarantee sequence continuity, the Epoch is incremented. Consumers that detect an Epoch change know they must discard local idempotency state and re-synchronize — analogous to a SECS/GEM Establish Communications (S1F13) reset.

### 3. Named Durable Queues (`$queue/` namespace)
Topics prefixed with `$queue/` are treated as first-class queue entities: persisted to non-volatile storage, sequenced, and retained indefinitely until consumed or expired — independent of any client session. This replaces the implicit, session-bound queue model of v5.0.

### 4. Pull-Based Flow Control (FETCH)
A new `FETCH` Control Packet (Type 16) lets consumers explicitly request batches of messages from the broker. The broker holds messages in the persistent queue and releases them only when asked. This eliminates the "thundering herd" problem where a recovering consumer is flooded with backlogged messages. For v5.0-compat environments, a Virtual FETCH mechanism uses a `$SYS/` control topic instead.

### 5. Single-Queue Multi-Consumer (SQMC) Semantics
An extension to `SUBSCRIBE` that adds two new consumer modes beyond the loose `$share/` model:
- **Competing:** Messages are distributed to exactly one consumer via round-robin, with strict message locking and immediate failover if the consumer disconnects before acknowledging.
- **Exclusive:** One designated consumer receives all messages; others are hot standbys that take over instantly on failure, preserving strict ordering.

---

## Business Impact

| Use Case | v5.0 Risk | v6.0 Benefit |
|----------|-----------|--------------|
| Semiconductor FAB (SECS/GEM) | Broker restart can silently lose a "Process Start" (S2F21) command, ruining a wafer | Epoch resync + sequence gaps ensure the command is detected as lost and retried |
| Industrial FDC Data Collection | High-frequency sensor data floods the host system, causing crashes | FETCH-based backpressure keeps the broker as the buffer; host processes at its own rate |
| Financial Message Bus | Duplicate processing of payment events due to lack of idempotency primitives | 32-bit Sequence as an idempotency key, checked before executing business logic |
| Multi-node HiveMQ Cluster | Client failover to a new node silently re-delivers or loses messages | Last Received Seq in CONNECT allows new node to resume delivery from exact position |
| High-availability IoT Gateways | Primary/backup consumer logic must be hand-coded in application layer | Exclusive consumer mode with automatic hot-standby failover built into the protocol |

---

## Compatibility Strategy

v6.0 is designed to coexist with v5.0:

- All new properties use IDs in the reserved range (`0x30–0x45`) that v5.0 brokers and clients are required to ignore.
- The `$queue/` namespace gracefully degrades to standard topic behavior on v5.0 brokers (with appropriate ACL controls).
- A **Compatibility Layer** maps every native v6.0 feature to v5.0 User Properties and system topics, enabling mixed-version deployments.
- A negotiation handshake (`mqtt-ext: v6.0` in CONNECT/CONNACK) allows clients and brokers to detect v6.0 support and fall back gracefully.

---

## Implementation Path for HiveMQ

The broker-side implementation uses the HiveMQ Extension SDK:

| Feature | HiveMQ API |
|---------|-----------|
| Sequence injection | `PublishInboundInterceptor` |
| Client throttling | `ClientService.blockClient()` / `unblockClient()` |
| Queue persistence | `ManagedPersistenceService` |
| Cluster epoch management | `ClusterService` + consistent hashing on queue names |

A proof-of-concept can be built today using a HiveMQ Extension alongside a Python `gmqtt` client shim, without any changes to the core broker binary.

---

## Recommendation

Adopt MQTT v6.0 as a **two-phase rollout**:

1. **Phase 1 — Compatible Extension:** Deploy the HiveMQ Extension Plugin that intercepts `v6-*` user properties. Migrate clients to the Python/Java shim. Zero broker downtime required.
2. **Phase 2 — Native v6.0:** Once the ecosystem supports Protocol Level 6, deprecate the shim layer and use native FETCH packets with full binary efficiency.

This proposal is production-ready as a HiveMQ extension today and provides a clear path to a formal OASIS standardization submission.
