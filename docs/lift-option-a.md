# Option A: MQTT 6.0 Protocol Primitives + MQTT Stream Application Profile

> **Author:** Bill Sommers, AI Solutions Lead, HiveMQ, Inc.
> **Status:** Discussion draft for standards committee review — March 2026
> **Addresses:** Simon's "mux'ing of application and protocol expectations" criticism

---

## 1. Overview

The central concern raised by Simon in the committee review is that the current MQTT 6.0 specification conflates two distinct layers of obligation: what the **broker must do** and what the **client library must do**. His exact phrasing — *"there appears to be a mux'ing of what is expected of the application and what is expected of the protocol"* — identifies a real structural problem in the draft, and this document addresses it directly.

Option A resolves the mux'ing by splitting the proposal into two independent documents with a clean interface between them:

1. **MQTT 6.0 Protocol Specification** — defines six broker-level primitives. Normative obligations using MUST/MUST NOT. Submitted to OASIS. Protocol parsers, broker implementers, and wire-format tooling implement this layer.

2. **MQTT Stream Application Profile** — defines client library behavior built on top of those primitives. Normative obligations using REQUIRES/RECOMMENDS. Submitted to Eclipse Foundation (alongside Sparkplug B). Client library authors and application framework developers implement this layer.

The architectural relationship is identical to MQTT itself versus Eclipse Sparkplug B. MQTT defines the transport primitives (PUBLISH, SUBSCRIBE, QoS levels). Sparkplug B defines application behavior on top of those primitives (64-bit sequence fields in protobuf payloads, birth/death certificate state management, group IDs). Two governing bodies, two documents, one coherent system.

This document does not propose removing any feature from the v6.0 ecosystem. It proposes assigning each feature to the layer where it belongs.

---

## 2. The Protocol Layer: What Stays in the MQTT 6.0 Specification

The MQTT 6.0 Protocol Specification defines the obligations of the **broker** — specifically, what the broker MUST do when it encounters v6.0 protocol elements. Client behavior noted below is the minimum required to invoke these broker obligations; everything else is the Application Profile's domain.

| Feature | Protocol Specification Obligation | Normative Level |
|---|---|---|
| **`$queue/` durable persistence** | The broker MUST persist a message published to a `$queue/` topic to non-volatile storage before sending PUBACK. The queue MUST continue to exist and retain messages independently of any client session. | MUST |
| **Stream Sequence Number (`0x30`)** | The broker MUST assign a monotonically increasing 32-bit Sequence Number to each message accepted into a `$queue/`. Sequence Numbers MUST be cluster-wide and MUST NOT be reused within an Epoch. | MUST |
| **Stream Epoch (`0x35`)** | The broker MUST include the current Epoch value in CONNACK. The broker MUST increment the Epoch when it cannot guarantee sequence continuity for one or more queues (e.g., after a partition event or unrecoverable state loss). The broker MUST NOT increment the Epoch for routine operations that preserve continuity. | MUST |
| **FETCH / Virtual FETCH** | The broker MUST NOT push `$queue/` messages to a subscriber unless a FETCH request is pending or in force. On receiving a FETCH request, the broker MUST deliver up to the requested `batch-size` messages in ascending Sequence Number order. | MUST |
| **SQMC subscription semantics** | When a subscriber includes `v6-semantics: competing` in SUBSCRIBE User Properties, the broker MUST deliver each `$queue/` message to exactly one subscriber in the group. When `v6-semantics: exclusive` is specified, the broker MUST deliver to the primary subscriber only and MUST redirect to the standby subscriber if the primary disconnects. | MUST |
| **Throughput Limit (`0x41`)** | The broker MAY include a Throughput Limit property in CONNACK specifying the maximum KB/s the client is permitted to publish. If included, the broker MUST enforce this limit by refusing or delaying publishes that exceed it. | MAY / MUST |

