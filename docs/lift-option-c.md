# Option C: Two Independent Specifications — MQTT 6.0 Transport Extension + MQTT Stream 1.0 Application Protocol

> **Author:** Bill Sommers, AI Solutions Lead, HiveMQ, Inc.
> **Date:** March 2026
> **Status:** Proposal — for standards committee review

---

## 1. Overview

Option C is the maximum-separation answer to the committee's structural criticisms. It dissolves the layering ambiguity by making the boundary absolute and architectural: two distinct specifications, governed independently, versioned independently, with a clean contractual interface between them.

**MQTT 6.0** becomes a minimal wire-format extension specification. It defines new property IDs, the `$queue/` namespace semantics, and broker-side behavioral requirements. It contains no client behavioral requirements beyond what is necessary to negotiate the extension. It does not define state machines, gap-detection algorithms, epoch-handling procedures, or application patterns. It is a transport extension, not an application protocol.

**MQTT Stream 1.0** is a separate specification that defines the industrial reliability application protocol built on top of MQTT 6.0. It defines the consumer state machine, the gap-detection algorithm, the epoch-resync procedure, the exactly-once delivery contract, and FETCH pacing strategies. It references MQTT 6.0 as its required transport layer. It is to MQTT 6.0 what Sparkplug B is to MQTT 3.1.1 — an application-layer profile that leverages the transport primitives without being conflated with them.

This is not a novel pattern. The protocol ecosystem has used it for decades:

- TCP/IP defines reliable byte-stream delivery. HTTP defines an application protocol for document transfer over TCP.
- MQTT 3.1.1 defines a lightweight pub/sub transport. Sparkplug B defines an application protocol for industrial telemetry over MQTT.
- CoAP defines a constrained application protocol over UDP. LwM2M defines a device management application protocol over CoAP.

Option C places MQTT 6.0 and MQTT Stream 1.0 in that same well-understood relationship. The transport layer provides primitives. The application layer defines what to do with them.

---

## 2. MQTT 6.0 Transport Extension Specification

The MQTT 6.0 spec is a **broker-only behavioral specification**. It defines what a conformant broker MUST do. It imposes no normative requirements on client application logic.

### 2.1 What MQTT 6.0 Defines

| Feature | Specification Content |
|---|---|
| **Property 0x30: Stream Sequence Number** | Four Byte Integer. A conformant broker MUST assign a monotonically increasing, per-`$queue/`, cluster-wide sequence number to every message it persists. The broker MUST include Property 0x30 in the PUBLISH delivered to consumers. Clients MUST NOT set this property; if present in a client PUBLISH, the broker MUST overwrite it. |
| **Property 0x35: Stream Epoch** | Two Byte Integer. A conformant broker MUST include this property in CONNACK when the client presents a `last-seq` in CONNECT. If the broker cannot guarantee sequence continuity from `last-seq` to the current queue head, it MUST set a new Epoch value. What constitutes "cannot guarantee" is implementation-defined; the signal is normative, the trigger is not. |
| **Property 0x41: Throughput Limit** | Four Byte Integer (KB/s). A conformant broker MAY include this property in CONNACK to enforce a per-connection bandwidth ceiling. Client behavior upon receiving this property is advisory only from the MQTT 6.0 perspective; MQTT Stream 1.0 defines normative client handling. |
| **`$queue/` Namespace** | A conformant broker MUST persist a message published to a `$queue/` topic to non-volatile storage before sending PUBACK to the publisher. A `$queue/` entity MUST exist independently of any client session. A conformant broker MUST NOT discard a `$queue/` message because all consumers are disconnected. |
| **Virtual FETCH** | A conformant broker MUST support pull-based delivery via PUBLISH to `$SYS/queues/{name}/fetch` with `batch-size` User Property. The broker MUST hold messages in the queue until a FETCH is received; it MUST NOT push messages to a `$queue/` consumer except in response to a FETCH. |
| **SQMC Semantics** | A conformant broker MUST honor the `v6-semantics` User Property in SUBSCRIBE. `competing` mode: broker distributes each message to exactly one consumer in the group. `exclusive` mode: broker delivers all messages to a single designated consumer; on that consumer's disconnect, the broker MUST transfer delivery to the next-eligible subscriber without message loss. |
| **v6.0 Handshake** | A client signals v6.0 support by including `User Property: ("mqtt-ext", "v6.0")` in CONNECT. A conformant broker MUST echo this property in CONNACK. A client that does not receive the echo MUST NOT use `$queue/` topics or rely on Property 0x30/0x35 semantics. |

