# Option B: MQTT 6.0 with Normative Client Annex — Explicit Layer Boundary

**Author:** Bill Sommers, AI Solutions Lead, HiveMQ, Inc.
**Date:** March 2026
**Status:** Proposal — For Committee Review

---

## 1. Overview

### The Problem With the Current Spec Structure

The current `mqtt-v6.0-spec.md` interleaves two distinct categories of normative obligation throughout its sections. Section 3.1 specifies what a client MUST include in CONNECT; Section 4.3.3 specifies what a client MUST do on reconnect; Section 4.3.4 specifies how a client MUST manage its idempotency table. These are client library behaviors. Section 4.1.1 specifies what a broker MUST do with storage before issuing PUBACK; Section 4.3.1 specifies what a broker MUST do with a distributed sequence counter; Section 4.4.1 specifies how a broker MUST handle message locking. These are broker behaviors. Both categories appear in the same numbered sections, often in adjacent subsections, with no structural signal to the reader that they represent different contractual parties.

This is the source of Simon's "mux'ing" criticism: *"There appears to be a mux'ing of what is expected of the application and what is expected of the protocol."* The criticism is accurate. The spec is not wrong in content, but it is ambiguous in structure.

### The Option B Solution

Option B retains the single-document structure — one OASIS submission — but reorganizes the content to make the architectural boundary explicit. The main body (Sections 1–7) becomes broker normative requirements only. A new **Annex A (normative)** collects all client library MUST/SHOULD behaviors. The existing code examples and informative implementation guidance move to **Annex B (informative)**.

The analogy is instructive: MQTT v5.0 itself has a main body defining the protocol and informative annexes providing implementation guidance. Option B promotes client behavior from informative to normative, and separates it from broker behavior by document structure rather than by convention.

This is not a reduction in scope. All five v6.0 features remain. The total set of normative requirements is unchanged. What changes is their organization: a reader evaluating broker conformance reads Sections 1–7. A reader implementing a client library reads Annex A. The mux'ing is resolved by separation within the document.

---

## 2. Proposed Spec Restructure

The reorganization maps the current spec content to three structural zones:

| Zone | Scope | Normative? | Audience |
|------|-------|------------|----------|
| **Sections 1–7 (main body)** | Broker obligations only | Yes | Broker implementers, OASIS committee |
| **Annex A** | Stream client library obligations | Yes | Client library authors |
| **Annex B** | Example implementations, code patterns | No (informative) | Application developers |

Current content moves as follows:

### Sections 1–7 (Broker Normative — Unchanged Scope, Tightened Audience)

- Section 1: Introduction, conformance, terminology — retained as-is
- Section 2: Wire format, property IDs, packet types — retained; client-side property interpretation moves to Annex A
- Section 3: CONNECT/CONNACK/PUBLISH/SUBSCRIBE/FETCH packet specifications — broker-side processing only; client-side obligations (what to send, when, with what values) move to Annex A
- Section 4: Operational behavior — `$queue/` persistence, ordering, FETCH handling, Epoch management, SQMC mechanics — broker obligations only
- Section 5: v5.0 vs. v6.0 comparison table — retained
- Section 6: Compatibility Layer — broker-side compat mode requirements
- Section 7: Security Considerations — retained as-is

### Annex A (Normative) — Stream Client Implementation Requirements

New section. Contains all client library MUST/SHOULD behaviors currently scattered through Sections 3 and 4. See Section 3 of this document for the complete content specification.

### Annex B (Informative) — Implementation Examples

Existing Annex A (SECS/GEM Mapping) moves here. Python shim examples, Java HiveMQ extension patterns, and the Protobuf schemas currently in `src/` are referenced here as non-normative implementation guidance.

---

## 3. Annex A Content: What Gets Lifted

Annex A is titled **"Stream Client Implementation Requirements"** and opens with the following normative statement:

> A conformant Stream Client implementation MUST implement all MUST-level requirements in this Annex. Failure to implement these requirements results in undefined behavior with respect to exactly-once processing, gap detection, and epoch-safe resumption.

### A.1 Stream Consumer State Machine

The client library MUST implement the following states and transitions for each `$queue/` subscription:

```
States: {CONNECTING, HANDSHAKING, FETCHING, PROCESSING, ACKNOWLEDGING, RESYNCING}

CONNECTING     -> HANDSHAKING   : CONNACK received with mqtt-ext: v6.0 confirmed
HANDSHAKING    -> FETCHING      : Epoch check complete (see A.4); FETCH issued
HANDSHAKING    -> RESYNCING     : Epoch in CONNACK != stored Epoch
FETCHING       -> PROCESSING    : PUBLISH batch received from broker
PROCESSING     -> ACKNOWLEDGING : Business logic complete for message N
ACKNOWLEDGING  -> FETCHING      : PUBACK sent; batch exhausted or next FETCH issued
ACKNOWLEDGING  -> PROCESSING    : Next message in batch available (batch not yet exhausted)
RESYNCING      -> FETCHING      : Application confirms new high-watermark; Epoch stored
Any state      -> CONNECTING    : TCP disconnect or DISCONNECT packet received
```

The client MUST NOT issue a FETCH request from any state other than FETCHING. The client MUST NOT process messages from any state other than PROCESSING.

### A.2 Gap Detection

The client MUST maintain a variable `expected_seq` per subscribed `$queue/{name}`, initialized to `last_stored_hwm + 1` on connect (or `1` on first connect).

On receipt of each PUBLISH from a `$queue/` topic:

1. If `received_seq == expected_seq`: proceed to processing; set `expected_seq = received_seq + 1`
2. If `received_seq > expected_seq`: a gap exists between `expected_seq` and `received_seq - 1`. The client MUST invoke the application's registered gap handler before processing `received_seq`. The gap handler MAY choose to halt, reconcile, or log-and-continue — this is application policy. The client library MUST NOT silently skip the gap.
3. If `received_seq < expected_seq`: the message is a duplicate (already processed). The client MUST send PUBACK but MUST NOT re-execute business logic. The client MUST NOT update `expected_seq`.

### A.3 High-Watermark Management

The client MUST persist the last successfully processed Stream Sequence Number per `$queue/{name}` as the **High-Watermark** (`hwm`). Persistence MUST be durable (survives process restart). The atomicity requirement: the High-Watermark update and the business-logic side effect MUST succeed or fail together. If the High-Watermark cannot be persisted, the client MUST NOT send PUBACK.

The client SHOULD use the High-Watermark as the `v6-last-seq` User Property value in CONNECT on reconnect. This enables the broker to resume delivery from `hwm + 1` without re-delivering already-processed messages.

For in-order `$queue/` delivery (the normal case), the High-Watermark model is O(1) in storage. A set-based idempotency table is only required when the application enables delivery modes that can produce out-of-order receipt (not the default).

### A.4 Epoch Change Protocol

On receiving CONNACK, the client MUST compare the Epoch value in CONNACK against its stored Epoch for each subscribed `$queue/{name}`.

If `connack_epoch != stored_epoch`:

1. The client MUST discard its local idempotency state for the affected queue (High-Watermark, `expected_seq`, and any set-based dedup table)
2. The client MUST log the Epoch change with: timestamp, queue name, previous Epoch value, new Epoch value
3. The client MUST invoke the application's registered epoch-change handler and MUST wait for it to return a new high-watermark before transitioning to FETCHING
4. The client MUST store the new Epoch before issuing any FETCH request
5. The client MUST NOT attempt to use sequence numbers from the previous Epoch for deduplication

If `connack_epoch == stored_epoch`, the client MAY proceed directly to the FETCHING state using its stored High-Watermark.

### A.5 Reconnect and Resume

The client SHOULD include the following User Properties in CONNECT after any disconnection from a queue it was consuming:

- `v6-last-seq`: the decimal string of the stored High-Watermark for the most recently consumed queue
- `v6-epoch`: the decimal string of the stored Epoch for that queue

If multiple queues are active, the client SHOULD send one `v6-last-seq`/`v6-epoch` pair per queue using repeated User Properties keyed by queue name (e.g., `v6-last-seq:$queue/line_1`).

The client MUST NOT send a `v6-last-seq` value that has not been durably persisted. Reporting a false high-watermark (higher than the true last processed sequence) causes silent message loss.

### A.6 FETCH Pacing Strategy

The client MUST NOT issue overlapping FETCH requests for the same `$queue/{name}`. A FETCH is outstanding from the moment it is sent until the full batch has been acknowledged (all PUBACKs sent for the batch).

The RECOMMENDED initial batch size is 1. The RECOMMENDED pacing algorithm is additive doubling on success: if a batch of N is fully processed without error, the next FETCH MAY use batch size 2N, up to a configurable maximum. On processing error, the client SHOULD reduce batch size to 1 and re-FETCH from the last acknowledged sequence.