These six obligations define the complete broker contract. The MQTT 6.0 Protocol Specification is thinner than the current draft precisely because everything below this line belongs in the Application Profile.

---

## 3. The Application Profile Layer: The Lift

The **MQTT Stream Application Profile** defines client library behavior using the six protocol primitives above as building blocks. This is the layer that implements the reliability guarantees that industrial users actually need. The profile does not introduce new wire format; it specifies how client libraries MUST behave when processing protocol-layer signals.

This is Simon's "mux'ing" resolved: these behaviors are explicitly and formally designated as client library obligations, not protocol obligations.

| Behavior | Application Profile Specification | Normative Level |
|---|---|---|
| **Gap detection algorithm** | The client library REQUIRES a check `received_seq == expected_seq` for each message delivered from a `$queue/`. On gap detection (received > expected + 1), the library MUST invoke the registered gap handler before delivering the out-of-sequence message to the application. | REQUIRES |
| **High-watermark tracking** | The client library REQUIRES storing the last successfully processed Sequence Number per queue (O(1) state). The high-watermark is the reference point for gap detection, resume-from-position, and exactly-once deduplication for in-order delivery. | REQUIRES |
| **Epoch change handler** | On CONNACK where the broker-supplied Epoch differs from the client's stored Epoch for any queue, the client library MUST discard all stored idempotency state for that queue, update the stored Epoch, and trigger a resync before resuming consumption. | MUST |
| **Consumer state machine** | The client library REQUIRES implementing a state machine with the following states: `CONNECTING`, `HANDSHAKING` (v6.0 capability exchange), `FETCHING`, `PROCESSING`, `ACKNOWLEDGING`, `RESYNCING`. The profile defines valid transitions and the conditions that trigger each. | REQUIRES |
| **Exactly-once processing workflow** | The profile defines the sequence: (1) receive message, (2) check Seq against high-watermark, (3) if duplicate, send PUBACK and skip application delivery, (4) if new, deliver to application, (5) on application success, advance high-watermark, (6) send PUBACK. Step 5 MUST occur before Step 6. | REQUIRES |
| **Reconnect and resume** | On reconnect to a v6.0 broker, the client library REQUIRES including `last-seq` and `current-epoch` as CONNECT User Properties for each queue the client was consuming. The broker uses these values to resume delivery from the correct position. | REQUIRES |
| **Sequence wraparound** | The client library MUST treat `Seq 0` following `Seq 0xFFFFFFFF` as a continuation, not a gap. If the broker increments the Epoch at wraparound, the library MUST handle this as an Epoch change event (see Epoch change handler above). | MUST |
| **FETCH batch sizing strategy** | The profile RECOMMENDS an adaptive batch sizing strategy: start with `batch-size = 1`, double on successful processing, halve on slow processing (processing time exceeds a configurable threshold). This prevents the reconnect flood while allowing throughput to scale under stable conditions. | RECOMMENDS |
| **Idempotency table management** | For in-order delivery (standard `$queue/` topics), the profile REQUIRES the high-watermark model (O(1) state). Set-based idempotency tables are RECOMMENDED only when the application requires out-of-order delivery guarantees. On Epoch reset, the profile REQUIRES discarding the entire idempotency table as a garbage-collection boundary. | REQUIRES / RECOMMENDS |
| **Consumer group coordination** | The profile defines how to use SQMC `competing` mode for work-queue fan-out and `exclusive` mode for primary/standby failover. The profile also defines when application-level coordination is needed instead (e.g., cross-broker consumer groups spanning multiple `$queue/` instances require application-level partition assignment beyond what the protocol provides). | REQUIRES / defers |

---

## 4. How This Addresses Committee Criticisms

### Simon's "mux'ing" criticism

*"There appears to be a mux'ing of what is expected of the application and what is expected of the protocol."*

