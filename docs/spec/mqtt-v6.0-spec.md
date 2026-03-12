# MQTT Version 6.0
## Industrial Stream and Advanced Queuing Extension

**OASIS Standard Draft**
**Date:** March 2026
**Author:** Bill Sommers, AI Solutions Lead, HiveMQ, Inc.
**Base Specification:** MQTT Version 5.0 OASIS Standard (https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html)

---

## 1. Introduction

MQTT is a Client-Server publish/subscribe messaging transport protocol. It is lightweight, open, simple, and designed to be easy to implement.

**[MODIFIED for v6.0]:** Version 6.0 extends this simplicity with **Deterministic Stream Semantics**. These features provide the reliability required for mission-critical industrial environments — including semiconductor fabrication (SECS/GEM), financial messaging, and large-scale IoT deployments — where message ordering, pull-based flow control, and cluster-wide consistency are mandatory.

MQTT v6.0 is designed to be **wire-compatible** with MQTT v5.0 when the Compatibility Layer is active. All v6.0 extensions utilize the Property and User Property fields that v5.0 mandates be ignored when unrecognized. In Native Mode, v6.0 introduces a new Control Packet type and requires Protocol Level 6.

### 1.1 Conformance

A Client or Server is conformant to MQTT v6.0 if it:

- Meets all normative requirements of MQTT v5.0, AND
- Correctly handles Properties `0x30` (Stream Sequence Number) and `0x35` (Stream Epoch), AND
- Implements the `$queue/` namespace persistence semantics described in Section 4.1, AND
- Implements the v6.0 negotiation handshake described in Section 3.1.

### 1.2 Terminology

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT**, **RECOMMENDED**, **MAY**, and **OPTIONAL** in this document are to be interpreted as described in RFC 2119.

**[NEW for v6.0] Additional Terms:**

| Term | Definition |
|------|-----------|
| **Stream Sequence Number** | A 32-bit monotonic integer uniquely identifying a message within a `$queue/` namespace, persistent across sessions |
| **Stream Epoch** | A 16-bit counter representing the "era" of a queue; incremented when cluster failover may have caused sequence discontinuity |
| **FETCH** | New Control Packet (Type 16) for pull-based message retrieval from persistent queues |
| **`$queue/`** | Topic namespace prefix designating a named, durable, session-independent persistent queue |
| **SQMC** | Single-Queue Multi-Consumer — a queuing pattern where each message is delivered to exactly one of multiple active consumers |
| **Virtual FETCH** | Compatibility-mode representation of FETCH using PUBLISH to `$SYS/queues/{name}/fetch` |
| **High-Watermark** | The last sequence number successfully processed by a consumer client |
| **Distributed Sequence Counter** | A cluster-wide atomic counter, one per `$queue/`; any node may increment it atomically (e.g., via compare-and-swap) to claim the next sequence number. The storage and replication mechanism is implementation-defined. |
| **Competing Consumer** | SQMC mode: messages distributed round-robin; each message delivered to exactly one consumer |
| **Exclusive Consumer** | SQMC mode: one designated consumer receives all messages; others are hot standbys |

### 1.3 Normative References

- MQTT Version 5.0 OASIS Standard: https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html
- RFC 2119: Key words for use in RFCs to Indicate Requirement Levels

### 1.4 Data Representation

All data representation follows MQTT v5.0 conventions.

**[NEW for v6.0]:**
- **Four Byte Integer:** A 32-bit unsigned integer in big-endian order. Used for Stream Sequence Numbers.
- **Two Byte Integer:** A 16-bit unsigned integer in big-endian order. Used for Stream Epochs.

---

## 2. MQTT Control Packet Format

### 2.1 Fixed Header

Every MQTT Control Packet begins with a Fixed Header. The format is unchanged from v5.0.

```
Bit:     7    6    5    4    3    2    1    0
Byte 1:  [ MQTT Control Packet Type  ] [Flags]
Byte 2+: [        Remaining Length        ]
```

**[NEW for v6.0] Control Packet Type 16 — FETCH:**

| Type Value | Name  | Direction        | Description |
|-----------|-------|------------------|-------------|
| 16        | FETCH | Client to Server | Pull-based request for a batch of messages from a named queue |

> **Note on Compatibility:** The Type 16 slot was reserved in v5.0. A strict v5.0 broker will close the connection upon receiving a Type 16 packet. In environments with mixed v5.0/v6.0 brokers, use the Virtual FETCH mechanism (Section 4.2.1) instead.

### 2.2 Variable Header Properties

MQTT v6.0 introduces four new Property Identifiers in the reserved range (`0x30–0x45`):

| Hex  | Name                    | Data Type          | Applicable Packets              |
|------|-------------------------|--------------------|---------------------------------|
| 0x30 | **Stream Sequence Number** | Four Byte Integer | PUBLISH, FETCH (response)       |
| 0x35 | **Stream Epoch**        | Two Byte Integer   | PUBLISH, CONNACK, DISCONNECT    |
| 0x41 | **Throughput Limit**    | Four Byte Integer  | CONNACK                         |
| 0x42 | **Batch Size**          | Four Byte Integer  | FETCH, PUBLISH (Virtual FETCH)  |

#### 2.2.1 Stream Sequence Number (0x30)

- **Type:** Four Byte Integer (32-bit unsigned, big-endian)
- **Packets:** PUBLISH (for `$queue/` topics)
- **Normative:** The Broker MUST assign a monotonically increasing value to this property for every message published to a `$queue/` topic. If the Publisher provides this value, the Broker MUST validate it and MAY override it.
- **Purpose:** Provides a persistent, end-to-end message identity that survives transport-layer reconnections, session restarts, and cluster failovers. Unlike the 16-bit Packet Identifier (which is per-session and recycled), this value is globally unique within a queue's lifetime.

#### 2.2.2 Stream Epoch (0x35)

- **Type:** Two Byte Integer (16-bit unsigned, big-endian)
- **Packets:** PUBLISH, CONNACK, DISCONNECT
- **Normative:** The Broker MUST include the current Epoch in CONNACK for resuming sessions. The Broker MUST increment the Epoch when it cannot guarantee sequence continuity (see Section 4.3.2 for the exhaustive list of triggering conditions). A Client that receives an Epoch value greater than its stored Epoch MUST discard its local idempotency table and perform a full application-layer resynchronization.
- **Purpose:** Identifies the "era" of a queue's sequence space. Allows clients to distinguish between a sequence gap (a missed message) and a cluster reset (all previous sequence context is invalid).