### 2.2 What MQTT 6.0 Explicitly Does NOT Define

The following are out of scope for the MQTT 6.0 transport extension spec:

- How clients detect sequence gaps
- How clients respond to an Epoch change
- The client-side consumer state machine
- Exactly-once delivery guarantees at the application layer
- The high-watermark persistence protocol
- FETCH batch-size selection algorithms or pipelining strategies
- The reconnect protocol (what `last-seq` and `current-epoch` values clients SHOULD present in CONNECT)
- Sequence wraparound handling at the client side
- Application patterns for competing vs. exclusive consumer modes

These belong to MQTT Stream 1.0.

---

## 3. MQTT Stream 1.0 Application Protocol Specification

MQTT Stream 1.0 is an application-layer protocol specification that references MQTT 6.0 as its required transport extension. A conformant MQTT Stream 1.0 client library implements all of the following normatively.

### 3.1 Stream Consumer State Machine

A conformant client MUST implement the following FSM:

```
CONNECTING → HANDSHAKING → FETCHING → PROCESSING → ACKNOWLEDGING
                ↑                                        |
                └──────────── RESYNCING ←────────────────┘
                                  ↑
                          (Epoch change detected)
```

| State | Entry Condition | Exit Condition |
|---|---|---|
| CONNECTING | Client initiates TCP/TLS connection | CONNACK received |
| HANDSHAKING | CONNACK received | Broker echoes `mqtt-ext: v6.0`; client loads persisted high-watermark |
| FETCHING | HANDSHAKING complete | FETCH sent; batch received |
| PROCESSING | Batch received | All messages in batch processed by application |
| ACKNOWLEDGING | Processing complete | PUBACK sent for all batch messages; high-watermark advanced |
| RESYNCING | Epoch in CONNACK differs from client's stored epoch | Client discards idempotency state, resets high-watermark, returns to HANDSHAKING |

### 3.2 Gap Detection Protocol

A conformant client MUST implement the following algorithm on each received message:

1. Let `expected_seq` = `high_watermark + 1`
2. Let `received_seq` = Property 0x30 of the received PUBLISH
3. If `received_seq == expected_seq`: advance `high_watermark`, process message, go to step 1
4. If `received_seq > expected_seq`: a gap exists. The client MUST NOT process messages beyond the gap. The client MUST send a gap notification to the application layer with `(expected_seq, received_seq - 1, queue_name)`. The client MAY request gap-fill (implementation-defined recovery) or enter RESYNCING
5. If `received_seq < expected_seq`: duplicate. The client MUST silently discard the message without advancing `high_watermark` or notifying the application

### 3.3 Epoch Resync Protocol

On receiving a CONNACK where Property 0x35 differs from the client's stored epoch:

1. Log the epoch transition with stored epoch, new epoch, queue name, and timestamp
2. Discard the entire in-memory idempotency state for the affected queue(s)
3. Reset `high_watermark` to the value indicated by the broker's CONNACK (or 0 if not provided)
4. Notify the application layer that sequence continuity cannot be guaranteed for the window between the last-acknowledged sequence and the new queue head
5. Persist the new epoch value
6. Return to HANDSHAKING state

### 3.4 High-Watermark Protocol

- The client MUST persist `high_watermark` (last successfully processed and acknowledged sequence number) to durable local storage after each successful ACKNOWLEDGING state transition
- On reconnect, the client MUST present the persisted `high_watermark` as `last-seq` in the CONNECT User Property
- The high-watermark MUST NOT advance until the application layer confirms processing is complete and PUBACK has been sent
- For ordered `$queue/` delivery, a single integer watermark is sufficient (O(1) storage). Set-based idempotency tables are not required

### 3.5 Exactly-Once Delivery Contract

