# Why MQTT v6.0? Motivation, Rationale, and Intended Audience

> **Status:** Part of the MQTT v6.0 Draft Proposal — March 2026

---

## 0. Important Context: What This Proposal Is Not

**This is not "MQTT trying to become Kafka."** This is not a general-purpose upgrade. Most MQTT deployments do not need v6.0 and should remain on v5.0.

> "MQTT currently guarantees delivery — but it cannot guarantee state reconstruction. MQTT v6.0 adds the minimal metadata needed for deterministic telemetry recovery after disruption."

This proposal targets a specific problem: **industrial operators who already use MQTT at the edge but are forced to bolt on Kafka, AMQP, or Redis at the broker tier** to get durable queuing and ordered delivery. The edge devices cannot change — they run constrained firmware with MQTT baked in. The bridge architecture (MQTT → Kafka → Consumer) adds operational cost, a second failure domain, and a second protocol stack. v6.0 eliminates the bridge by extending the MQTT broker with the specific queuing primitives these operators need, without changing the edge protocol.

Every feature in v6.0 is already being implemented at the application layer by industrial MQTT users — sequence numbers in payloads, idempotency tables in databases, consumer group coordination in custom code. [Eclipse Sparkplug B](https://sparkplug.eclipse.org/specification/) is the most prominent example: it defines [application-layer sequencing on top of MQTT](https://sparkplug.eclipse.org/specification/version/2.2/documents/sparkplug-specification-2.2.pdf) precisely because MQTT v5.0 does not provide these primitives natively. v6.0 proposes to move these proven patterns from the payload into the protocol where brokers can optimize for them and client libraries can handle them automatically.

**Why not ship these as vendor extensions first?** Because the extension-first path leads to fragmentation, not standardization. If HiveMQ ships `$queue/` as a proprietary extension, EMQX, Mosquitto, and AWS IoT Core will build incompatible versions — just as every broker implemented `$SYS/` differently, creating a mess that remains unstandardized 15 years later. HiveMQ's own [Declared Shared Subscriptions](https://docs.hivemq.com/hivemq/latest/user-guide/declared-shared-subscriptions.html) — a proprietary workaround for the durable queue gap in `$share/` — is proof that extension-driven solutions do not converge on interoperability. Standardizing early, before fragmentation, is cheaper than standardizing late.

For a detailed response to specific criticisms (including "this is Kafka," "v5.0 already does shared subscriptions," and "this should be application-level"), see [Addressing Criticisms — Point-by-Point Rebuttals](rebuttals.md).

---

## 1. Who This Is For

MQTT v6.0 is targeted at a specific tier of industrial and enterprise IoT deployments that have **outgrown what MQTT v5.0 was designed to provide**. It is not a general-purpose upgrade for all MQTT users.

### Primary Use Cases

**Semiconductor Manufacturing ([SECS/GEM](https://en.wikipedia.org/wiki/SECS/GEM)):** Semiconductor fabs run the [SEMI E30 (GEM)](https://store-us.semi.org/products/e03000-semi-e30-specification-for-the-generic-model-for-communications-and-control-of-manufacturing-equipment-gem) protocol for equipment communication. A lost `S2F21` (Remote Process Start) command can ruin a wafer worth $10K–$50K. Today, fabs using MQTT must embed sequence numbers and idempotency keys in application payloads because MQTT v5.0 has no protocol-level mechanism to detect a gap caused by a broker restart. Every equipment vendor implements this differently.

**Energy and Grid SCADA ([IEC 61850](https://en.wikipedia.org/wiki/IEC_61850)):** Distributed energy providers operate millions of smart meters, PMUs, RTUs, and substation gateways. MQTT is increasingly used as the [edge transport for IEC 61850 telemetry](https://www.emqx.com/en/blog/iec-61850-protocol), but downstream data pipelines require ordered, durable queues with 90-day regulatory retention. Today this means an MQTT-to-Kafka bridge — a second system, a second failure domain, a second team.

### Primary Audience

| Audience | Why They Need v6.0 |
|----------|--------------------|
| **Large-scale industrial operators** — energy utilities, grid SCADA, semiconductor fabs, process manufacturing | Need ordered, durable message queues that survive broker restarts and client disconnections; need competing consumer patterns for high-availability pipelines |
| **IIoT platform engineers** | Building middleware that must guarantee message delivery ordering across distributed broker clusters without application-layer workarounds |
| **Data pipeline architects** | Connecting MQTT edge data to downstream analytics, historians, and SCADA systems; need pull-based flow control so consumers can dictate their own ingestion rate |
| **HiveMQ extension developers** | Implementing advanced queuing semantics today via custom extensions; v6.0 standardises and formalises these patterns |
| **MQTT broker implementers** | Seeking a standardised wire protocol for durable queuing so customers are not locked into proprietary extension APIs |

### Who Should Stay on MQTT v5.0

MQTT v6.0 is designed as a strict superset of MQTT v5.0: existing publish-subscribe use cases continue to work unchanged, while deployments that require durable queues and ordered replay can opt into the new capabilities. If your deployment matches any of the following profiles, v5.0 is the right choice and v6.0 adds complexity without benefit:

- Simple telemetry from sensors to a single backend consumer
- Devices with less than 256 KB available memory
- Short message lifetimes where loss is acceptable (dashboards, live monitoring)
- No requirement for competing consumers or consumer group semantics
- Broker infrastructure managed by a single operator with no cluster failover requirements

These deployments can connect to a v6.0 broker without modification — the broker serves v5.0 and v3.1.1 clients identically to a v5.0 broker. The v6.0 extensions are only activated when a client explicitly opts in via the v6.0 handshake.

---

## 2. The Problem Statement: What MQTT v5.0 Cannot Do

MQTT v5.0 is a well-designed protocol for lightweight publish-subscribe messaging. It was not designed to be a message queue. Five specific limitations emerge at scale in industrial deployments:

### 2.1 No Durable, Session-Independent Queues

MQTT v5.0 sessions are bound to a client identifier and a broker node. When a client disconnects:
- Clean session (`cleanStart=true`): all queued messages are discarded
- Persistent session (`cleanStart=false`): messages are held *for that specific client*, not for a named consumer group

**The result:** If a downstream analytics pipeline (one of ten competing consumers) disconnects for maintenance, its share of the message backlog is either lost or held indefinitely in a single-consumer session — neither behaviour is correct for an industrial pipeline.

**What operators do today:** They build application-layer queuing on top of MQTT using Redis, Kafka, or proprietary HiveMQ extensions. The MQTT broker becomes a thin transport layer and the real queuing logic lives outside the protocol. This defeats the purpose of using a standardised protocol.

### 2.2 No Message Ordering Guarantee Across Sessions

MQTT v5.0 includes a Packet Identifier, but it is not a message sequence number. It exists only for QoS delivery handshakes, is scoped to a single client session, is reused after acknowledgement, and resets when the session reconnects. It therefore cannot be used to determine message ordering or detect gaps across sessions.

MQTT v6.0 introduces a broker-assigned, monotonic sequence number (Property `0x30`) that identifies the message itself rather than the delivery attempt.

MQTT v5.0 uses a 16-bit Packet Identifier that resets per session. Messages across sessions cannot be ordered. If a consumer reconnects mid-stream, it cannot determine which messages it has already processed and which it has not — not without an application-layer sequence number that the publisher must attach manually.

**The result:** Exactly-once processing at the application layer requires every publisher and consumer pair to implement bespoke deduplication logic. In a system with 50 publishers and 20 consumers, this is 1,000 pairwise agreements — none of them standardised.

**What "1,000 pairwise agreements" means in practice:**

When sequence numbers live in the payload rather than the protocol, every publisher and every consumer must agree on the payload format — and that agreement must happen pair by pair. Consider a semiconductor fab with 50 tools (publishers) sending messages to 20 downstream systems (consumers) — historians, MES, FDC analyzers, dashboards:

- Tool A sends `{"seq": 123, "data": ...}` (JSON, field name `seq`)
- Tool B sends a [Sparkplug](https://sparkplug.eclipse.org/specification/) protobuf with a `sequence_number` field
- Tool C uses a custom binary header with bytes 0–3 as a big-endian sequence counter

Every consumer that wants to do deduplication or gap detection on messages from Tool A needs to know Tool A's format. And Tool B's format. And Tool C's format. Each publisher-consumer pair is a "pairwise agreement" about how to find the sequence number in the payload.

50 publishers × 20 consumers = 1,000 pairs that each need to agree on a schema. In practice, teams reduce this by picking a common format — but that common format is itself non-standard. It is a company-internal convention, not a protocol guarantee. Different companies, different vendors, and different integrations all pick different conventions. The result is that interoperability between organizations requires yet another translation layer.

**The v6.0 fix:** The broker assigns the sequence number as a protocol property (`0x30`). Every publisher's message gets a sequence number automatically — the publisher does not even need to be aware of it. Every consumer reads it from the same property, regardless of payload format. The 1,000 pairwise agreements collapse to zero. The protocol is the agreement.

Put simply: **when reliability metadata is in the payload, everyone has to agree on the payload format. When it is in the protocol, the protocol is the agreement.**

#### But Wait — Doesn't MQTT 5.0 Already Have a Sequence Number?

MQTT v5.0 does include a Packet Identifier, but it is not a message sequence number in the sense required for ordering or replay.

The Packet Identifier:
- Is 16-bit and wraps frequently
- Exists only for QoS handshake state, not for message identity
- Is scoped to a single client session
- Is reused once the QoS exchange completes
- Resets on reconnect

Because of these properties, the Packet Identifier cannot be used to determine message ordering across sessions or after reconnect. If a consumer disconnects and reconnects, the next message may reuse an earlier Packet Identifier, making it impossible to determine whether the message is new, duplicated, or missing.

In other words, **the Packet Identifier tracks delivery acknowledgement state, not message position in a stream.**

This is why industrial deployments that require ordering or deduplication add their own application-layer sequence numbers in the payload. [Sparkplug B](https://sparkplug.eclipse.org/specification/), for example, defines its own `seq` field precisely because MQTT provides no protocol-level sequence for messages.

MQTT v6.0 introduces a true message sequence number:
- **Broker-assigned** — publishers do not need to maintain counters
- **Cluster-wide** — valid across all nodes, not scoped to a single connection
- **Monotonic** — always increasing within a queue's lifetime
- **Immutable once assigned** — the sequence number is permanent
- **Stable across client sessions** — persists through disconnections and reconnections

This sequence number (Property `0x30`) identifies **the message itself**, not the delivery attempt.

The distinction is crucial:

| | MQTT v5.0 Packet Identifier | MQTT v6.0 Stream Sequence Number |
|--|--|--|
| **Purpose** | Tracks QoS handshake state | Tracks message position in the stream |
| **Scope** | Per-session | Cluster-wide |
| **Lifecycle** | Reused and reset | Monotonic and immutable |
| **Ordering** | Not usable for ordering | Basis for ordering, deduplication, and replay |

### 2.3 Push-Based Flow Control vs. Pull-Based Flow Control

MQTT v5.0 provides flow control via `Receive Maximum` — a mechanism that caps the number of QoS 1/2 messages the broker can have in-flight simultaneously. This is a valid and effective mechanism for bounding the push window. Combined with deliberate ack pacing, it allows consumers to influence the delivery rate.

However, `Receive Maximum` operates within a **push model**: the broker initiates delivery as soon as an acknowledgment frees a slot. The consumer controls the *rate* of delivery but not the *timing*. There is no mechanism for a consumer to say "hold all messages until I ask for them" without disconnecting (which discards session state if `cleanStart=true`) or withholding acknowledgments (which violates the spirit of QoS contracts).

FETCH introduces a **different semantic model** — pull-based consumption — where the consumer explicitly requests batches. This is not a replacement for `Receive Maximum`; both serve valid purposes. `Receive Maximum` is appropriate for live pub/sub where bounded push is correct. FETCH is for queue consumption where the consumer needs absolute control over *when* it receives messages, not just *how many*.

**The practical difference:** A slow consumer — one doing a database write per message — under the push model fills its in-flight window, processes it, and immediately receives another window. It can never pause, drain its backlog, or catch up without disconnecting. Under the pull model, it fetches when ready. No FETCH = no delivery. Messages remain safely in the durable queue.

### 2.4 No Cluster-Aware Sequence Numbers

MQTT v5.0 has no concept of cluster topology. If a client is connected to Node A and Node A fails, the client reconnects to Node B. From the protocol's perspective, this is a new session — there is no way to tell Node B "I had processed up to message X on Node A; please resume from X+1."

**The result:** After any broker failover, consumers must either:
- Re-process all messages from the beginning of the session (duplicate processing)
- Trust that the application layer tracked its own position (requires external state)
- Accept a gap (message loss)

None of these outcomes are acceptable for regulatory data, safety-critical commands, or financial telemetry.

### 2.5 Shared Subscriptions Have Loose Delivery Semantics

MQTT v5.0 introduced Shared Subscriptions (`$share/`) for competing consumers. However:
- There is no guaranteed round-robin; delivery order within a group is implementation-defined
- There is no concept of exclusive access (hot-standby primary/backup)
- If a consumer in the group disconnects mid-processing, the in-flight message may be re-delivered to any other consumer — but only if the broker's session timeout has not expired

**The result:** Building a reliable competing consumer pipeline on `$share/` requires extensive application-layer coordination that must be re-implemented for each new deployment.

### Why HiveMQ's Declared Shared Subscriptions Don't Solve This

HiveMQ [Declared Shared Subscriptions](https://docs.hivemq.com/hivemq/latest/user-guide/declared-shared-subscriptions.html) improve on standard `$share/` by buffering messages even when no subscriber is connected — a real and useful improvement over the base spec. But they leave four critical gaps open.

| Capability | `$share/` (MQTT v5.0 Spec) | HiveMQ Declared Shared Subscriptions | SQMC (`$queue/` + v6.0) |
|---|---|---|---|
| **Buffer messages when no subscriber connected** | Not guaranteed — spec is silent | Yes — HiveMQ's primary addition | Yes — `$queue/` persists independently |
| **Re-dispatch unacked message on consumer disconnect** | No — `[MQTT-4.8.2-5]` prohibits; message discarded if session terminates | No — `[MQTT-4.8.2-5]` still applies at spec level | Yes — lock released immediately; re-dispatched to next available consumer |
| **Exclusive consumer / hot-standby mode** | No | No | Yes — primary consumer + automatic standby promotion on disconnect |
| **Message ordering guarantee** | No — `[MQTT-4.6.0-6]` scopes ordering to non-shared subscriptions only | No | Yes — strict ascending Stream Sequence Number per queue |
| **Gap detection** | Impossible — no per-message identity | Impossible | Built-in — sequence gaps are detectable and auditable |
| **Survives broker restart (spec-mandated)** | No — persistence is implementation-defined | Yes (HiveMQ-specific behavior) | Yes — persistence to non-volatile storage required before PUBACK |
| **Interoperable across broker vendors** | Yes — standard | No — HiveMQ-proprietary | Yes — standardized wire format |
| **Named, inspectable entity** | No — subscription pattern only | No — broker config entry only | Yes — `$queue/` is a first-class entity with TTL, max-size, storage policy |

**The critical gap: `[MQTT-4.8.2-5]`.** [MQTT v5.0 Section 4.8.2, normative requirement `[MQTT-4.8.2-5]`](https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html#_Toc3901250) states: *"If the Client's Session terminates before the Client reconnects, the Server MUST NOT send the Application Message to any other subscribed Client."* This means: if a consumer in any `$share/` group — including a Declared Shared Subscription — receives a QoS 1 message, disconnects before sending PUBACK, and its session expires, the message is **discarded**. The spec explicitly prohibits the broker from re-delivering it to another consumer. In traditional competing-consumer queues (AMQP, JMS, Kafka consumer groups), an unacknowledged message is returned to the queue and re-dispatched. In MQTT v5.0 shared subscriptions — proprietary or otherwise — it is destroyed. SQMC breaks from this by treating `$queue/` topics as session-independent persistent stores: when a competing consumer disconnects, the message lock is released and the message is immediately re-dispatched regardless of session state.

**The exclusive consumer gap.** Declared Shared Subscriptions provide no equivalent to SQMC Exclusive Consumer mode. There is no mechanism in any `$share/` variant — declared or dynamic — to designate one consumer as primary and hold others as hot standbys that take over instantly on primary disconnect while preserving strict ordering. This pattern is non-negotiable for safety-critical command streams: SECS/GEM S2F21 (Remote Start), grid protection relay commands, and financial settlement messages where exactly one consumer must process each message in strict order with zero-delay failover.

**Why this is the argument, not the counterargument.** The existence of Declared Shared Subscriptions as a HiveMQ-proprietary feature is itself evidence that the MQTT standard has a gap — HiveMQ built it because `$share/` alone did not satisfy customer requirements. And yet those same customers are asking for re-dispatch-on-failure and exclusive consumer semantics that Declared Shared Subscriptions still cannot provide. The extension-first path is also how `$SYS/` became permanently fragmented: EMQX, Mosquitto, and HiveMQ each implemented it differently, and 15 years later there is still no standard. Standardizing SQMC semantics now — before EMQX, AWS IoT Core, and others build incompatible variants — avoids repeating that outcome.

*For a full side-by-side treatment of this comparison, including the normative `[MQTT-4.8.2-5]` analysis, see the standalone reference document [`sqmc-vs-declared-shared-subscriptions.md`](sqmc-vs-declared-shared-subscriptions.md).*

---

## 3. Why Not Use Kafka or AMQP?

This is the most frequently raised objection. The answer depends on **where in the architecture** the problem exists.

### At the Edge (Sensors, RTUs, PLCs, Smart Meters)

Kafka and AMQP are not viable at the edge:
- Kafka's minimum client footprint requires a [full JVM stack with multi-GB RAM](https://docs.confluent.io/platform/current/installation/system-requirements.html) — not compatible with microcontrollers or constrained devices
- [AMQP 1.0 is a complex framing protocol](https://www.hivemq.com/blog/mqtt-vs-amqp-for-iot/) — correct implementation requires significant expertise and is poorly suited to constrained devices
- Kafka requires TCP connections with persistent state; many OT networks have unreliable connectivity and require disconnect-tolerant protocols
- MQTT v5.0 is already deployed on [hundreds of millions of devices](https://www.hivemq.com/blog/building-industrial-iot-data-streaming-architecture-mqtt/) with battle-tested client libraries for C, MicroPython, Java, and Go

**Conclusion:** At the edge, MQTT remains the right protocol. The question is what happens to messages *after* they reach the broker cluster.

### At the Broker Tier (The Gap MQTT v6.0 Fills)

Today, industrial deployments solve the queuing problem with a pattern like this:

```
[Edge device MQTT v5.0] → [MQTT Broker] → [Bridge to Kafka/AMQP] → [Consumer]
```

This architecture requires:
- A bridge component that must be deployed, scaled, and maintained
- Two separate protocol stacks, two separate failure domains
- Message translation overhead at the bridge
- Kafka or AMQP client libraries in every downstream consumer

MQTT v6.0 eliminates the bridge by extending the MQTT broker to natively support the queuing semantics that consumers need. The edge devices continue to speak MQTT v5.0 unchanged. The downstream consumers get ordered, pull-based, durable message queues — without a separate message queue system.

```
[Edge device MQTT v5.0] → [HiveMQ v6.0 Broker — native queuing] → [Consumer via FETCH]
```

This is not "MQTT trying to become Kafka." It is MQTT extending its native durability semantics to the broker tier where the queuing problem actually lives.

---

## 4. Design Principles

MQTT v6.0 is built on six explicit principles, each derived from a lesson learned in large-scale industrial deployments:

### Principle 1: The Protocol Must Survive Broker Restarts

A `$queue/` message that has been published MUST be retained by the broker cluster regardless of individual node failures. The protocol defines what "retained" means (quorum write), when sequence continuity can be guaranteed (same Epoch), and when it cannot (Epoch increment on counter quorum loss).

This is a departure from v5.0's "retained message" feature, which is per-topic and not queue-semantics aware.

### Principle 2: Consumers Control Their Own Rate

Pull-based FETCH (not push) is the default for `$queue/` consumption. A consumer that is slow, restarting, or catching up a backlog is never flooded. It fetches when it is ready. This is an intentional departure from v5.0's push-all model — but it applies **only to `$queue/` topics**, not to standard pub/sub.

Push subscriptions remain available for all non-queue topics and for use cases where push semantics are correct (live telemetry monitoring, real-time dashboards). A v6.0 broker serving standard pub/sub traffic behaves identically to a v5.0 broker.

### Principle 3: Sequence Numbers Are a First-Class Protocol Citizen

Every `$queue/` message has a broker-assigned, cluster-wide monotonic sequence number (Property `0x30`). Publishers do not assign sequence numbers — the broker does, atomically, with no routing constraints. Sequence numbers are:
- Immutable once assigned
- Cluster-wide (not per-session or per-node)
- The basis for exactly-once deduplication at the consumer
- The basis for gap detection and recovery

### Principle 4: Cluster Failover Must Be Transparent to Well-Behaved Clients

A client that stores its `last-seq` and `epoch` values can reconnect to *any* node in the cluster after any failure and resume processing from exactly where it left off — provided the cluster maintained quorum. If quorum was lost (an Epoch increment event), the protocol signals this explicitly so the client can decide how to recover.

No application-layer failover logic is required. No broker-specific reconnect APIs. The protocol carries all the state the client needs.

### Principle 5: Backward Compatibility Is a Non-Negotiable Constraint

MQTT v6.0 is backward-compatible with MQTT v5.0 **for all unchanged v5.0 use cases**: existing packet types, properties, topics, and semantics continue to work as before. Specifically:

- A v6.0 broker can serve v5.0 and v3.1.1 clients without modification — these clients see no difference in behavior
- The migration from v5.0 to v6.0 does not require a flag-day cutover

**Honest about the limits:** Compatibility is not wire-transparent for v6.0-only features. The proposal defines two tracks:

- **Track A (Native v6.0, Protocol Level 6):** Uses FETCH (Type 16) and new property IDs. This is a **breaking change** — a v5.0 broker will reject Protocol Level 6 connections, and a v5.0 client receiving a Type 16 packet will close the connection. Track A requires updated brokers and client libraries.
- **Track B (Compatibility Mode, Protocol Level 5):** Uses User Properties and Virtual FETCH via `$SYS/` control topics. This works on any v5.0 broker with a v6.0-aware extension plugin. It is functionally complete but carries string-encoding overhead and is not a formal standard — it is an extension convention.

Track B is not a transparent bridge — it requires a v6.0-aware extension on the broker and v6.0-aware client code. It is a migration path, not invisible compatibility. See [§7 Compatibility Boundaries](#compatibility-boundaries) for exact details.

### Principle 6: Layered Standardization

The proposal is structured so that it can be submitted to OASIS incrementally:

1. **Core layer** (submit first): Stream Sequence Number (`0x30`), Stream Epoch (`0x35`), `$queue/` namespace and persistence semantics. These are the minimum viable primitives.
2. **Consumption layer** (follow-on): FETCH packet (Type 16), Virtual FETCH, batch semantics. Depends on the core layer.
3. **Consumer group layer** (follow-on): SQMC competing/exclusive modes, consumer group management. Depends on the core layer.

This layering allows the standards committee to evaluate and accept the core primitives independently, without requiring approval of the full feature set in a single submission.

---

## 5. Expected Benefits

### For Industrial Operators

| Benefit | Mechanism |
|---------|-----------|
| Message loss eliminated for `$queue/` topics | Quorum write + HWM-based exactly-once |
| Consumer restart is safe — no re-processing required | `last-seq` + `epoch` in CONNECT; broker resumes from N+1 |
| Slow consumers cannot be flooded | Pull-based FETCH; consumer controls batch size and timing |
| Competing consumers with correct failover | SQMC competing mode: in-flight locks re-dispatched on consumer crash |
| Hot-standby consumer for safety-critical commands | SQMC exclusive mode: single active consumer with automatic promotion |
| Broker failover transparent to clients | Epoch-based resync protocol |

### For Platform Engineers

| Benefit | Mechanism |
|---------|-----------|
| Eliminates MQTT-to-Kafka bridge for queue use cases | Native `$queue/` semantics in the broker |
| Standardised competing consumer semantics | SQMC spec replaces bespoke `$share/` orchestration |
| Sequence numbers enable cross-system correlation | `Seq` + `Epoch` = immutable event identifier for audit, replay, join |
| No external state required for exactly-once | HWM tracked by broker + client; no Redis or database required |

### For the MQTT Ecosystem

| Benefit | Mechanism |
|---------|-----------|
| Clear upgrade path from v5.0 | Compatibility layer; no flag-day migration |
| Standardised semantics reduce broker lock-in | Wire protocol defines queue behaviour, not just transport |
| Opens MQTT to new use cases | Financial telemetry, ERP integration, command-and-control audit trails |

---

## 5.5 MQTT v6.0 as Telemetry Integrity Infrastructure

The proposal's features map to a specific layer in the emerging industrial AI stack. Modern industrial systems are converging on a four-layer architecture:

```
┌─────────────────────────────────────┐
│ Layer 4 – Industrial AI Agents      │
│ autonomous decision systems         │
└─────────────────────────────────────┘
                ▲
┌─────────────────────────────────────┐
│ Layer 3 – Deterministic State       │
│ digital twin + event sourcing       │
└─────────────────────────────────────┘
                ▲
┌─────────────────────────────────────┐
│ Layer 2 – Telemetry Integrity       │
│ sequence numbers + epochs           │
│ ← MQTT v6.0 fills this layer        │
└─────────────────────────────────────┘
                ▲
┌─────────────────────────────────────┐
│ Layer 1 – Device Messaging          │
│ MQTT pub/sub (unchanged)            │
└─────────────────────────────────────┘
```

MQTT v5.0 provides Layer 1. Layers 3 and 4 are well-served by existing platforms (digital twin engines, AI inference frameworks). **Layer 2 does not exist as a standard today.** Every industrial MQTT deployment that needs telemetry continuity — gap detection, restart detection, state reconstruction after disruption — builds Layer 2 from scratch, incompatibly.

MQTT v6.0 fills Layer 2. The features are precisely scoped to this layer:

| Feature | Layer 2 Function |
|---|---|
| Stream Sequence Numbers | Detect missing telemetry events |
| Stream Epoch | Detect publisher/broker restart boundaries |
| `$queue/` Namespace | Provide the durable stream that Layer 2 operates on |
| FETCH / Pull Control | Protect Layer 3 consumers from being overwhelmed during state reconstruction |
| SQMC | Ensure Layer 3 state machines receive each event exactly once, in order |

Once Layer 2 exists, Layer 3 and Layer 4 can be built reliably. Without it, digital twins drift, AI agents receive incomplete event histories, and industrial systems require manual reconciliation after every disruption.

---

## 6. Explicit Non-Goals

MQTT v6.0 explicitly does not aim to:

- Replace Kafka or RabbitMQ for server-to-server batch processing at data centre scale
- Provide full AMQP 1.0 semantics (routing topologies, exchanges, dead-letter queues)
- Support messages larger than the current MQTT maximum (256 MB per PUBLISH)
- Implement stream processing or CEP (complex event processing)
- Define a management API or REST interface for broker administration
- Mandate a specific cluster topology or replication protocol (the spec defines *what* must be guaranteed, not *how*)

---

## 7. Relationship to the MQTT v5.0 Specification

MQTT v6.0 is a **strict superset of MQTT v5.0**: existing publish-subscribe use cases continue to work unchanged, while deployments that require durable queues and ordered replay can opt into the new capabilities. Every feature defined in the OASIS MQTT v5.0 specification remains valid and unchanged. The additions in v6.0 are:

1. **New packet type**: FETCH (Control Packet Type 16) — absent from v5.0
2. **New property identifiers**: `0x30` through `0x35`, `0x41` through `0x42` — reserved ranges not used by v5.0
3. **New topic namespace**: `$queue/` — conventionally reserved (similar to `$SYS/`) but now formally specified
4. **New connection negotiation**: Protocol Level `6` in CONNECT; `mqtt-ext: v6.0` User Property for compat mode
5. **New CONNECT fields**: `last-seq` and `epoch` for stateful reconnection

No existing v5.0 packet types, property identifiers, or semantics are modified or removed.

### Compatibility Boundaries

MQTT v6.0 is backward-compatible with MQTT v5.0 for all unchanged v5.0 use cases. The following table defines exactly when compatibility is guaranteed and when compatibility mode is required:

| Scenario | Compatible? | Notes |
|----------|:-:|-------|
| v5.0 client → v6.0 broker, standard pub/sub | **Yes — fully transparent** | Client sees no difference. No v6.0 features activated. |
| v3.1.1 client → v6.0 broker, standard pub/sub | **Yes — fully transparent** | Same as above. |
| v6.0 client → v6.0 broker, `$queue/` + FETCH | **Yes — native mode** | Protocol Level 6. Full binary efficiency. |
| v6.0 client → v5.0 broker, compatibility mode | **Yes — via compat layer** | Client uses Protocol Level 5 + `mqtt-ext: v6.0` User Property. FETCH tunneled via `$SYS/queues/*/fetch`. Seq/Epoch carried as User Properties. Requires v6.0-aware extension on the v5.0 broker. |
| v6.0 client → v5.0 broker, native FETCH packet | **No — connection rejected** | v5.0 broker rejects Protocol Level 6 with Reason Code `0x84`. Client MUST fall back to compatibility mode. |
| v5.0 client → v6.0 broker, `$queue/` topics | **No — rejected by ACL** | v6.0 broker MUST reject `$queue/` access from clients that have not completed the v6.0 handshake. |
| v6.0 properties on non-queue topics | **Ignored** | v5.0 clients and brokers MUST ignore unknown property IDs per the v5.0 spec. No harm, no benefit. |

**The key guarantee:** If you do not use `$queue/`, FETCH, Stream Sequence, or `last-seq`/`epoch`, your deployment is fully compatible with v5.0 — no behavioral changes, no additional overhead, no migration required. The v6.0 extensions activate only when explicitly opted into.