#### 2.2.3 Throughput Limit (0x41)

- **Type:** Four Byte Integer (KB/second)
- **Packets:** CONNACK
- **Normative:** If present, the Client MUST NOT exceed this throughput. If the Client exceeds the limit, the Broker MAY disconnect with Reason Code `0x9B (Quota Exceeded)`.
- **Purpose:** Broker-enforced rate limiting for hardware NIC and storage protection.

#### 2.2.4 Batch Size (0x42)

- **Type:** Four Byte Integer (message count)
- **Packets:** FETCH (native); PUBLISH to `$SYS/queues/{name}/fetch` (compat mode)
- **Normative:** The Broker MUST release at most this many messages in response to a FETCH or Virtual FETCH request. If fewer messages are available, the Broker MUST release only the available count.

---

## 3. MQTT Control Packets

### 3.1 CONNECT – Connection Request

#### 3.1.2.2 Protocol Version

- **v5.0:** Protocol Level value is `5`
- **[MODIFIED for v6.0]:** Protocol Level value is `6` for native v6.0 mode. Clients MAY use Protocol Level `5` combined with the v6.0 User Property for Compatibility Mode operation.

#### 3.1.2.11 CONNECT Properties

All v5.0 CONNECT properties are retained. The following property is added:

**[NEW for v6.0] v6.0 Capability Negotiation:**
- **User Property Key:** `mqtt-ext`
- **User Property Value:** `v6.0`
- **Normative:** A Client wishing to use `$queue/` namespaces, FETCH semantics, or SQMC consumer modes MUST include this property. A Client that does not include it MUST be treated as a legacy v5.0 Client by the Broker.

**[NEW for v6.0] Resync on Reconnect:**
- **User Property Key:** `v6-last-seq`
- **User Property Value:** The decimal string representation of the last successfully processed Stream Sequence Number
- **User Property Key:** `v6-epoch`
- **User Property Value:** The decimal string representation of the Client's current known Epoch
- **Normative:** Upon reconnect, a Client SHOULD include these properties to enable seamless queue resumption. The Broker MUST use these values to resume delivery from the correct position (see Section 4.3).

### 3.2 CONNACK – Connect Acknowledgement

#### 3.2.2.3 CONNACK Properties

All v5.0 CONNACK properties are retained. The following properties are added:

**[NEW for v6.0] v6.0 Capability Confirmation:**
- **User Property Key:** `mqtt-ext`
- **User Property Value:** `v6.0`
- **Normative:** A v6.0-aware Broker MUST echo this property. If absent, the Client MUST assume a legacy v5.0 Broker and MUST NOT use `$queue/` namespaces or FETCH semantics.

**[NEW for v6.0] Throughput Limit (0x41):**
- See Section 2.2.3.

**[NEW for v6.0] Stream Epoch (0x35):**
- **Normative:** REQUIRED when the Client included `v6-epoch` in CONNECT. If the Broker's current Epoch differs from the Client's reported Epoch, the Broker MUST include the new Epoch in CONNACK. The Client MUST respond per Section 2.2.2.

### 3.3 PUBLISH – Publish Message

#### 3.3.2 PUBLISH Variable Header

The PUBLISH packet, when directed to a `$queue/` topic, triggers additional broker-side processing.

**[MODIFIED for v6.0]:**
~~The Server MUST push all matching messages to connected Clients.~~ For `$queue/` topics, the Server MUST NOT push messages unless a FETCH request is active or push mode is explicitly enabled. For standard topics, push behavior is unchanged.

#### 3.3.2.3 PUBLISH Properties

All v5.0 PUBLISH properties are retained. The following properties are added:

**[NEW for v6.0] Stream Sequence Number (0x30):**
- **Normative:** REQUIRED for all PUBLISH packets to `$queue/` topics. The Broker MUST assign this value before persisting the message. See Section 2.2.1.

**[NEW for v6.0] Stream Epoch (0x35):**
- **Normative:** REQUIRED for all PUBLISH packets to `$queue/` topics. The Broker MUST include the current Epoch. See Section 2.2.2.

**[NEW for v6.0] Priority:**
- **User Property Key:** `v6-priority`
- **User Property Value:** Integer 0–255 (higher values = higher priority)
- **Normative:** OPTIONAL. Higher-priority messages SHOULD be delivered to consumers before lower-priority messages in the same queue.

### 3.4 SUBSCRIBE – Subscribe Request

#### 3.8.2.1 SUBSCRIBE Properties

All v5.0 SUBSCRIBE properties are retained. The following User Properties are added for SQMC semantics:

**[NEW for v6.0] Consumer Semantics:**
- **User Property Key:** `v6-semantics`
- **Values:**
  - `competing` — Enables Competing Consumer mode (round-robin; each message delivered to exactly one consumer; message locked until PUBACK received; immediate failover on disconnect)
  - `exclusive` — Enables Exclusive Consumer mode (primary consumer receives all messages; standby consumers receive nothing until primary disconnects)
- **Normative:** If neither value is present, the subscription behaves as standard v5.0 Shared Subscription semantics (if `$share/` prefix is used) or normal subscription semantics otherwise.

**[NEW for v6.0] Consumer Group:**
- **User Property Key:** `v6-group`
- **User Property Value:** A UTF-8 string naming the consumer group
- **Normative:** Clients in the same group sharing a `$queue/` topic with `competing` semantics will receive messages via round-robin distribution. Required when using `v6-semantics: competing`.

### 3.5 FETCH – Pull Request (Type 16) [NEW]

The FETCH packet is a new Control Packet introduced in v6.0. It enables pull-based message retrieval from persistent queues, providing absolute backpressure control.

#### 3.5.1 FETCH Fixed Header

```
Bit:     7    6    5    4    3    2    1    0
Byte 1:  [ 1    0    0    0  ] [ 0    0    0    0 ]
          ^--- Type = 16 ---^   ^--- Reserved ---^
Byte 2+: [         Remaining Length              ]
```

#### 3.5.2 FETCH Variable Header