Option A resolves this directly. Section 2 of this document is a complete enumeration of broker obligations — the MQTT 6.0 Protocol Specification contains exactly and only those six items. Section 3 is a complete enumeration of client library obligations — every item that belongs at the application layer is explicitly placed in the Application Profile. The line is drawn and labeled. Simon is right that the current draft mixes these layers; Option A unmixes them.

### The "this should be application-level" argument

Simon's implicit position — that gap detection, idempotency management, and consumer state machines belong in the application rather than the protocol — is **correct**, and Option A agrees with him. The Application Profile is precisely the document that specifies what IS at the application level. We are not pushing these behaviors into the protocol; we are standardizing them in their appropriate layer, using the Eclipse Foundation as the governing body (the same body that governs Sparkplug B, which already standardizes application-level sequencing on MQTT). The protocol spec stays narrow. The application behavior gets standardized where it belongs.

### The "bloat" and Kafka-clone criticism

The MQTT 6.0 Protocol Specification under Option A contains six broker primitives. The protocol document is noticeably thinner than the current combined draft. Implementers building a compliant v6.0 broker need only implement Section 2 of this document. They do not need to implement gap detection algorithms, consumer state machines, or idempotency table strategies — those are client library concerns that live in the Application Profile. A minimal v6.0 broker footprint is achievable; the protocol is not attempting to replicate Kafka's consumer group coordinator.

### The "standardize now vs. extension first" tension

Option A enables parallel standardization tracks that match the institutional capabilities of the appropriate governing bodies:

- **MQTT 6.0 Protocol Specification** — OASIS. Six broker primitives, wire format, property IDs `0x30`, `0x35`, `0x41`. This is protocol engineering; OASIS is the right home.
- **MQTT Stream Application Profile** — Eclipse Foundation, alongside Sparkplug B. Client library behavior, reference implementations, conformance test suites. This is application engineering; Eclipse Foundation already governs Sparkplug B and has the processes for this kind of document.
- **Reference implementation** — HiveMQ Extension SDK for the broker side; an open-source client library (Python/Java/Go) implementing the Application Profile for the client side.

Two tracks can advance simultaneously. If the OASIS process moves slowly, the Application Profile can be published and adopted while the protocol primitives are in draft. If the Application Profile needs revision (e.g., new batch sizing strategies emerge from production experience), it can be updated without reopening the OASIS protocol spec.

---

## 5. Feature Split: Comprehensive Reference Table

| Feature | In MQTT 6.0 Protocol Spec? | In MQTT Stream Application Profile? | Who Implements |
|---|:---:|:---:|---|
| `$queue/` durable persistence before PUBACK | Yes | No | Broker |
| Queue TTL and max-size enforcement | Yes | No | Broker |
| Stream Sequence Number assignment (`0x30`) | Yes | No | Broker |
| Stream Epoch signaling (`0x35`) in CONNACK | Yes | No | Broker |
| FETCH request handling / Virtual FETCH dispatch | Yes | No | Broker |
| SQMC competing-consumer dispatch (round-robin) | Yes | No | Broker |
| SQMC exclusive-consumer primary/standby failover | Yes | No | Broker |
| Throughput Limit enforcement (`0x41`) | Yes | No | Broker |
| v6.0 handshake (`mqtt-ext: v6.0` in CONNECT/CONNACK) | Yes (detection only) | Yes (fallback logic) | Broker detects; client library handles fallback |
| Gap detection algorithm | No | Yes | Client library |
| High-watermark state tracking | No | Yes | Client library |
| Epoch change handler (discard idempotency state) | No | Yes | Client library |
| Consumer state machine | No | Yes | Client library |
| Exactly-once processing workflow | No | Yes | Client library |
| Reconnect/resume with `last-seq` + `current-epoch` | No (wire format only) | Yes (behavior) | Client library |
| Sequence wraparound handling | No | Yes | Client library |
| Adaptive FETCH batch sizing | No | Yes | Client library |
| Idempotency table strategy selection | No | Yes | Client library |
| Consumer group application-level coordination | No | Yes (scope limits defined) | Application / client library |

