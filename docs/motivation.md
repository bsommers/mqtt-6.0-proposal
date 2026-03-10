# Why MQTT v6.0? Motivation, Rationale, and Intended Audience

> **Status:** Part of the MQTT v6.0 Draft Proposal — March 2026

---

## 0. Important Context: What This Proposal Is Not

**This is not "MQTT trying to become Kafka."** This is not a general-purpose upgrade. Most MQTT deployments do not need v6.0 and should remain on v5.0.

This proposal targets a specific problem: **industrial operators who already use MQTT at the edge but are forced to bolt on Kafka, AMQP, or Redis at the broker tier** to get durable queuing and ordered delivery. The edge devices cannot change — they run constrained firmware with MQTT baked in. The bridge architecture (MQTT → Kafka → Consumer) adds operational cost, a second failure domain, and a second protocol stack. v6.0 eliminates the bridge by extending the MQTT broker with the specific queuing primitives these operators need, without changing the edge protocol.

Every feature in v6.0 is already being implemented at the application layer by industrial MQTT users — sequence numbers in payloads, idempotency tables in databases, consumer group coordination in custom code. [Eclipse Sparkplug B](https://sparkplug.eclipse.org/specification/) is the most prominent example: it defines [application-layer sequencing on top of MQTT](https://sparkplug.eclipse.org/specification/version/2.2/documents/sparkplug-specification-2.2.pdf) precisely because MQTT v5.0 does not provide these primitives natively. v6.0 proposes to move these proven patterns from the payload into the protocol where brokers can optimize for them and client libraries can handle them automatically.

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

If your deployment matches any of the following profiles, v5.0 is the right choice and v6.0 adds complexity without benefit:

- Simple telemetry from sensors to a single backend consumer
- Devices with less than 256 KB available memory
- Short message lifetimes where loss is acceptable (dashboards, live monitoring)
- No requirement for competing consumers or consumer group semantics
- Broker infrastructure managed by a single operator with no cluster failover requirements

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

MQTT v5.0 uses a 16-bit Packet Identifier that resets per session. Messages across sessions cannot be ordered. If a consumer reconnects mid-stream, it cannot determine which messages it has already processed and which it has not — not without an application-layer sequence number that the publisher must attach manually.

**The result:** Exactly-once processing at the application layer requires every publisher and consumer pair to implement bespoke deduplication logic. In a system with 50 publishers and 20 consumers, this is 1,000 pairwise agreements — none of them standardised.

### 2.3 No Pull-Based Flow Control

MQTT v5.0 is push-only. The broker delivers messages to subscribers as fast as they arrive. Consumer-side flow control is limited to:
- `Receive Maximum` — caps the in-flight window but does not let the consumer control *when* it receives the next batch
- Disconnecting and reconnecting — a destructive and operationally expensive throttle

**The result:** A slow consumer — one doing a database write per message — is flooded. The broker's delivery queue fills the consumer's memory until it crashes. Consumer crashes trigger reconnects, which trigger session resumption, which floods the consumer again. This cycle is well-known in industrial MQTT deployments and is solved today by external rate limiters, message buffers, or complete replacement of the push model with polling.

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

MQTT v6.0 is built on five explicit principles, each derived from a lesson learned in large-scale industrial deployments:

### Principle 1: The Protocol Must Survive Broker Restarts

A `$queue/` message that has been published MUST be retained by the broker cluster regardless of individual node failures. The protocol defines what "retained" means (quorum write), when sequence continuity can be guaranteed (same Epoch), and when it cannot (Epoch increment on counter quorum loss).

This is a departure from v5.0's "retained message" feature, which is per-topic and not queue-semantics aware.

### Principle 2: Consumers Control Their Own Rate

Pull-based FETCH (not push) is the default for `$queue/` consumption. A consumer that is slow, restarting, or catching up a backlog is never flooded. It fetches when it is ready.

Push subscriptions remain available for compatibility and for use cases where push semantics are correct (live telemetry monitoring, real-time dashboards).

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

MQTT v6.0 is designed so that:
- A v6.0 broker can serve v5.0 and v3.1.1 clients without modification
- A v5.0 broker can serve v6.0 clients in compatibility mode (via User Properties and Virtual FETCH)
- The migration from v5.0 to v6.0 does not require a flag-day cutover

The compatibility layer is specified precisely enough that it can be implemented as a HiveMQ Extension Plugin without modifying the core broker.

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

MQTT v6.0 is a **strict superset of MQTT v5.0**. Every feature defined in the OASIS MQTT v5.0 specification remains valid and unchanged. The additions in v6.0 are:

1. **New packet type**: FETCH (Control Packet Type 16) — absent from v5.0
2. **New property identifiers**: `0x30` through `0x35`, `0x41` through `0x42` — reserved ranges not used by v5.0
3. **New topic namespace**: `$queue/` — conventionally reserved (similar to `$SYS/`) but now formally specified
4. **New connection negotiation**: Protocol Level `6` in CONNECT; `mqtt-ext: v6.0` User Property for compat mode
5. **New CONNECT fields**: `last-seq` and `epoch` for stateful reconnection

No existing v5.0 packet types, property identifiers, or semantics are modified or removed.