| Field | Size | Description |
|-------|------|-------------|
| Packet Identifier | 2 bytes | Standard acknowledgement identifier |
| Property Length | Variable | Length of property block |
| Batch Size (0x42) | 4 bytes | Maximum messages to return (REQUIRED) |
| Wait Timeout (0x36) | 2 bytes | Max ms to wait if queue is empty (long-poll; OPTIONAL) |
| Last Received Seq (0x30) | 4 bytes | Client's high-watermark for gap detection (OPTIONAL) |

#### 3.5.3 FETCH Payload

The payload contains the **Queue Name** — a UTF-8 encoded string specifying the target `$queue/` topic (e.g., `$queue/production_line_1`).

```
+-----------------------------------------------------------+
|                  FIXED HEADER (2+ bytes)                  |
| Bits 7-4: Type (16) | Bits 3-0: Reserved (0000)          |
| Remaining Length (Variable Byte Integer)                   |
+-----------------------------------------------------------+
|                   VARIABLE HEADER                          |
| Packet Identifier       (2 bytes)                         |
| Property Length         (Variable)                        |
|   Batch Size    (0x42)  (4 bytes)                         |
|   Wait Timeout  (0x36)  (2 bytes, optional)               |
|   Last Seq      (0x30)  (4 bytes, optional)               |
+-----------------------------------------------------------+
|                      PAYLOAD                               |
| Topic Filter (UTF-8, e.g., "$queue/production_line_1")    |
+-----------------------------------------------------------+
```

#### 3.5.4 FETCH Normative Behavior

- The Broker MUST respond by delivering at most `Batch Size` messages from the specified queue to the Client's session.
- If the queue contains fewer messages than `Batch Size`, the Broker MUST deliver only the available messages.
- If the queue is empty and `Wait Timeout` is specified, the Broker MAY hold the request open until a message arrives or the timeout expires (long-polling).
- If `Last Received Seq` is provided, the Broker MUST validate it against the queue's current state. If the Client's value is ahead of the Broker's known state, the Broker MUST respond with a DISCONNECT containing `Reason Code 0xA0 (Epoch Reset)`.
- The Broker MUST NOT send unsolicited messages from `$queue/` topics unless the Client has an active FETCH request.

#### 3.5.5 FETCH Acknowledgement

The Broker responds to a FETCH by publishing messages with the standard PUBLISH flow (including PUBACK for QoS 1). The Packet Identifier from the FETCH is echoed in the response batch's PUBLISH packets to allow correlation.

---

## 4. Operational Behavior

### 4.1 The `$queue/` Namespace

Topics prefixed with `$queue/` represent **Named Queues** — durable, ordered message stores that exist independently of client sessions.

#### 4.1.0 `$queue/` Behavior by Packet Type

The `$queue/` prefix changes packet semantics as follows:

| Packet | Standard Topic Behavior | `$queue/` Topic Behavior |
|--------|------------------------|--------------------------|
| **PUBLISH (inbound)** | Delivered immediately to matching subscribers | Persisted to non-volatile storage, assigned Stream Sequence Number, acknowledged only after persistence confirmed |
| **PUBLISH (outbound)** | Pushed to subscriber as soon as available | Delivered only in response to a FETCH request (or active push subscription in compat mode); includes Stream Sequence Number and Epoch properties |
| **SUBSCRIBE** | Creates a live subscription; broker pushes matching messages | Registers the client as a consumer of the named queue; delivery mode depends on `v6-semantics` property (default: pull via FETCH) |
| **UNSUBSCRIBE** | Removes subscription; no further messages delivered | Deregisters the consumer; queue continues to exist and buffer messages independently |
| **FETCH** | N/A (not applicable to standard topics) | Requests a batch of messages from the named queue; broker responds with up to `Batch Size` messages |
| **CONNECT (with `v6-last-seq`)** | N/A (property ignored for standard topics) | Broker uses the client's last-seq and epoch to resume delivery from the correct position |

#### 4.1.1 Persistence

- **Normative:** The Broker MUST store messages published to `$queue/` topics in non-volatile storage before acknowledging the PUBACK (QoS 1) or PUBCOMP (QoS 2).
- Messages in `$queue/` MUST NOT be discarded unless:
  - Acknowledged by all intended consumers (per SQMC consumer group logic), OR
  - The message's `Message Expiry Interval` (v5.0 Property 0x02) has elapsed, OR
  - The queue's storage capacity limit has been reached (see Section 4.1.3)

#### 4.1.2 Ordering

The ordering invariant is: **per-queue, per-consumer (or per-consumer-group).**

- **Normative:** The Broker MUST deliver messages to each individual consumer in strict ascending order of their `Stream Sequence Number` within a given `$queue/{name}`.
- The Broker MUST NOT deliver a message with Sequence N+1 before the consumer has acknowledged Sequence N (for QoS 1 and 2 delivery).
- In **Competing Consumer** mode, ordering is guaranteed per-consumer within the group, but not globally across all consumers in the group (since messages are distributed round-robin). Global ordering across the group is achievable only with a single active consumer (Exclusive mode).
- In **Exclusive Consumer** mode, ordering is globally guaranteed because only one consumer is active at any time.

#### 4.1.3 Storage Limits

- **User Property:** `v6-queue-max-size` in SUBSCRIBE — specifies the maximum number of messages to buffer (Four Byte Integer string)
- **Behavior on limit reached:** The Broker SHOULD apply a "drop-oldest" policy by default. An alternative "reject-new" policy returns PUBACK with Reason Code `0x8D (Quota Exceeded)`.
- **User Property:** `v6-queue-ttl` in SUBSCRIBE — specifies how long (seconds) the queue persists after the last consumer disconnects

#### 4.1.4 Access Control

- **Normative:** Access to `$queue/` topics MUST be controlled via ACLs. The Broker SHOULD treat unauthorized publish or subscribe attempts to `$queue/` the same as unauthorized access to `$SYS/` topics.
- The Broker MUST reject subscribe requests to `$queue/` topics from Clients that have not completed the v6.0 negotiation handshake (Section 3.1).

### 4.2 Pull-Based Flow Control

MQTT v6.0 replaces the "push-all" delivery model for queue topics with a **consumer-driven pull model**.

#### 4.2.1 Native Mode (FETCH Packet)

See Section 3.5. The Broker MUST hold queue messages until a FETCH request arrives. This provides absolute backpressure: if the consumer's application layer is slow, it simply does not issue FETCH requests.