---

## 6. Standardization Path

```
OASIS MQTT Technical Committee
  └── MQTT 6.0 Protocol Specification (broker primitives)
        Property 0x30 (Stream Sequence Number)
        Property 0x35 (Stream Epoch)
        Property 0x41 (Throughput Limit)
        $queue/ persistence semantics
        FETCH / Virtual FETCH broker behavior
        SQMC broker dispatch semantics

Eclipse Foundation (IoT Working Group)
  └── MQTT Stream Application Profile v1.0
        Gap detection algorithm
        Consumer state machine
        Epoch change handler
        Exactly-once processing workflow
        FETCH batch sizing strategy
        Reconnect/resume behavior
        Idempotency table management
  └── Sparkplug B (existing — application-layer sequencing on MQTT v5.0)

HiveMQ
  └── Reference implementation — broker (HiveMQ Extension SDK)
  └── Reference implementation — client (open-source, multi-language)
  └── Conformance test suite (donated to Eclipse Foundation)
```

The OASIS submission can proceed with only the six protocol primitives, making the committee's evaluation scope manageable. The Eclipse Foundation Application Profile can begin community review immediately, given the Eclipse Foundation's lighter governance process relative to OASIS. The two documents reference each other normatively but are independently versioned.

---

## 7. Trade-offs

### Advantages

- **Protocol spec is genuinely slimmer.** The MQTT 6.0 OASIS submission covers six broker primitives, not a full consumer lifecycle specification. Committee members evaluating "is this appropriate for a protocol spec?" are evaluating a narrower document with a cleaner answer.
- **Simon's criticism is directly and structurally resolved.** The mux'ing is eliminated by design. Every feature has a designated layer and a designated governing body.
- **Application Profile can evolve faster.** If production experience reveals that the adaptive FETCH batch sizing strategy needs revision, the Eclipse Foundation can publish Application Profile v1.1 without reopening the OASIS protocol spec. Protocol stability and application-layer agility are decoupled.
- **Aligns with established precedent.** Sparkplug B proves that the MQTT ecosystem already accepts this two-layer model. The Application Profile is not a novel concept; it is an explicit formalization of what Sparkplug B does informally.
- **Appropriate governing bodies.** OASIS for wire format and broker obligations. Eclipse Foundation for client library behavior and reference implementations. Each body handles what it handles well.

### Disadvantages

- **Two documents to maintain.** An implementer building a complete v6.0 consumer must read and conform to both the protocol spec and the Application Profile. Cross-document consistency must be actively managed.
- **Risk of Application Profile fragmentation.** If the Application Profile is not adopted widely, client libraries may implement the protocol primitives but diverge on the consumer state machine, gap detection, and idempotency strategies. This is the same fragmentation risk that motivated the proposal in the first place, now shifted one layer up. Mitigation: the reference implementation and conformance test suite must be published simultaneously with the Application Profile.
- **Compliance testing is split.** A "fully compliant v6.0 system" requires broker conformance to the protocol spec AND client library conformance to the Application Profile. Test harnesses must cover both layers. This is more complex than a single combined conformance suite.

---

## References

- Simon's committee review feedback — quoted directly in `docs/rebuttals.md`, Section: "This Should Be Handled at the Application Level"
- `docs/rebuttals.md` — full point-by-point responses to Georg and Simon
- `docs/critiques-and-rebuttals.md` — technical pitfalls and mitigations (idempotency table growth, sequence wraparound, Epoch DoS)
- `docs/spec/mqtt-v6.0-spec.md` — current combined specification (the document that Option A proposes splitting)
- [Eclipse Sparkplug B Specification](https://sparkplug.eclipse.org/specification/) — the governing precedent for this two-layer model
- [MQTT v5.0 OASIS Standard](https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html) — protocol layer reference
