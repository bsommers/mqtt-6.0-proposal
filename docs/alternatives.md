# Alternative Approaches to MQTT v6.0

This document explores the design alternatives considered during the development of MQTT v6.0, explains the trade-offs, and justifies the chosen approach.

---

## 1. The Core Design Choice: Breaking vs. Non-Breaking

The central tension in extending MQTT is between **expressiveness** and **compatibility**. Every proposed feature was evaluated on a spectrum:

```
[Pure v5.0 Extension] ←————————————————————→ [New Protocol Version]
   (User Properties)      (New Properties)      (New Packet Types)
      No breaks               Safe                  Breaking
```

---

## 2. Alternative A: Pure MQTT v5.0 Extension (Property-Based Shim)

### Description
All v6.0 features encoded entirely as `User Properties` within existing v5.0 packets. No new property IDs, no new packet types.

### Implementation
- Sequence numbers as `User Property: ("v6-seq", "12345")`
- Epoch as `User Property: ("v6-epoch", "2")`
- FETCH as `PUBLISH` to `$SYS/queues/{name}/fetch` with `User Property: ("v6-batch", "100")`
- Consumer modes as `User Property: ("v6-semantics", "competing")`

### Pros
- **Zero compatibility risk.** Works on any MQTT v5.0 broker, any client library, today.
- **No broker changes required.** Logic lives entirely in a HiveMQ Extension Plugin.
- **Fastest time to production.** Can be deployed as a library/plugin without protocol changes.

### Cons
- **Not standardizable.** User properties are opaque strings — no binary parser optimization is possible. This is a permanent workaround, not a standard.
- **Parsing overhead.** Sequence numbers as strings ("4294967295") cost 10 bytes; as 4-byte integers they cost 4 bytes + 1 ID byte = 5 bytes.
- **No protocol-level enforcement.** A broker cannot distinguish a v6.0 sequence-aware publish from a regular publish at the binary level without inspecting all user properties.
- **No `FETCH` semantics at the broker level.** The broker cannot natively throttle push delivery; it requires application-level hacks.

### The Fragmentation Risk

Shipping these features as vendor-specific User Property conventions (without standardization) creates the exact problem standardization prevents. If HiveMQ uses `v6-seq`, EMQX uses `x-seq-number`, and AWS IoT Core uses `aws-sequence`, every customer running multiple brokers needs a translation layer. This is how `$SYS/` became fragmented across brokers — every vendor implemented it differently, and 15 years later there is still no standard. Standardizing the wire representation early prevents this.

### Verdict
**Viable as a transitional shim.** Adopted as the Compatibility Layer (Track B). Not suitable as the long-term specification because it prevents standardization and invites vendor fragmentation.

---

## 3. Alternative B: MQTT v5.0 with Reserved Property IDs (0x30–0x45)

### Description
Use the unused/reserved property ID space (`0x30`–`0x45`) to define new typed properties. No new packet types. Protocol Level remains 5.

### Implementation
- `0x30`: Stream Sequence Number (Four Byte Integer)
- `0x35`: Stream Epoch (Two Byte Integer)
- `0x41`: Throughput Limit (Four Byte Integer)
- `0x42`: Batch Size (Four Byte Integer)
- FETCH still implemented as Virtual FETCH (control topic publish)

### Pros
- **Binary-efficient.** Fixed-width integers instead of string user properties.
- **Backward-compatible in practice.** MQTT v5.0 mandates that unknown Property IDs MUST be silently ignored by non-v6 clients and brokers. However, these IDs are not formally reserved for v6.0 until an OASIS submission is accepted — there is a pre-standardization window where a future v5.x revision could theoretically assign different semantics to the same IDs.
- **Minimal parser changes.** Any existing MQTT parser that follows the spec will skip unrecognized properties safely.
- **Works without Protocol Level change.** Mixed v5.0/v6.0 deployments are seamless.