#### 4.2.2 Compatibility Mode (Virtual FETCH)

For deployments where clients or brokers do not support Protocol Level 6:

1. **Request:** The Client publishes a message (QoS 1) to `$SYS/queues/{queue_name}/fetch`
2. **Batch Size:** The PUBLISH MUST include `User Property: ("v6-batch", "{N}")` where N is the desired message count
3. **Response:** The Broker releases the next N messages from the persistent queue to the Client's session
4. **Normative:** The Broker MUST NOT release more than N messages per request. If no Virtual FETCH is active, the Broker MUST NOT push queue messages to the Client.

#### 4.2.3 Semantic Equivalence Requirement

**Normative:** The Virtual FETCH mechanism (Section 4.2.2) and the native FETCH packet (Section 4.2.1) MUST provide identical observable behavior to the consumer. Specifically:

- The set of messages returned for a given queue state and batch size MUST be the same regardless of which mechanism is used.
- Ordering guarantees (Section 4.1.2) MUST be preserved in both modes.
- Stream Sequence Number and Stream Epoch values MUST be present in delivered messages in both modes (as native properties in Track A; as User Properties `v6-seq` and `v6-epoch` in Track B).
- The broker MUST NOT push unsolicited `$queue/` messages in either mode.

A conformant implementation MUST pass the same test suite for both mechanisms. The only permitted differences are wire encoding (binary properties vs. string User Properties) and transport overhead.

#### 4.2.4 Rate Limiting

- **Throughput Limit (0x41) in CONNACK:** Broker-enforced KB/s limit on client publish rate
- **Reason Code 0x9B (Quota Exceeded):** Returned when a Client exceeds the throughput limit
- The `Receive Maximum` property from v5.0 continues to apply for QoS 1/2 in-flight limits

### 4.3 Cluster Consistency

In a multi-node deployment, any node MAY accept a publish to a `$queue/` topic. The protocol does not mandate a specific cluster topology, consensus algorithm, or replication strategy. v6.0 defines the **client-facing invariants** that any conformant clustered implementation MUST satisfy, using a **Distributed Sequence Counter** model as the reference mechanism.

#### 4.3.1 Distributed Sequence Counter

- **Normative:** Each `$queue/{name}` MUST maintain a single logical sequence counter whose increments are serialized across all nodes in the cluster. The storage and replication mechanism for this counter is implementation-defined.
- When any node receives a PUBLISH to a `$queue/` topic, it MUST obtain the next sequence number **atomically** (e.g., via compare-and-swap, distributed lock, or equivalent) before persisting the message.
- No routing constraint is imposed on clients or publishers — **any node may sequence any publish**. Monotonicity is guaranteed by the serialized counter, not by sticky routing or leader election.
- If the sequence counter is temporarily unavailable (e.g., due to a network partition or quorum loss), the receiving node MUST reject the PUBLISH with Reason Code `0x97 (Quota Exceeded)` and the client MUST retry after reconnection.
- The Broker MUST NOT assign a sequence number speculatively (i.e., without a confirmed serialized increment). Speculative assignment risks duplicate sequence numbers across nodes.

#### 4.3.2 Epoch Management

##### 4.3.2.1 Scope

The Stream Epoch is **per-queue**: each `$queue/{name}` maintains its own independent Epoch value. An Epoch increment on `$queue/A` has no effect on `$queue/B`.

##### 4.3.2.2 Triggering Conditions (Exhaustive)

The Broker MUST increment the Stream Epoch for a given `$queue/{name}` if and only if one of the following conditions is true:

1. **Sequence counter state loss:** The serialized sequence counter for the queue was unavailable during a failure window, and the Broker cannot confirm that no sequence numbers were issued, duplicated, or lost during that window.
2. **Unrecoverable message loss:** One or more persisted messages in the queue were permanently lost (e.g., all replicas of the message left the cluster before the message was acknowledged by a consumer).
3. **Sequence wraparound:** The 32-bit sequence space has been exhausted and the counter wraps to 0 (see Annex C).

The Broker MUST NOT increment the Epoch for routine events such as node restarts with intact persistent storage, consumer disconnections, or temporary network latency.

##### 4.3.2.3 Propagation

- The new Epoch MUST be propagated in the next CONNACK or PUBLISH to any Client subscribed to the affected queue, and in a DISCONNECT (with Reason Code `0xA0 Epoch Reset`) to Clients that had in-flight messages from the affected queue at the time of the event.
- Nodes rejoining after a partition MUST defer to the surviving cluster's Epoch value for each queue.

##### 4.3.2.4 Mixed-Epoch In-Flight Messages

If a Client has in-flight (unacknowledged) messages from Epoch E and the Broker increments to Epoch E+1:

- The Broker MUST send a DISCONNECT with Reason Code `0xA0 (Epoch Reset)` to the Client.
- The Client MUST discard all unprocessed in-flight messages from Epoch E.
- On reconnect, the Client MUST include `v6-epoch: E` (its last known Epoch) in CONNECT. The Broker responds with the new Epoch in CONNACK per Section 4.3.3.

#### 4.3.3 Client Failover and Resync

When a Client reconnects after a broker failure:

1. Client includes `v6-last-seq: {N}` and `v6-epoch: {E}` in CONNECT
2. Broker checks its local queue state for `$queue/{name}`:
   - If Epoch matches and Seq N is present: resume delivery from N+1
   - If Epoch matches but Seq N is absent (message was lost): begin from the earliest available message and flag the gap
   - If Epoch has incremented: respond with CONNACK containing the new Epoch value; Client MUST reset its idempotency state

#### 4.3.4 Exactly-Once Processing (Application Layer)

Using the Stream Sequence Number as an idempotency key:

1. Consumer maintains a **High-Watermark** (last processed Seq) in an atomic store alongside its business logic
2. On message receipt: if `Seq <= High-Watermark`, acknowledge (PUBACK) but discard — do not process
3. If `Seq > High-Watermark`: execute business logic AND update High-Watermark atomically
4. On Epoch reset: clear the High-Watermark and perform full reconciliation

### 4.4 Single-Queue Multi-Consumer (SQMC)

#### 4.4.1 Competing Consumer Mode

When a consumer subscribes with `v6-semantics: competing`:

- **Message Locking:** When a message is dispatched from the queue to a consumer at QoS 1 or 2, it is "locked" to that consumer.
- **Lock Duration:** The lock persists until the consumer sends PUBACK (QoS 1) or PUBCOMP (QoS 2).
- **Failover:** If the consumer disconnects before acknowledging, the Broker MUST immediately unlock the message and deliver it to the next available consumer in the group.
- **Round-Robin:** The Broker distributes messages across consumers in the group using round-robin or least-loaded assignment. The specific algorithm is implementation-defined.
- **Normative:** Each message MUST be delivered to exactly one consumer in a Competing Consumer group.
- **Normative:** When dispatching a message in Competing Consumer mode, the Broker MUST include all message properties — including payload encryption properties (`0x3A`, `0x3B`, `0x3C`) — unchanged in the PUBLISH delivered to the consumer.

#### 4.4.2 Exclusive Consumer Mode

When a consumer subscribes with `v6-semantics: exclusive`:

- The first Client to subscribe becomes the **Primary Consumer**.
- All subsequent subscribers become **Hot Standbys** — they receive no messages while the Primary is connected.
- **Normative:** If the Primary Consumer disconnects, the Broker MUST immediately promote the first Standby to Primary and resume delivery from the last acknowledged sequence.
- **Ordering guarantee:** Because only one consumer is ever active, strict ordering is preserved across failover.
- **Normative:** When delivering a message to the Primary Consumer in Exclusive mode, the Broker MUST include all message properties — including payload encryption properties (`0x3A`, `0x3B`, `0x3C`) — unchanged in the PUBLISH packet.

---

## 5. Summary of Changes: v5.0 vs. v6.0

| Feature | MQTT v5.0 | MQTT v6.0 |
|---------|-----------|-----------|
| Protocol Level | 5 | **6** (or 5 with compat negotiation) |
| Sequencing | 16-bit Packet ID (per-session, recycled) | **32-bit Stream Sequence (per-queue, persistent)** |
| Flow Control | Push-based (Receive Maximum bounds in-flight window) | **Push + Pull: Receive Maximum for pub/sub; FETCH for queue consumption** |
| Queue Type | Session-bound implicit queue | **Named durable queue (`$queue/` namespace)** |
| Consumer Patterns | Shared Subscriptions (loose) | **SQMC: Competing + Exclusive with message locking** |
| Cluster Consistency | Implementation-defined, opaque to clients | **Epoch-based failover; client-visible resync** |
| Ordering Guarantee | Hop-by-hop, best effort | **Global monotonic ordering within queue** |
| Backpressure | Receive Maximum limits in-flight count | **FETCH adds consumer-initiated pull; broker buffers until requested** |
| Rate Limiting | None | **Throughput Limit property in CONNACK** |
| New Packet Types | None (Types 1-15) | **FETCH (Type 16)** |

---

## 6. Compatibility Layer

MQTT v6.0 is backward-compatible with MQTT v5.0 for all unchanged v5.0 use cases: existing packet types, properties, topics, and semantics continue to work as before. Compatibility is not wire-transparent for v6.0-only features such as FETCH, `$queue/`, Stream Sequence properties, or `last-seq`/`epoch`; those require either Protocol Level 6 or the compatibility mode specified below.

**Compatibility guarantee:** A v5.0 or v3.1.1 client connecting to a v6.0 broker for standard publish-subscribe sees no difference in behavior. The v6.0 extensions activate only when a client explicitly opts in via the negotiation handshake.

### 6.1 Negotiation

| Mode | Protocol Level | User Property |
|------|---------------|---------------|
| Native v6.0 | `6` | `mqtt-ext: v6.0` (optional, implied by level 6) |
| Compat v6.0 (on v5.0 broker) | `5` | `mqtt-ext: v6.0` (required) |
| Legacy v5.0 | `5` | (absent) |

### 6.2 Feature Mapping (Native → Compat)

| Native v6.0 | v5.0 Compatibility Mapping |
|-------------|---------------------------|
| FETCH (Type 16) | `PUBLISH` to `$SYS/queues/{name}/fetch` |
| Batch Size (0x42) | `User Property: ("v6-batch", "{N}")` |
| Stream Sequence (0x30) | `User Property: ("v6-seq", "{N}")` |
| Stream Epoch (0x35) | `User Property: ("v6-epoch", "{N}")` |
| SQMC Mode Bits | `User Property: ("v6-semantics", "competing\|exclusive")` |
| Wait Timeout (0x36) | `User Property: ("v6-wait-ms", "{N}")` |

### 6.3 Broker Requirements for Compat Mode

A v5.0 broker with a v6.0 Extension Plugin MUST:

1. Intercept PUBLISH packets to `$SYS/queues/*/fetch` and trigger queue message release
2. Intercept SUBSCRIBE packets containing `v6-semantics` User Properties and apply SQMC logic
3. Inject `v6-seq` and `v6-epoch` User Properties into outgoing PUBLISH packets for `$queue/` topics
4. Maintain persistent storage for `$queue/` topics independent of session state

---

## 7. Security Considerations

All MQTT v5.0 security requirements (TLS, Enhanced Authentication, SASL/SCRAM) are retained and remain mandatory. The following subsections define normative security requirements introduced by v6.0.

### 7.1 Access Control for `$queue/` and `$SYS/queues/`

- **Normative:** Access to the `$queue/` namespace MUST be controlled by ACLs. Unauthorized publish or subscribe to `$queue/` topics MUST be rejected with Reason Code `0x87 (Not Authorized)`.
- **Normative:** Access to `$SYS/queues/*/fetch` control topics MUST be restricted to authenticated clients that have completed the v6.0 handshake.
- **Normative:** The Broker MUST NOT allow a client to create, subscribe to, or publish to a `$queue/` topic without first completing the v6.0 negotiation handshake (Section 3.1). Clients that have not negotiated v6.0 MUST be rejected with Reason Code `0x87 (Not Authorized)`.

### 7.2 Epoch Integrity

- **Normative:** The Broker MUST only increment the Stream Epoch under the conditions listed in Section 4.3.2.2 (Triggering Conditions). Sending an Epoch increment outside these conditions is a protocol violation.
- **Normative:** A spurious Epoch Reset causes all affected clients to discard idempotency state and resynchronize simultaneously. Implementations MUST treat unauthorized or unwarranted Epoch increments as a denial-of-service vector and SHOULD implement rate limiting (no more than N Epoch increments per queue per hour, where N is implementation-defined but SHOULD default to a conservative value such as 5).
- **Normative:** Epoch changes MUST be logged with timestamps, affected queue names, and triggering conditions for forensic auditing.