The full client-side exactly-once workflow:

1. Receive PUBLISH with Property 0x30 = `seq`
2. If `seq <= high_watermark`: discard (duplicate), do not deliver to application
3. If `seq > high_watermark + 1`: gap detected; enter gap-handling procedure (Section 3.2)
4. If `seq == high_watermark + 1`: deliver to application
5. Application confirms processing complete
6. Send PUBACK to broker
7. Persist `high_watermark = seq`

Steps 5–7 MUST be atomic from the application's perspective: the watermark MUST NOT be advanced if PUBACK fails, and PUBACK MUST NOT be sent if application processing fails.

### 3.6 FETCH Pacing

- **Baseline algorithm:** Request `batch-size = min(processing_capacity, max_batch)` where `processing_capacity` is the number of messages the consumer can process before the next FETCH
- **Pipelining:** A client MAY issue the next FETCH before the current batch is fully acknowledged, provided the pipeline depth does not exceed `Receive Maximum`
- **Back-pressure signaling:** If application processing time exceeds a configurable threshold, the client MUST reduce `batch-size` by 50% on the next FETCH. Recovery to full batch size MUST be gradual (linear increase per successful batch)
- **Idle behavior:** If the broker returns an empty batch, the client SHOULD use long-polling (`Wait-Timeout` User Property) on the next FETCH rather than tight-loop polling

### 3.7 Reconnect Protocol

On reconnect, the client MUST include in CONNECT:

- `User Property: ("last-seq", "<high_watermark>")` — the last durably processed sequence number
- `User Property: ("current-epoch", "<stored_epoch>")` — the epoch value the client last saw

The broker uses these values to determine whether to increment the Epoch in CONNACK and to identify the resume point in the queue. A broker that receives `last-seq` beyond the current queue head MUST signal an error condition.

### 3.8 Sequence Wraparound Rules

- A 32-bit sequence wraps at 2^32 - 1. The client MUST treat Seq 0 following Seq 0xFFFFFFFF as a continuation, not a gap
- The broker MUST increment Property 0x35 (Epoch) coincident with sequence wraparound to provide an unambiguous continuity marker
- Clients MUST NOT assume that a lower sequence number following a higher one indicates a gap if the Epoch has also changed

### 3.9 SQMC Application Patterns

**Competing mode (`v6-semantics: competing`):**
- Use for stateless consumers that can independently process any message in the queue
- Deploy N consumer instances, each maintaining its own high-watermark
- On consumer failure, surviving consumers continue processing; the failed consumer's in-flight messages are requeued by the broker and dispatched to the next available consumer

**Exclusive mode (`v6-semantics: exclusive`):**
- Use for stateful consumers where ordering is safety-critical (SECS/GEM command streams, protection relay sequences)
- Deploy one active consumer and one standby consumer subscribed to the same queue
- On active consumer failure, the broker promotes the standby automatically within one broker-side timeout interval
- The standby MUST present its high-watermark in CONNECT so the broker can resume from the correct position

---

## 4. How This Addresses Committee Criticisms

### 4.1 Simon's "Mux'ing" Criticism

> *"There appears to be a mux'ing of what is expected of the application and what is expected of the protocol."*

Option C is the most complete answer to this criticism. MQTT 6.0 contains zero application-layer concerns: no state machines, no gap-detection algorithms, no consumer patterns. MQTT Stream 1.0 contains zero broker-internal concerns: no persistence requirements, no property ID definitions, no packet formats. The line is absolute. A reader of the MQTT 6.0 spec cannot find application-layer logic in it. A reader of the MQTT Stream 1.0 spec cannot find wire-format definitions in it. The mux'ing is eliminated by structural separation, not by argument.

### 4.2 The "This Should Be Application-Level" Argument

We agree. MQTT Stream 1.0 IS the application-level standard. It lives in a separate document, governed separately, versioned separately, with its own conformance test suite. The committee members who raised this concern were correct: gap detection, epoch handling, and consumer state machines belong at the application layer. Option C puts them there.

### 4.3 The "Bloat / Kafka Clone" Criticism