The client MAY issue the next FETCH before the current batch is fully acknowledged, provided the outstanding FETCH is for the immediately following sequence range (pipelining). The client MUST track which sequences are outstanding across pipelined requests.

### A.7 Idempotency Table Lifecycle

The High-Watermark (Section A.3) is sufficient for exactly-once processing under in-order delivery, which is the invariant provided by `$queue/` ordered delivery. The client SHOULD use the High-Watermark model and SHOULD NOT maintain a set-based idempotency table unless the application explicitly requires processing of out-of-order delivery.

If a set-based table is used, the client MUST garbage-collect entries with sequence numbers at or below the current High-Watermark. Epoch changes (Section A.4) are natural garbage-collection boundaries: the client MUST discard the entire set on Epoch change.

The client MUST NOT allow the idempotency table to grow without bound. If set size exceeds a configurable threshold, the client SHOULD log a warning and SHOULD trigger a manual reconciliation request.

### A.8 Sequence Wraparound

The 32-bit Stream Sequence Number space is exhausted at `0xFFFFFFFF`. The client MUST treat `Seq 0` received after `Seq 0xFFFFFFFF` as a valid continuation, not as a gap. The broker MUST couple wraparound with an Epoch increment (per Section 4.3.2.2 of the main body); the client's Epoch change protocol (Section A.4) handles the state reset automatically.

The client MUST NOT treat a sequence gap of magnitude `0xFFFFFFFF` or greater as evidence of missing messages; it MUST instead treat it as evidence of a wraparound event and proceed through the Epoch change protocol.

---

## 4. How This Addresses Committee Criticisms

### Simon's "Mux'ing" Criticism

> "There appears to be a mux'ing of what is expected of the application and what is expected of the protocol."

**Option B response:** The Annex A boundary makes the separation explicit and auditable within the document. Sections 1–7 (main body) = broker contract. Annex A = client contract. The mux'ing is resolved by structural separation within the spec. A committee member evaluating broker conformance reads through Section 7 and stops. A committee member evaluating client library conformance reads Annex A. The two audiences no longer read the same section headers as addressing them both.

### The "Application-Level" Argument

> The objection that gap detection, epoch handling, and consumer state management are application-level concerns and should not be in a protocol spec.

**Option B response:** Annex A acknowledges this directly. Gap detection, Epoch handling, and consumer state management ARE application-layer responsibilities — they are normative requirements on the **client library**, not on the broker, and they are placed in an Annex explicitly to signal this. The main body does not require applications to manage sequence state; it requires a conformant client library to do so. This mirrors how MQTT v5.0 itself specifies client behavior (QoS retry, session resumption) separately from broker behavior, without those client behaviors being "mixed into" broker sections.

### Procedural Argument

> The concern that two separate documents (a hypothetical Option A split) create submission and versioning complexity at OASIS.

**Option B response:** A single document is easier to submit to OASIS as one coherent standard. The committee evaluates broker and client behavior together in a single review cycle. There is no synchronization risk between two documents, no question of which version of a client spec corresponds to which version of a broker spec, and no procedural ambiguity about whether Annex A is binding.

### The "Bloat" Criticism

> "MQTT's success is its simplicity. v6.0 turns it into a bloated Kafka clone." (Criticism 1 in `critiques-and-rebuttals.md`)

**Option B response:** The main body, after restructuring, contains only broker obligations. Sections 1–7 are trimmed of all client-side MUST/SHOULD language, which moves to Annex A. The perceived bloat was the interleaving — a reader scanning the main body encountered client library state machine requirements alongside broker wire-format requirements. After restructuring, the main body is visibly shorter and more focused. The total normative content is unchanged, but each section addresses a single audience.

---

## 5. Comparison: Current Spec vs. Option B Structure