### 7.3 Sequence Number Side-Channel

- **Informative:** Stream Sequence Numbers are monotonically increasing and visible to all consumers of a queue. An observer who can read sequence numbers can infer the publication rate of the queue. Deployments where publication rate is sensitive information SHOULD restrict queue subscriptions via ACLs and SHOULD use TLS to prevent network-level observation.

### 7.4 High-Watermark Persistence

- **Normative:** A Client's High-Watermark (last processed sequence number) determines the resumption point on reconnect. If a Client's High-Watermark is tampered with (set to a value higher than actually processed), messages between the true and false watermark are silently skipped. Client implementations MUST persist the High-Watermark atomically with the business-logic processing of each message (Section 4.3.4).
- **Informative:** The Broker does not validate that a Client's reported `v6-last-seq` is truthful. A malicious client could report a false High-Watermark to skip messages. Deployments requiring tamper-proof watermark tracking SHOULD implement server-side watermark validation.

### 7.5 Transport Security — TLS 1.3 Requirement

**[NEW for v6.0]**

- **Normative:** A v6.0 Broker operating in Native Mode (Protocol Level 6) MUST support TLS 1.3 as defined in RFC 8446. A v6.0 Client in Native Mode MUST NOT negotiate TLS versions prior to TLS 1.3 with a v6.0 Broker.
- **Normative:** A v6.0 Broker MUST reject connections from clients that offer only TLS 1.2 or earlier cipher suites when operating in Native Mode. Reason Code `0x87 (Not Authorized)` is returned.
- **Normative:** The following TLS 1.3 cipher suites MUST be supported: `TLS_AES_256_GCM_SHA384`, `TLS_CHACHA20_POLY1305_SHA256`. Brokers MAY support additional cipher suites.
- **Informative:** TLS 1.3 eliminates the handshake round-trip latency of TLS 1.2 and removes vulnerable cipher suites (RC4, 3DES, CBC-mode AES without HMAC). For industrial deployments where both latency and auditability matter, TLS 1.3 is the appropriate floor.
- **Compatibility Note:** In Compatibility Mode (Protocol Level 5), TLS 1.3 is RECOMMENDED but NOT required. Existing v5.0 deployments may use TLS 1.2 during migration. Operators SHOULD establish a migration timeline when upgrading to Native Mode.

### 7.6 Optional Payload Encryption (Zero Trust)

**[NEW for v6.0 — OPTIONAL FEATURE]**

> **Note:** This feature is entirely optional. It is never required for protocol conformance. Deployments that rely on TLS 1.3 transport encryption alone (Section 7.5) are fully conformant. Payload encryption is provided for zero trust architectures where the broker must be treated as an untrusted intermediary.

#### 7.6.1 Motivation

In zero trust architectures, end-to-end confidentiality requires that the broker — even a trusted HiveMQ cluster — cannot read message payloads. TLS 1.3 secures the transport hop (client→broker, broker→subscriber) but terminates at the broker. Payload encryption extends confidentiality across the broker, making the broker a sealed transport for ciphertext it cannot inspect.

This matters specifically for `$queue/` topics carrying sensitive industrial payloads (SECS/GEM process recipes, financial transactions, regulated health or grid data) where the broker operator and the data owner are organizationally distinct.

#### 7.6.2 New Properties for Key Metadata

Three new optional properties carry encryption metadata on PUBLISH packets. These properties describe the encryption applied to the payload. They carry no key material — key distribution is an application-layer responsibility outside this specification.

| Property ID | Name | Type | Description |
|------------|------|------|-------------|
| `0x3A` | **Payload Key ID** | UTF-8 String | Opaque identifier for the symmetric key used to encrypt the payload. Consumers use this to look up the correct decryption key from their key management system. |
| `0x3B` | **Payload Algorithm** | Byte | Enum identifying the encryption algorithm. See Section 7.6.3. |
| `0x3C` | **Payload Key Version** | Two Byte Integer | Key rotation counter. Consumers can detect key rotation events without changing the Key ID. |

- **Normative:** Encryption properties (`0x3A`, `0x3B`, `0x3C`) MUST only appear on PUBLISH packets to `$queue/` topics carrying encrypted payloads. A PUBLISH to a non-`$queue/` topic carrying these properties is malformed. Brokers MAY reject such packets with Reason Code `0x8A (Invalid Argument)`.
- **Normative:** A Broker that receives a PUBLISH with encryption properties MUST forward them to subscribers unchanged. The Broker MUST NOT attempt to decrypt or re-encrypt payloads.

#### 7.6.3 Payload Algorithm Enum (Property `0x3B`)

| Value | Algorithm | Notes |
|-------|-----------|-------|
| `0x01` | AES-256-GCM | Recommended default; AEAD; authenticated encryption |
| `0x02` | ChaCha20-Poly1305 | Preferred for constrained clients without AES hardware acceleration |
| `0x03` | AES-128-GCM | Acceptable where bandwidth or compute is constrained |
| `0x7F` | Implementation-Defined | For private extensions; not interoperable across broker vendors |

#### 7.6.4 Nonce and Authentication Tag

When using an AEAD cipher (all standardized algorithms above), the encrypted payload format is:

```
[12-byte nonce][ciphertext][16-byte authentication tag]
```

The nonce MUST be unique per message. Implementations SHOULD derive the nonce by combining a random base with the Stream Sequence Number (`0x30`) to prevent nonce reuse across queue messages while remaining deterministic for deduplication.

#### 7.6.5 Key Management — Application Layer Boundary

Key distribution, key rotation procedures, key revocation, and certificate management are **application-layer responsibilities**. This specification defines only the metadata properties that identify which key and algorithm were used. How keys are exchanged, stored, and rotated is intentionally outside this specification.

> Refer to the MQTT Stream Application Profile (Option A in the Application Layer Lift documentation) for recommended key management patterns, including integration with SPIFFE/SPIRE for workload identity and HPKE for asymmetric key encapsulation.

#### 7.6.6 Broker Behavior for Encrypted Payloads

