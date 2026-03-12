# Executive Summary: MQTT Version 6.0

## What Is This?

**MQTT v6.0** is a proposed evolutionary extension to the MQTT v5.0 protocol that adds **targeted industrial queuing primitives** to the broker tier — without changing the edge protocol that millions of devices already run.

> **The core problem:** MQTT currently guarantees delivery — but it cannot guarantee state reconstruction. After a device reconnect, broker restart, or cluster failover, neither the client nor the broker has a standard mechanism to answer: "Did we miss any messages? Did a command execute twice? Can we reconstruct the system's current state?" MQTT v6.0 adds the minimal metadata needed to answer these questions deterministically.

A companion compatibility profile — **MQTT Reliable Secure Streams Profile (MQTT-RSSP)** — provides the same semantics over existing MQTT 5.0 brokers without requiring protocol-level changes, enabling incremental adoption.

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
- **No cluster-aware consistency.** When a broker node fails and a client reconnects to a new node, the protocol has no mechanism to detect what was lost or resume from an exact point.

These gaps are currently "solved" by embedding sequence numbers, idempotency keys, and acknowledgment logic in message payloads — a non-standard, non-interoperable approach.

---

## The Solution

MQTT v6.0 introduces six targeted additions to the protocol. In compatibility mode (Track B), these additions use v5.0 User Properties and control topics that are transparent to existing parsers. In native mode (Track A, Protocol Level 6), a new packet type (FETCH) and new property IDs are introduced that require updated client libraries and brokers:

### 1. 32-bit Stream Sequence Numbers
A new Property (`0x30`) carrying a monotonic, cluster-wide 32-bit integer is attached to every message in the `$queue/` namespace. This allows consumers to detect gaps (`received Seq 1002 but expected 1001`), perform deduplication, and implement application-level exactly-once processing without embedding logic in payloads.

### 2. Stream Epoch
A new Property (`0x35`) that tracks the "era" of a queue. When a broker cluster suffers a catastrophic failure and cannot guarantee sequence continuity, the Epoch is incremented. Consumers that detect an Epoch change know they must discard local idempotency state and re-synchronize — analogous to a SECS/GEM Establish Communications (S1F13) reset.

### 3. Named Durable Queues (`$queue/` namespace)
Topics prefixed with `$queue/` are treated as first-class queue entities: persisted to non-volatile storage, sequenced, and retained indefinitely until consumed or expired — independent of any client session. This replaces the implicit, session-bound queue model of v5.0.

### 4. Pull-Based Flow Control (FETCH)
A new `FETCH` Control Packet (Type 16) lets consumers explicitly request batches of messages from the broker. The broker holds messages in the persistent queue and releases them only when asked. This eliminates the "thundering herd" problem where a recovering consumer is flooded with backlogged messages. For v5.0-compat environments, a Virtual FETCH mechanism uses a `$SYS/` control topic instead.

### 5. Single-Queue Multi-Consumer (SQMC) Semantics
An extension to `SUBSCRIBE` that adds two new consumer modes beyond the loose `$share/` model:
- **Competing:** Messages are distributed to exactly one consumer via round-robin, with strict message locking and immediate failover if the consumer disconnects before acknowledging.
- **Exclusive:** One designated consumer receives all messages; others are hot standbys that take over instantly on failure, preserving strict ordering.

### 6. Mandatory TLS 1.3 + Optional Payload Encryption (Zero Trust)
Native Mode v6.0 connections MUST use TLS 1.3, eliminating the vulnerable cipher suites and additional round-trip latency of TLS 1.2. For deployments where the broker must be treated as an untrusted intermediary (zero trust architectures), v6.0 introduces three optional key metadata properties (`0x3A` Key ID, `0x3B` Algorithm, `0x3C` Key Version) that allow end-to-end encrypted payloads to carry the information consumers need to decrypt them — without placing any key material in the protocol. Key management (distribution, rotation, revocation) is explicitly an application-layer responsibility. This feature is entirely opt-in; deployments using TLS 1.3 transport encryption alone are fully conformant.

### Where MQTT v6.0 Fits in the Industrial Stack

MQTT v6.0 occupies a precise layer in the modern industrial architecture:

```
Layer 4 – Industrial AI Agents       (autonomous decisions, anomaly detection)
Layer 3 – Deterministic State        (digital twins, event sourcing, process models)
Layer 2 – Telemetry Integrity        ← MQTT v6.0 fills this layer
Layer 1 – Device Messaging           (MQTT pub/sub — unchanged)
```

Layer 1 is MQTT v5.0. Layer 2 is currently built ad-hoc by every deployment, differently and incompatibly. MQTT v6.0 standardizes Layer 2 so that Layers 3 and 4 — digital twins and AI agents — can be built on a reliable foundation.

Without Layer 2, industrial AI agents receive incomplete event histories. Digital twins drift. Recovery after disruption requires manual reconciliation. MQTT v6.0 eliminates the need to build Layer 2 from scratch in every deployment.

---

## Business Impact