The MQTT 6.0 spec is a small transport extension. It does not define application patterns. It specifies five new broker behaviors and three new property IDs. The spec document is short. It is not trying to be Kafka. MQTT Stream 1.0 provides Kafka-like application semantics as a separate, opt-in specification. A broker vendor who implements MQTT 6.0 is not required to implement MQTT Stream 1.0. A client developer who targets MQTT Stream 1.0 gets Kafka-like semantics over MQTT without the Kafka footprint. These are separable decisions.

### 4.4 The "Standardize Now vs. Extension First" Argument

MQTT 6.0 goes to OASIS as a minimal transport extension — a narrow, well-scoped document that broker vendors can implement incrementally. MQTT Stream 1.0 can be submitted to the Eclipse Foundation (as a Sparkplug-family specification) or as an OASIS TC note — a separate track with faster iteration cycles. The application protocol can evolve without reopening the OASIS MQTT 6.0 standard. This decouples the governance cadence from the innovation cadence.

### 4.5 Property ID Conflict Risk

A minimal MQTT 6.0 spec using only Property 0x30 (Stream Sequence Number) and Property 0x35 (Stream Epoch) — and optionally 0x41 (Throughput Limit) — is a far smaller OASIS ask than a comprehensive spec. Smaller footprint means fewer property ID claims, fewer normative requirements, and less surface area for OASIS technical review to find objections. The minimal-scope approach maximizes the probability of OASIS approval for the transport layer while leaving the application layer free to evolve.

---

## 5. Governance Split

| Specification | Governing Body | Version Cadence | Who Contributes | Role |
|---|---|---|---|---|
| MQTT 6.0 | OASIS MQTT TC | Stable / slow (years per revision) | Broker vendors, protocol architects, OASIS members | Foundational transport primitives — changes here affect the entire ecosystem |
| MQTT Stream 1.0 | Eclipse Foundation (or OASIS TC Note) | Faster iteration (months per revision) | Application developers, industrial users, client library authors | Application-layer profile — changes here affect Stream-conformant clients only |

The governance split mirrors the Sparkplug B precedent: MQTT 3.1.1 is an OASIS standard governed by the MQTT TC; Sparkplug B is an Eclipse specification governed by the Sparkplug Working Group. They have different maintainers, different release schedules, and different audiences. MQTT Stream 1.0 would occupy the same structural position relative to MQTT 6.0 that Sparkplug B occupies relative to MQTT 3.1.1 — except that MQTT Stream 1.0 would be an officially recognized companion specification rather than a third-party profile.

---

## 6. Interoperability Contract

An MQTT Stream 1.0 conformant client library + an MQTT 6.0 conformant broker = a fully interoperable industrial messaging system.

The contract is bidirectional:

- **MQTT 6.0 without MQTT Stream 1.0:** A broker that implements MQTT 6.0 provides the transport primitives. Any client that can issue a FETCH control publish and read Property 0x30 can consume from a `$queue/` — but the exactly-once guarantees and gap-recovery procedures are application-defined. This is sufficient for broker vendors who want to offer the primitives and let client libraries define their own application profiles.

- **MQTT Stream 1.0 without MQTT 6.0:** Not possible. MQTT Stream 1.0 is normatively dependent on MQTT 6.0. A client library that claims MQTT Stream 1.0 conformance MUST run on an MQTT 6.0 broker; it MUST NOT claim conformance when connected to an MQTT 5.0 broker.

- **Both together:** Full industrial reliability stack. Gap detection, epoch resync, high-watermark persistence, exactly-once delivery, and FETCH pacing are all specified normatively. A semiconductor fab can run any MQTT Stream 1.0 client library against any MQTT 6.0 broker and get identical behavior — no vendor-specific payload conventions, no custom middleware, no Kafka bridge.

Neither specification is complete without the other for the industrial use case. But each is complete for its own layer, and each can be implemented, tested, and certified independently.

---

## 7. Trade-offs

### Advantages