- **Normative:** A Broker MUST NOT reject a PUBLISH solely because it carries payload encryption properties (`0x3A`, `0x3B`, `0x3C`).
- **Normative:** A Broker MUST forward payload encryption properties to all matching subscribers unchanged.
- **Normative:** A Broker MUST NOT log, inspect, or cache the decrypted payload content. The broker is a sealed conduit for encrypted payloads.
- **Informative:** Because the broker cannot inspect encrypted payloads, content-based routing (topic-based filtering on payload content), stream processing plugins, and payload-aware QoS features are unavailable for encrypted `$queue/` messages. Topic design must carry all routing information in the topic string rather than in the payload.

#### 7.6.7 Interaction with Stream Sequence Numbers

Stream Sequence Numbers (`0x30`) are assigned to the encrypted payload as a whole. The sequence number does not depend on plaintext content. Gap detection, high-watermark tracking, and epoch resync operate identically whether the payload is encrypted or not — all sequence semantics are in the MQTT properties layer, not the payload.

#### 7.6.8 Backward Compatibility with MQTT v5.0 Clients

**Normative:** MQTT v5.0 clients MUST NOT be exposed to encrypted payloads on `$queue/` topics. The v6.0 handshake gate (Section 3.1) is the primary enforcement mechanism: a client that has not completed the `mqtt-ext: v6.0` negotiation MUST be rejected with Reason Code `0x87 (Not Authorized)` when attempting to SUBSCRIBE to any `$queue/` topic. Since v5.0 clients do not send the `mqtt-ext: v6.0` User Property in CONNECT, they cannot pass this gate and will never receive encrypted payloads.

**Informative:** In the event that a conformant MQTT v5.0 client inadvertently receives a PUBLISH packet carrying encryption properties (`0x3A`, `0x3B`, `0x3C`), the MQTT v5.0 specification mandates that the client silently ignore unknown property IDs. No protocol-level error or connection closure is triggered. Any failure is at the application layer (the client receives ciphertext it cannot interpret), not at the protocol layer. This provides a defense-in-depth guarantee: the handshake gate is the primary protection; the unknown-property rule is the fallback.

### 7.7 Threat Model

This section provides a formal threat model for MQTT v6.0. It identifies the actors, trust boundaries, threats addressed by this specification, and threats that are explicitly out of scope.

#### 7.7.1 Actors

| Actor | Description |
|-------|-------------|
| **Publisher** | A trusted endpoint that produces messages and publishes them to the broker. |
| **Subscriber** | A trusted endpoint that consumes messages delivered by the broker. |
| **Broker** | A semi-trusted router. The broker may be multi-tenant, cloud-hosted, or federated. It is trusted for routing, QoS, and session management, but is treated as an untrusted intermediary for payload content when payload encryption (Section 7.6) is in use. |
| **Network Adversary** | A party that can observe or intercept traffic at the transport layer between any two actors. |
| **Rogue Broker Administrator** | An internal threat — a party with administrative access to broker infrastructure who may attempt to read, modify, or replay message content. |

#### 7.7.2 Trust Boundaries

- **Publisher→Broker transport:** Secured by TLS 1.3 (Section 7.5). The network adversary cannot observe or tamper with this hop.
- **Broker→Subscriber transport:** Secured by TLS 1.3 (Section 7.5). The network adversary cannot observe or tamper with this hop.
- **Publisher→Subscriber end-to-end:** Secured by payload encryption (Section 7.6) when deployed. The broker receives and forwards ciphertext it cannot decrypt. This trust boundary holds even against the rogue broker administrator.
- **Broker as routing intermediary:** The broker is trusted to route, sequence, and deliver messages correctly. It is not trusted to maintain payload confidentiality when Section 7.6 encryption is not in use.

#### 7.7.3 Threats Addressed

| # | Threat | Mitigation |
|---|--------|-----------|
| 1 | **Network eavesdropping** — a network adversary intercepts the transport stream to read message content | Mitigated by TLS 1.3 (Section 7.5), which encrypts all traffic between client and broker |
| 2 | **Broker payload inspection** — the broker operator or a rogue administrator reads sensitive payload content | Mitigated by payload encryption (Section 7.6); the broker holds ciphertext and cannot recover plaintext without the application-layer key |
| 3 | **Message replay** — an adversary records and retransmits a previously delivered message | Mitigated by Stream Epoch (Section 4.3) combined with nonce uniqueness (Section 7.6.4); consumers reject messages whose sequence number falls at or below the High-Watermark, and the AEAD nonce prevents ciphertext reuse |
| 4 | **Message gap / loss detection** — messages are silently dropped between publisher and subscriber without detection | Mitigated by Stream Sequence Numbers (Section 4.3); consumers detect gaps by observing discontinuities in the monotonic sequence |
| 5 | **Broker message tampering** — the broker or a network adversary modifies payload content in transit | Mitigated by the AEAD authentication tag (Section 7.6.4); any modification to the ciphertext or associated data causes tag verification to fail at the subscriber |

#### 7.7.4 Threats Not Addressed (Out of Scope)

The following threats are explicitly outside the scope of this specification:

- **Key distribution and rotation:** The means by which publishers and subscribers obtain, exchange, rotate, and revoke symmetric keys is an application-layer responsibility. This specification defines only the metadata properties that identify which key was used (Section 7.6.5).
- **Broker ACL bypass:** Authorization enforcement — ensuring that a given client is permitted to publish or subscribe to a given topic — is the responsibility of the broker's authorization layer. This specification defines that ACLs MUST be enforced (Section 4.1.4, Section 7.1) but does not define the authorization mechanism.
- **Physical device compromise:** An adversary with physical access to a publisher or subscriber endpoint can extract keys or inject false messages at the application layer. This is outside the protocol threat model.
- **Denial of service at the broker tier:** Volumetric attacks, resource exhaustion, and distributed denial-of-service attacks against broker infrastructure are outside the scope of this specification. The Throughput Limit property (Section 2.2.3) provides per-client rate limiting but does not constitute a DoS defense.

#### 7.7.5 Forward Secrecy

**Informative:** TLS 1.3 provides forward secrecy at the transport layer via ephemeral key exchange. Compromise of a long-term TLS private key does not retroactively expose previously recorded transport traffic.