| Use Case | v5.0 Risk | v6.0 Benefit |
|----------|-----------|--------------|
| Semiconductor FAB (SECS/GEM) | Broker restart can silently lose a "Process Start" (S2F21) command, ruining a wafer | Epoch resync + sequence gaps ensure the command is detected as lost and retried |
| Industrial FDC Data Collection | High-frequency sensor data floods the host system, causing crashes | FETCH-based backpressure keeps the broker as the buffer; host processes at its own rate |
| Financial Message Bus | Duplicate processing of payment events due to lack of idempotency primitives | 32-bit Sequence as an idempotency key, checked before executing business logic |
| Multi-node Broker Cluster | Client failover to a new node silently re-delivers or loses messages | Last Received Seq in CONNECT allows new node to resume delivery from exact position |
| High-availability IoT Gateways | Primary/backup consumer logic must be hand-coded in application layer | Exclusive consumer mode with automatic hot-standby failover built into the protocol |

---

## Compatibility Strategy

MQTT v6.0 is backward-compatible with MQTT v5.0 for all unchanged v5.0 use cases: existing packet types, properties, topics, and semantics continue to work as before. A v5.0 or v3.1.1 client connecting to a v6.0 broker for standard pub/sub sees no difference in behavior.

Compatibility is not wire-transparent for v6.0-only features (FETCH, `$queue/`, Stream Sequence properties, `last-seq`/`epoch`); those require either Protocol Level 6 or the specified v5.0 compatibility mode. Specifically:

- All new properties use IDs in the currently unassigned range (`0x30–0x45`). The v5.0 spec requires conformant implementations to ignore unknown property IDs, so these properties are safe in mixed environments. However, these IDs are not formally reserved for v6.0 until an OASIS submission is accepted — a pre-standardization risk that the Compatibility Layer (User Properties) mitigates.
- The `$queue/` namespace is ACL-protected; v5.0 clients that have not completed the v6.0 handshake are rejected.
- A **Compatibility Layer** maps every native v6.0 feature to v5.0 User Properties and system topics, enabling mixed-version deployments.
- A negotiation handshake (`mqtt-ext: v6.0` in CONNECT/CONNACK) allows clients and brokers to detect v6.0 support and fall back gracefully.

**The key guarantee:** if you do not use `$queue/`, FETCH, or Stream Sequence properties, your deployment is fully compatible with v5.0 — no behavioral changes, no additional overhead, no migration required. See [Compatibility Boundaries](motivation.md#compatibility-boundaries) for the full scenario matrix.

Security considerations for the new primitives — including ACL requirements for `$queue/`, Epoch integrity, sequence number side-channels, and High-Watermark persistence — are defined normatively in Section 7 of the [specification](spec/mqtt-v6.0-spec.md#7-security-considerations).

---

## Scope and Standardization Path

This proposal is intentionally scoped to a single problem domain: adding durable, ordered queuing primitives for industrial broker-tier use cases. It does not attempt to replace general-purpose message queues, add stream processing, or modify MQTT's core pub/sub semantics. The features are additive and opt-in.

The recommended standardization path is **layered**: submit the core primitives (Stream Sequence, Epoch, `$queue/` namespace) as a first submission, with FETCH and SQMC as follow-on extensions if the core is accepted. This allows the committee to evaluate the proposal incrementally.

## Recommendation

Adopt MQTT v6.0 across three dimensions: operational deployment, OASIS standardization, and reference implementation.

### Deployment Phases (Operational)

- **Phase 1 — Compatible Extension (Track B):** Deploy via the HiveMQ Extension Plugin using the User Property shim (`v6-seq`, `v6-epoch`, `v6-semantics`). Zero broker downtime required. Works on any MQTT 5.0 broker today.
- **Phase 2 — Native v6.0 (Track A):** Once the ecosystem supports Protocol Level 6, migrate to native FETCH packets and Properties `0x30`/`0x35`/`0x3A`–`0x3C` for full binary efficiency and protocol-level enforcement.

### Standardization Path (OASIS)

- **Phase 1 OASIS submission — MQTT Reliable Secure Streams Profile (MQTT-RSSP):** Submit the Track B compatible layer as a broker-transparent interoperability standard. No breaking changes; works on any MQTT 5.0 broker. Establishes the semantic framework (named durable queues, stream sequencing, SQMC modes, Zero Trust key metadata) without requiring a protocol version bump.
- **Phase 2 OASIS submission — Native v6.0 wire extensions:** Propose Property IDs `0x30`–`0x3C` and the Type 16 FETCH packet as a formal protocol extension once MQTT-RSSP is accepted and the semantic model is validated by the broader ecosystem.

### Reference Implementation (HiveMQ)

A reference implementation can be built using the HiveMQ Extension SDK today:

| Feature | HiveMQ API |
|---------|-----------|
| Sequence injection | `PublishInboundInterceptor` |
| Client throttling | `ClientService.blockClient()` / `unblockClient()` |
| Queue persistence | `ManagedPersistenceService` |
| Cluster epoch management | `ClusterService` + consistent hashing on queue names |

A proof-of-concept can be built today using a HiveMQ Extension alongside a Python `gmqtt` client shim, without any changes to the core broker binary.