| Spec Content | Current Location | Option B Location | Type |
|---|---|---|---|
| Property IDs 0x30, 0x35, 0x41, 0x42 wire format | Section 2.2 | Section 2.2 (unchanged) | Normative |
| FETCH packet structure | Section 3.5 | Section 3.5 (unchanged) | Normative |
| Broker: assign Seq before PUBACK | Section 4.1.1 | Section 4.1.1 (unchanged) | Normative |
| Broker: Epoch increment conditions | Section 4.3.2.2 | Section 4.3.2.2 (unchanged) | Normative |
| Broker: SQMC message locking | Section 4.4.1 | Section 4.4.1 (unchanged) | Normative |
| **Client: send v6-last-seq in CONNECT** | Section 3.1 (mixed) | **Annex A.5** | Normative |
| **Client: discard idempotency on Epoch change** | Section 2.2.2 (mixed) | **Annex A.4** | Normative |
| **Client: High-Watermark persistence** | Section 4.3.4 (mixed) | **Annex A.3** | Normative |
| **Client: gap detection algorithm** | Section 4.3.4 (implicit) | **Annex A.2** | Normative |
| **Client: FETCH pacing** | Not specified | **Annex A.6** | Normative |
| **Client: state machine** | Not specified | **Annex A.1** | Normative |
| **Client: sequence wraparound handling** | `critiques-and-rebuttals.md` Pitfall 1 (informative) | **Annex A.8** | Normative |
| SECS/GEM mapping | Annex A (current) | Annex B (informative) | Informative |
| Python/Java code examples | `src/` directory | Annex B (informative) | Informative |
| Protobuf schemas | `src/` directory | Annex B (informative) | Informative |

---

## 6. Trade-offs

### Pros

- **Single OASIS submission.** One document, one submission, one review cycle. No fragmentation risk between a broker spec and a client spec.
- **Full system evaluated together.** The committee sees both broker and client obligations in one pass. The interaction between broker Epoch propagation (Section 4.3.2.3) and client Epoch change protocol (Annex A.4) is visible in context.
- **No new scope.** All five v6.0 features are preserved. Annex A collects and formalizes client obligations that are already implied by the current spec; it does not add new ones.
- **Addresses Simon's criticism directly.** The mux'ing is resolved by the Annex boundary without splitting the document.
- **Lighter main body.** Sections 1–7 become visibly more focused after client-side MUST language is lifted to Annex A.

### Cons

- **Annex A is still in the spec.** Committee members who object to the total scope (gap detection, state machine, epoch handling in a protocol spec) will still see it. Option B separates it structurally; it does not remove it. If the objection is to scope rather than to presentation, Option B does not fully resolve it.
- **Client library improvements require OASIS revision.** Because Annex A is normative and inside the spec, any update to client library MUST/SHOULD requirements (e.g., adding a new state to the state machine, or revising the FETCH pacing algorithm) requires a formal OASIS revision cycle. This is slower than maintaining a separate client implementation guide.
- **Less clean than a full split.** Option A (a separate client implementation specification document) would provide a more complete architectural separation. Option B is a compromise — it draws the boundary explicitly, but both sides of the boundary remain in the same document.

---

## 7. What the Main Body (Sections 1–7) Looks Like After Restructure

After lifting all client-side MUST/SHOULD language to Annex A, the main body sections become:

**Section 1 — Introduction and Conformance:** Unchanged. Conformance criteria updated to reference Annex A for client library conformance.

**Section 2 — Wire Format:** Broker-only: property ID assignments, data types, packet type definitions. Client-side property interpretation (e.g., "a client that receives an Epoch value greater than its stored Epoch MUST...") moves to Annex A.4.

**Section 3 — Control Packets:** Broker-only processing rules for CONNECT, CONNACK, PUBLISH, SUBSCRIBE, FETCH. What the broker MUST validate, reject, or respond to. Client-side sending obligations (what values to populate, when) move to Annex A.5.

**Section 4 — Operational Behavior:** Broker-only: `$queue/` persistence contract, Epoch increment conditions and propagation, SQMC locking semantics. The "Exactly-Once Processing" subsection (Section 4.3.4) moves entirely to Annex A, as it describes client library behavior with no broker obligation.

**Section 5 — Summary of Changes:** Unchanged comparison table.

**Section 6 — Compatibility Layer:** Broker-side compat mode requirements. Client-side compat mode behavior (which User Property to send instead of which native property) moves to Annex A.

**Section 7 — Security Considerations:** Unchanged. Sections 7.3 and 7.4 (Sequence Number Side-Channel and High-Watermark Persistence) move to Annex A, as both describe client implementation obligations.

The result is a main body of roughly 60–70% of the current length, with all remaining content directly addressing broker implementers. The substantive content removed from the main body does not disappear — it becomes the formally bounded client contract in Annex A.

---

## References

- MQTT v5.0 OASIS Standard: https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html
- Current v6.0 specification: `docs/spec/mqtt-v6.0-spec.md`
- Standards committee criticisms: `docs/rebuttals.md`, `docs/critiques-and-rebuttals.md`