- **Maximum committee acceptance for MQTT 6.0.** A narrow transport extension spec is the easiest possible OASIS ask. Reviewers who object to application-layer content in a protocol spec will find nothing to object to.
- **MQTT Stream 1.0 evolves faster.** Eclipse Foundation governance moves faster than OASIS. The application protocol can be updated as industrial requirements evolve without reopening the MQTT 6.0 OASIS standard.
- **Clear governance split.** Broker vendors own MQTT 6.0 conformance. Client library authors own MQTT Stream 1.0 conformance. Responsibilities are unambiguous.
- **Clean precedent.** The Sparkplug B model is understood by the standards community. Option C fits a known pattern.

### Disadvantages

- **Two separate standardization processes.** The working group must maintain two documents, two conformance test suites, and two submission tracks. This is more work than a single integrated specification.
- **Interoperability requires conformance to both specs.** Implementers who want full industrial reliability must implement both layers. The answer to "which spec do I implement?" is "both, depending on your role." This adds explaining overhead, particularly for new adopters.
- **Risk of MQTT Stream 1.0 underadoption.** If MQTT 6.0 ships and MQTT Stream 1.0 fails to gain traction, the transport primitives (Property 0x30, Property 0x35, `$queue/`) may be underutilized or reimplemented inconsistently by client library authors — recreating the fragmentation problem at the application layer instead of the protocol layer.
- **Conformance surface area.** A client library can claim "MQTT 6.0 compatible" without implementing the Stream state machine. This may create a false sense of industrial readiness in the ecosystem.

---

## 8. Analogues in Other Protocol Ecosystems

This separation pattern is well-established and understood by standards bodies. The table below shows the direct parallels.

| Transport Spec | Application Profile | Relationship | Parallel to Option C |
|---|---|---|---|
| **MQTT 3.1.1** (OASIS) | **Sparkplug B** (Eclipse) | Sparkplug defines payload encoding, sequence numbers, and state management on top of MQTT pub/sub | Most direct analogue: MQTT Stream 1.0 would be the official Sparkplug B for MQTT 6.0 |
| **HTTP/1.1** (IETF RFC 2616) | **REST** (Fielding, 2000) | REST is an architectural style for distributed hypermedia systems over HTTP; it is not an HTTP extension | Architectural style defined separately from the transport protocol |
| **CoAP** (IETF RFC 7252) | **LwM2M** (OMA SpecWorks) | LwM2M defines a device management application protocol over CoAP; CoAP defines the constrained transport | IoT transport + IoT application management profile, separate governance bodies |
| **AMQP 1.0** (OASIS) | **JMS 2.0** (Jakarta EE) | JMS defines a Java messaging API that can be backed by AMQP 1.0 as a wire transport; the API spec and the wire spec are independent | API/application spec built on top of a wire transport standard |

The CoAP + LwM2M parallel is particularly apt: both are IoT protocols, CoAP is IETF-governed and LwM2M is OMA-governed, and the separation is clean enough that LwM2M implementations can run over CoAP or HTTP depending on the deployment. MQTT Stream 1.0 over MQTT 6.0 follows exactly this model.

The Sparkplug B parallel is the most persuasive for this committee: Sparkplug already defines application-layer sequencing (`bdSeq`, `seq` fields in protobuf payloads), birth/death certificate state management, and reconnect procedures on top of MQTT 3.1.1 — and it works. MQTT Stream 1.0 would provide those same guarantees at the wire level, under official MQTT ecosystem governance, for any MQTT 6.0 broker. Option C is not a novel idea. It is the formalization of a pattern the MQTT community already uses in production.

---

## References

- [MQTT v5.0 OASIS Standard](https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html)
- [Eclipse Sparkplug B Specification](https://sparkplug.eclipse.org/specification/)
- [OMA LwM2M Specification](https://www.openmobilealliance.org/solutions/lightweight-m2m)
- [RFC 7252: CoAP](https://datatracker.ietf.org/doc/html/rfc7252)
- [AMQP 1.0 OASIS Standard](https://www.amqp.org/node/102)
- MQTT v6.0 Proposal Spec: `docs/spec/mqtt-v6.0-spec.md`
- Committee Rebuttals: `docs/rebuttals.md`
- Critiques and Rebuttals: `docs/critiques-and-rebuttals.md`
- Alternative Approaches: `docs/alternatives.md`