### Cons
- **No native FETCH.** Without a new packet type, pull semantics must still be simulated through control topics, adding round-trip overhead.
- **Subscription option bits still blocked.** MQTT v5.0 mandates bits 6-7 of the SUBSCRIBE options byte MUST be zero; exclusive/competing modes cannot be encoded natively in the packet — only in user properties.
- **Protocol-level ambiguity.** A "Protocol Level 5 client with v6 properties" is technically a v5.0 client; there is no way to formally signal v6.0 conformance without a new level.

### Verdict
**Adopted as the Compatibility Extension profile.** This is what Track B uses. The reserved property IDs are the right mechanism; the missing piece is the FETCH packet.

---

## 4. Alternative C: Native v6.0 with New Packet Type (Chosen Approach)

### Description
Full protocol version bump to Level 6. Introduces FETCH as Control Packet Type 16 — previously reserved in v5.0. New subscription option bits for SQMC modes.

### Implementation
- Protocol Level `6` in CONNECT
- `FETCH` packet (Type 16) as a first-class pull mechanism
- Properties `0x30`, `0x35`, `0x41`, `0x42` as typed binary fields
- SUBSCRIBE options bits 6-7 used for Competing/Exclusive flags
- `$queue/` namespace with mandatory persistence semantics

### Pros
- **Full expressiveness.** Every v6.0 feature has a dedicated, binary-efficient representation.
- **Broker-level enforcement.** A v6.0 broker can natively identify `$queue/` publishes, FETCH requests, and SQMC subscriptions at the parser level without inspecting application data.
- **Formal standardizability.** A clean Protocol Level 6 specification can be submitted to OASIS as a distinct standard.
- **Performance.** FETCH as a dedicated packet eliminates the round-trip overhead of the "publish to a control topic" pattern.

### Cons
- **Breaking change for v5.0 brokers.** A strict v5.0 broker closes the connection immediately upon receiving a Type 16 packet.
- **Breaking change for subscription bits.** A v5.0 broker rejects SUBSCRIBE packets with non-zero reserved bits.
- **Requires ecosystem update.** Client libraries (paho, gmqtt, Eclipse Mosquitto) must be updated to support Level 6.
- **Deployment risk.** Mixed v5.0/v6.0 environments require the Compatibility Layer.

### The Dual-Mechanism Trade-Off

Having two mechanisms for the same operation (native FETCH and Virtual FETCH) creates a testing and conformance burden. The specification requires **semantic equivalence** (see spec Section 4.2.3): both mechanisms MUST produce identical observable behavior for any given queue state. A conformant implementation MUST pass the same test suite for both. This trade-off is accepted because the alternative — requiring Protocol Level 6 everywhere — would prevent incremental adoption.

### Verdict
**Chosen as the canonical v6.0 specification.** The breaking changes are manageable with the Compatibility Layer (Alternative B) and negotiation handshake. The long-term correctness of a formal protocol is worth the transition cost.

---

## 5. Alternative D: Replace MQTT Entirely (Kafka / AMQP 1.0 / NATS JetStream)

### Description
Instead of extending MQTT, adopt a different messaging protocol that already provides the required industrial features.

### Comparison

| Feature | MQTT v6.0 | Apache Kafka | AMQP 1.0 | NATS JetStream |
|---------|-----------|-------------|---------|----------------|
| Lightweight clients | Yes | No | Partial | Yes |
| Edge/IoT footprint | Excellent | Poor | Moderate | Good |
| Named durable queues | Yes (v6.0) | Yes (Topics) | Yes | Yes |
| Pull-based consumption | Yes (FETCH) | Yes (Poll API) | Yes | Yes |
| 32-bit+ sequencing | Yes (v6.0) | Yes (Offset) | No native | Yes |
| Cluster consistency | Epoch-based | ISR/Leader | Partition leader | Raft consensus |
| Existing MQTT ecosystem | Full compatibility | None | Partial bridge | None |
| SECS/GEM mapping | Native | Requires adapter | Requires adapter | Requires adapter |
| Standard body | OASIS | Apache/Confluent | AMQP WG | CNCF |

### Analysis
Kafka provides everything v6.0 proposes, but:
- Kafka clients are heavyweight (JVM, 50MB+). Not viable for edge devices or microcontrollers.
- The existing investment in MQTT infrastructure (broker, client libraries, security tooling) is significant.
- SECS/GEM integration with non-MQTT protocols requires a translation adapter, introducing latency and another failure point.
- NATS JetStream is compelling for cloud-native workloads but lacks the industrial IoT ecosystem MQTT has built.

