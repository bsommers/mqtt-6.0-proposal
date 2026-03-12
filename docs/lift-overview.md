# The Application Layer Lift — Overview

> **Context:** This document addresses the standards committee criticism that the MQTT 6.0 specification conflates broker obligations with application-layer responsibilities. It proposes three structural approaches to drawing a clear boundary between what the **protocol** provides and what the **application layer** must implement using those primitives.

---

## The Core Insight

The MQTT 6.0 proposal solves two distinct problems that have historically been bundled together:

1. **Protocol Primitives** — Things the *broker* must implement: durable queue storage, sequence number assignment, epoch signaling, pull-based message delivery, and strict consumer group enforcement. These require changes to the wire format and broker behavior. They cannot be "lifted" to the application layer — if the broker doesn't do them, no amount of client-side code can compensate.

2. **Application Patterns** — Things the *client library* must implement using those primitives: gap detection, epoch resync procedures, high-watermark tracking, idempotent processing workflows, consumer state machines, and reconnect/resume logic. These sit above the protocol. They are expressible in any language, testable independently of the broker, and can evolve faster than an OASIS standard.

The current MQTT 6.0 specification interleaves both. This is the source of the committee's "mux'ing" objection (Simon, March 2026). The three options below each propose a different way to draw the boundary explicitly.

---

## The Split: Protocol vs. Application Layer

Regardless of which structural option is chosen, the feature split is the same:

### Protocol Layer — Broker Obligations (MQTT 6.0 Spec)

| Feature | What the Broker Does | Property / Mechanism |
|---|---|---|
| Durable Queue Storage | Persist messages before PUBACK; retain independent of sessions | `$queue/` namespace |
| Stream Sequence Assignment | Assign monotonically increasing 32-bit integer per queue message | Property `0x30` |
| Epoch Signaling | Set Epoch in CONNACK when sequence continuity cannot be guaranteed | Property `0x35` |
| Pull-Based Delivery | Hold messages until FETCH received; deliver requested batch | FETCH / Virtual FETCH |
| SQMC Enforcement | Enforce competing/exclusive consumer modes; re-dispatch on disconnect | `v6-semantics` User Property |
| Throughput Limiting | Enforce KB/s limits set in CONNACK | Property `0x41` |
| v6.0 Handshake | Echo `mqtt-ext: v6.0` in CONNACK to confirm capability | User Property |

### Application Layer — Client Library Obligations ("The Lift")

| Responsibility | What the Client Library Does |
|---|---|
| Gap Detection | Track `expected_seq` per queue; detect when `received_seq ≠ expected_seq` |
| High-Watermark Tracking | Persist last successfully processed Seq per queue (O(1) state) |
| Epoch Change Handler | On Epoch mismatch in CONNACK: discard idempotency state, re-establish watermark |
| Consumer State Machine | Manage states: CONNECTING → HANDSHAKING → FETCHING → PROCESSING → ACKNOWLEDGING → RESYNCING |
| Exactly-Once Workflow | Check seq against watermark → process → advance watermark → PUBACK |
| Reconnect / Resume | Send `last-seq` and `current-epoch` as User Properties in CONNECT |
| FETCH Pacing | Manage batch sizing, pipeline depth, and back-pressure signaling |
| Idempotency Table Lifecycle | When to use watermark vs. set-based dedup; garbage collection on Epoch reset |
| Sequence Wraparound | Treat Seq 0 after Seq 0xFFFFFFFF as continuation; coordinate with Epoch at rollover |
| SQMC Application Patterns | Map competing/exclusive modes to use-case requirements; handle failover scenarios |

---

## Why This Answers the Committee

Simon's criticism — *"There appears to be a mux'ing of what is expected of the application and what is expected of the protocol"* — is valid and can be resolved structurally. The three options below each offer a different level of separation:

| Option | Separation Level | Documents | OASIS Submission |
|---|---|---|---|
| **A** | Hard split — two independent documents | MQTT 6.0 spec + MQTT Stream Application Profile | Protocol spec only |
| **B** | Soft split — one document, explicit boundary | MQTT 6.0 spec with Normative Annex A | Full spec as single submission |
| **C** | Maximum split — two independent specifications | MQTT 6.0 transport extension + MQTT Stream 1.0 app protocol | Two separate tracks |

The key concession in all three options: **Simon is correct**. Gap detection, epoch resync, consumer state machines, and exactly-once processing workflows are application-layer responsibilities. The MQTT 6.0 specification does not need to define them — it only needs to provide the primitives that make them possible to implement correctly and interoperably.

---

## Three Options

- **[Option A: Slim Protocol + MQTT Stream Application Profile](lift-option-a.md)**
  Reduces the MQTT 6.0 spec to broker-only primitives. Publishes a separate companion "MQTT Stream Application Profile" defining client library behavior. Analogous to MQTT + Sparkplug B, but officially blessed by the MQTT 6.0 ecosystem. Recommended starting point.

- **[Option B: Protocol Spec + Normative Annex A](lift-option-b.md)**
  Keeps a single MQTT 6.0 document but restructures it: Sections 1–7 contain only broker obligations; Normative Annex A defines client library requirements. Same total scope, explicit structural boundary. Easiest single OASIS submission.

- **[Option C: Two Independent Specifications](lift-option-c.md)**
  Maximum separation. MQTT 6.0 is a minimal wire-format extension (broker-only). A fully separate "MQTT Stream 1.0" specification defines the application protocol that uses MQTT 6.0 as transport. Analogous to CoAP + LwM2M or HTTP + REST. Strongest answer to protocol purists; requires two standardization tracks.

---

## Recommendation

For the current committee review stage, **Option A** offers the best balance: it visibly slims the protocol spec (addressing the "bloat" criticism), explicitly concedes the application-layer boundary (addressing Simon's mux'ing criticism), and provides a practical path where the MQTT Stream Application Profile can be adopted by Eclipse Foundation while the protocol primitives proceed through OASIS.

If the committee's primary concern is procedural scope (what OASIS is asked to ratify), **Option C** is the strongest answer. If a single-document submission is operationally required, **Option B** is the pragmatic choice.

All three options share the same feature split — only the document structure and governance path differ.