Payload encryption (Section 7.6) uses symmetric AEAD algorithms. Symmetric encryption does not inherently provide forward secrecy — if the symmetric key is compromised, all messages encrypted under that key are exposed. Forward secrecy at the payload layer requires key rotation: after rotating to a new key version (tracked by Property `0x3C`), messages encrypted under the old key remain at risk, but future messages are protected. Key rotation procedures are implementation-defined (Section 7.6.5).

---

### 7.8 QoS and Operational Interactions

This section addresses how payload encryption and v6.0 stream semantics interact with MQTT QoS levels and operational features including retained messages, broker bridging, and shared subscriptions.

#### 7.8.1 QoS 0, 1, and 2 Interactions

- **QoS 0 (at most once):** Payload encryption adds no overhead to QoS 0 flows beyond the encryption properties themselves. No PUBACK exchange occurs; encryption properties are included in the PUBLISH packet and delivered (or not) per normal QoS 0 semantics.
- **QoS 1 (at least once):** Encrypted payloads interact with PUBACK exactly as plaintext payloads do. The broker issues PUBACK after persisting the message to the queue; it does not inspect or validate the payload content. The PUBACK confirms persistence, not successful decryption.
- **QoS 2 (exactly once):** The PUBREC/PUBREL/PUBCOMP handshake is unaffected by payload encryption. The broker stores the encrypted payload and participates in the QoS 2 handshake without decrypting. The AEAD authentication tag is not validated by the broker; tag verification is performed by the subscriber after decryption.
- **Normative:** A Broker MUST NOT fail a QoS handshake (PUBACK, PUBREC, PUBREL, or PUBCOMP) on the basis of unrecognized payload content or the presence of payload encryption properties (`0x3A`, `0x3B`, `0x3C`).

#### 7.8.2 Retained Messages

- **Normative:** A Broker MAY store encrypted retained messages. The broker stores the ciphertext and encryption properties (`0x3A`, `0x3B`, `0x3C`) as-is, without inspection or modification.
- **Normative:** If the key identified by Payload Key ID (`0x3A`) is rotated after a retained message is stored, a subscriber that receives the retained message MUST use the Key Version (`0x3C`) to identify the correct decryption key. A retained message encrypted under a key version that has been revoked will remain undecryptable until the retained message is replaced by a new PUBLISH.
- **Informative:** Operators SHOULD carefully consider key rotation implications before using encrypted retained messages. A retained message encrypted with a revoked key will remain stored at the broker but will be unreadable by subscribers until the retained message is replaced with a freshly encrypted version.

#### 7.8.3 Broker Bridging

- **Normative:** When a broker bridge forwards a `$queue/` message to another broker, it MUST forward all PUBLISH properties unchanged, including payload encryption properties (`0x3A`, `0x3B`, `0x3C`).
- **Normative:** A bridging broker MUST NOT attempt to decrypt or re-encrypt forwarded payloads.
- **Normative:** Stream Sequence Numbers (`0x30`) MUST be preserved across broker bridges without modification. A bridge that rewrites sequence numbers breaks consumer gap detection and High-Watermark tracking on the downstream broker.

#### 7.8.4 Shared Subscriptions (non-SQMC)

- For standard `$share/` subscriptions carrying encrypted payloads, the broker distributes the encrypted payload to exactly one subscriber per the standard shared subscription rules (MQTT v5.0 Section 4.8.2). The selected subscriber decrypts using the key metadata properties included in the PUBLISH.
- **Normative:** All consumers in a shared subscription group accessing the same `$queue/` MUST have access to the same symmetric key, identified by Key ID (`0x3A`). Ensuring that all group members hold the correct key is an application-layer responsibility (Section 7.6.5).

#### 7.8.5 Observability and Debugging

- **Informative:** Payload encryption makes broker-side payload inspection, stream processing plugins, and content-based routing unavailable for encrypted messages. Operators SHOULD ensure that all routing information required for message delivery is expressed in the topic string, not in the payload, before enabling payload encryption.
- **Informative:** Observability tooling (Node-RED, broker management UIs, protocol analyzers) will display encrypted payloads as opaque binary blobs. This is by design — the security model requires that the broker be unable to read payload content. Debugging of encrypted message flows requires access to the application-layer decryption key and must be performed at the subscriber, not at the broker.

---

## Annex A: SECS/GEM Mapping

For semiconductor manufacturing environments using SECS/GEM (SEMI Equipment Communications Standard):

| SECS/GEM Concept | MQTT v6.0 Mapping |
|-----------------|-------------------|
| Transaction ID (TID) | Stream Sequence Number (0x30) |
| S1F13/S1F14 (Establish Comms) | CONNECT/CONNACK with v6.0 negotiation + Epoch check |
| S2F21 (Remote Start) | PUBLISH to `$queue/secsgem/{device_id}/S2F21` with `v6-semantics: exclusive` |
| S6Fx (Event Reports / FDC) | PUBLISH to `$queue/secsgem/{device_id}/events` + Virtual FETCH for backpressure |
| Multi-block messages | Segmented PUBLISH with sequence continuation; reassembled via Batch Size |
| Link Test (Heartbeat) | FETCH with `Wait Timeout` as a "proof of life" pull |
| Equipment Model Reset | Epoch Reset → Client performs S1F13 re-establishment |

### A.1 Critical Scenario: Process Start Command (S2F21)

In SECS/GEM, S2F21 (Remote Start) is mission-critical. Loss of this command can ruin a wafer.

**Without v6.0:** If broker Node A crashes after accepting S2F21 but before delivery, the command may be silently lost.

**With v6.0:**
1. Host publishes S2F21 with `Sequence: 5001, Epoch: 1` to `$queue/secsgem/tool_001/S2F21`
2. Broker Node A persists to non-volatile storage and assigns Seq 5001
3. Node A crashes; its replica is gone but the sequence counter and message data survive in other nodes' replicated storage
4. Tool reconnects with `v6-last-seq: 5000` in CONNECT
5. Node B checks persistent queue: Seq 5001 exists and was never acknowledged
6. Node B resumes delivery: tool receives S2F21 exactly once

---

## Annex B: New Reason Codes

| Code | Name | Description |
|------|------|-------------|
| `0xA0` | Epoch Reset | Cluster failover caused sequence discontinuity; client must reset idempotency state |
| `0x9B` | Quota Exceeded | Client exceeded Throughput Limit |
| `0x8D` | Queue Full | Queue storage limit reached; message rejected |