### Verdict
**Not adopted.** The v6.0 extensions preserve the edge/IoT deployment model of MQTT while adding the industrial reliability features. Replacing MQTT would abandon its core advantage in constrained environments.

---

## 6. Alternative E: Extend MQTT Shared Subscriptions (v5.0 `$share/`)

### Description
Enhance the existing MQTT v5.0 [`$share/group/topic`](https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html#_Toc3901250) mechanism to add message locking, exclusive consumer semantics, and failover logic — without changing the core protocol.

### Pros
- Uses an existing, widely-supported mechanism
- No new packet types or property IDs required
- Implementable today as a broker plugin

### Cons
- `$share/` groups are still session-dependent — the queue vanishes when the last client disconnects. [Shared subscriptions distribute messages to active subscribers](https://www.hivemq.com/blog/mqtt5-essentials-part7-shared-subscriptions/); they do not buffer messages when no subscriber is connected.
- No way to add explicit sequencing or gap detection within the `$share/` spec — there is no per-message identity that survives across sessions
- No standardized way to express "exclusive" (hot-standby) mode in the subscription syntax
- Consumer failover behavior (what happens when a consumer disconnects mid-processing) is [implementation-defined, not standardized](https://www.hivemq.com/docs/hivemq/4.13/user-guide/shared-subscriptions.html)
- Extending `$share/` syntax creates a non-standard variation that other broker implementations won't support
- Message ordering within a shared subscription group is not guaranteed by the spec

### Why `$share/` Is Not a Durable Queue

This is the most common misconception. `$share/` and `$queue/` solve fundamentally different problems:

| Property | `$share/` (v5.0) | `$queue/` (v6.0) |
|----------|:-:|:-:|
| Survives all consumers disconnecting | No | Yes |
| Survives broker restart (spec-mandated) | No | Yes |
| Message ordering guarantee | No | Yes |
| Gap detection | Impossible | Built-in |
| Named, inspectable entity | No | Yes |

A shared subscription is a **delivery optimization for active subscribers**. A named queue is a **persistent message store**. See [Addressing Criticisms](rebuttals.md#section-21-thats-a-shared-subscription) for full analysis.

### Verdict
**Partially adopted.** The conceptual model of consumer groups and competing delivery from `$share/` inspired the SQMC design. But v6.0 requires named queue persistence and sequencing that `$share/` fundamentally cannot provide without a new namespace.

---

## 7. Design Decision Matrix

| Criterion | Pure User Props | Reserved Props (0x30+) | Native v6.0 | Kafka/NATS | $share/ Ext |
|-----------|:--------------:|:---------------------:|:-----------:|:----------:|:-----------:|
| v5.0 Wire Compat | ✅ Full | ✅ Full | ⚠️ Breaking | ❌ None | ✅ Full |
| Binary Efficiency | ❌ Poor | ✅ Good | ✅ Best | ✅ Best | ✅ Good |
| Native FETCH | ❌ No | ❌ No | ✅ Yes | ✅ Yes | ❌ No |
| Standardizable | ❌ No | ⚠️ Partial | ✅ Yes | ✅ Yes | ❌ No |
| Edge/IoT Viable | ✅ Yes | ✅ Yes | ✅ Yes | ❌ No | ✅ Yes |
| SQMC Enforcement | ❌ App-layer | ⚠️ Partial | ✅ Protocol | ✅ Protocol | ⚠️ Partial |
| Queue Persistence | ❌ Plugin only | ⚠️ Plugin only | ✅ Spec-mandated | ✅ Spec-mandated | ❌ No |
| Time to Deploy | ✅ Immediate | ✅ Immediate | ⚠️ Ecosystem update | ❌ Full migration | ✅ Immediate |

**Recommendation:** Native v6.0 for new deployments with a full MQTT v6.0 ecosystem. Compatibility Layer (Reserved Props) for transitional deployments. Pure User Props shim for proof-of-concept and testing only.
