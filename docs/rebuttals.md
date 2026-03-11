# MQTT v6.0 — Addressing Criticisms and Defending the Proposal

> **Author:** Bill Sommers, AI Solutions Lead, HiveMQ, Inc.
> **Context:** Response to internal review feedback from Georg and Simon — March 2026

---

## A Note on Where This Comes From

Before I get into the point-by-point responses, I want to be clear about what drives this proposal: **two and a half years as a TAM in Customer Success at HiveMQ.**

I have spent that time on calls with customers who are building exactly the systems this proposal targets — semiconductor fabs running [SECS/GEM](https://en.wikipedia.org/wiki/SECS/GEM) over MQTT, energy providers pushing [IEC 61850](https://en.wikipedia.org/wiki/IEC_61850) telemetry through HiveMQ clusters, automotive OEMs streaming diagnostic data from factory floors. These are not hypothetical use cases. These are customers I have worked with directly, and the pain points in this proposal are patterns I have seen repeated across multiple engagements.

The common thread: **every one of these customers has built the same set of application-layer workarounds on top of MQTT v5.0.** Sequence numbers in payloads. Idempotency tables in Redis. Consumer group coordination in custom microservices. Checkpoint reconciliation jobs that run after every broker restart. And every one of them has asked some version of the same question: *"Why doesn't the broker just do this?"*

[Eclipse Sparkplug B](https://sparkplug.eclipse.org/specification/) is the most visible proof that this need is real — it defines [application-layer sequencing on top of MQTT](https://sparkplug.eclipse.org/specification/version/2.2/documents/sparkplug-specification-2.2.pdf) (64-bit `seq` fields in protobuf payloads, birth/death certificates, state management) precisely because MQTT v5.0 does not provide these primitives natively. Sparkplug exists because MQTT has a gap. v6.0 proposes to close that gap at the protocol level.

I am not proposing that MQTT become Kafka. I am not proposing a general-purpose upgrade. I am proposing that we acknowledge what our customers are already building on top of MQTT and give them proper protocol-level tools instead of forcing them to reinvent the same workarounds in every deployment.

### Why Standardize Now — Not "Ship an Extension First"

The most reasonable pushback I have heard is: *"Ship these features as a HiveMQ extension. Let the market validate them. Come back to OASIS in five years with production data."*

This sounds prudent, but it leads to **fragmentation, not validation.** If HiveMQ ships `$queue/`, FETCH, and SQMC as a proprietary extension, here is what happens next:

- **EMQX builds their own version** — similar semantics, different User Property names, different control topic paths, different consumer group behavior
- **Mosquitto community builds a plugin** — subset of features, incompatible wire format
- **AWS IoT Core adds "durable queues"** — completely proprietary, no interop with any of the above
- **Every customer running two brokers** (common in industrial — edge broker + cloud broker) now needs a translation layer between competing proprietary implementations

This is exactly what happened with `$SYS/` — every broker implemented it differently, there is no standard, and it remains a mess 15 years later. It is what happened with shared subscription behavior before v5.0 partially standardized it — and even now the spec leaves enough implementation-defined gaps that HiveMQ had to build [Declared Shared Subscriptions](https://docs.hivemq.com/hivemq/latest/user-guide/declared-shared-subscriptions.html) as a proprietary workaround.

**The extension-first path does not lead to standardization — it leads to vendor lock-in dressed up as innovation.** Once three vendors have incompatible implementations in production with paying customers depending on them, the OASIS committee has to reconcile three designs instead of evaluating one proposal. That is how standards processes stall for years.

The patterns are already validated. Sparkplug proves application-layer sequencing works. HiveMQ's Declared Shared Subscriptions prove durable queue semantics are needed. Every customer I have worked with who runs an MQTT-to-Kafka bridge proves pull-based consumption is needed. What is missing is not proof of concept — it is a **standard wire representation** that lets a Paho client library work with a HiveMQ broker, an EMQX broker, or any future broker without vendor-specific payload conventions.

**Standardizing early — before fragmentation — is cheaper than standardizing late.**

---

## What This Proposal Is Not

**This is not "MQTT trying to become Kafka."** Every time I present this to an engineer, that is the first reaction. I understand why — the feature list (durable queues, pull-based fetch, sequence numbers, consumer groups) reads like a Kafka feature sheet. But the context is completely different.

**Kafka is not viable at the edge.** Its minimum client footprint requires a [full JVM stack with multi-GB RAM](https://docs.confluent.io/platform/current/installation/system-requirements.html). Our customers have thousands of devices — PLCs, RTUs, smart meters, semiconductor tools — running constrained firmware with MQTT baked in. These devices will be in service for 15–25 years. They cannot be reflashed with Kafka client libraries. [AMQP 1.0 is similarly impractical](https://www.hivemq.com/blog/mqtt-vs-amqp-for-iot/) for constrained environments.

The architecture our customers run today looks like this:

```
[Edge Device — MQTT v5.0] → [HiveMQ Broker] → [Kafka Bridge] → [Kafka] → [Consumer]
```

That bridge is a second system, a second failure domain, a second protocol stack, and a second team. Every customer I have worked with who runs this architecture has told me they would eliminate the bridge if they could. v6.0 eliminates it:

```
[Edge Device — MQTT v5.0] → [HiveMQ v6.0 Broker — native queuing] → [Consumer via FETCH]
```

The edge devices do not change. The edge protocol does not change. The consumer gets Kafka-like semantics (ordered, durable, pull-based) without a second messaging system. If Kafka could run on a PLC, this proposal would not exist.

**What Kafka does that v6.0 explicitly does not attempt:**
- Multi-day log retention with consumer offset replay
- Stream processing or CEP (Kafka Streams, ksqlDB)
- Server-to-server batch processing at data centre scale
- Schema registry or schema evolution
- Topic compaction

v6.0 adds exactly five things to MQTT. No more.

---

## "MQTT v5.0 Already Does This" — Point-by-Point

### Section 2.1: "That's a Shared Subscription"

**Georg's criticism:** Durable, session-independent queues are not needed because MQTT v5.0 Shared Subscriptions (`$share/group/topic`) already provide this.

**Simon's criticism:** "The protocol does not concern itself with broker nodes — that's the implementation."

**I went back to the spec to make sure I was not overstating the gap. The gap is actually larger than I originally described.**

The [MQTT v5.0 OASIS Standard](https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html) defines shared subscriptions in [Section 4.8](https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html#_Toc3901250). Here is what the spec actually says — and critically, what it does not say:

**1. Shared subscriptions do not buffer messages when no subscriber is connected.**

The spec defines shared subscriptions as a mechanism to distribute messages across "subscribing Sessions." When no session is subscribed, the spec is silent — there is no normative requirement to buffer messages for the group. Messages published to a topic matched by a shared subscription with zero active sessions are not guaranteed to be held. This is not a durable queue — it is a fan-out optimization for active subscribers.

HiveMQ actually recognized this gap and built a proprietary feature called [Declared Shared Subscriptions](https://docs.hivemq.com/hivemq/latest/user-guide/declared-shared-subscriptions.html) — pre-configured shared subscriptions that enqueue messages even when no subscriber is connected. **The fact that HiveMQ had to build a non-standard extension to get this behavior is itself evidence that `$share/` does not provide durable queue semantics.**

**2. The spec explicitly prohibits re-routing unacknowledged messages to another consumer.**

This is the one that matters most for industrial use cases. [Section 4.8.2, normative requirement `[MQTT-4.8.2-5]`](https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html#_Toc3901250) states:

> *"If the Client's Session terminates before the Client reconnects, the Server MUST NOT send the Application Message to any other subscribed Client."*

Read that again. If a consumer in a `$share/` group receives a QoS 1 message, disconnects before sending PUBACK, and its session expires — **the message is lost.** The spec explicitly prohibits the broker from re-delivering it to another consumer in the group. The message is discarded.

In a traditional competing-consumer queue (AMQP, JMS, Kafka consumer groups), an unacknowledged message is returned to the queue and re-dispatched to another consumer. In MQTT v5.0 shared subscriptions, it is **destroyed.** This is not a competing-consumer queue. It is a load balancer with a data loss failure mode.

I have seen this exact scenario in customer deployments. A consumer crashes mid-processing during a fault storm — exactly when message integrity matters most — and the in-flight messages are silently lost because the session expired before the consumer could reconnect.

**3. Message ordering is explicitly NOT guaranteed for shared subscriptions.**

The spec's ordering guarantee in [Section 4.6, `[MQTT-4.6.0-6]`](https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html#_Toc3901242) is scoped to *"Non-shared Subscriptions"* only. For shared subscriptions, ordering across consumers in the group is implementation-defined. [HiveMQ's own documentation confirms this](https://www.hivemq.com/blog/mqtt5-essentials-part7-shared-subscriptions/): *"you gain horizontal scalability and high availability at the cost of per-client message ordering."*

**The full comparison:**

| Property | `$share/` (MQTT v5.0 Spec) | `$queue/` (v6.0 Proposal) |
|----------|:-:|:-:|
| **Messages buffered when no subscriber exists** | Not guaranteed — spec is silent; implementation-defined | Yes — queue persists independently of sessions |
| **Survives broker restart (spec-mandated)** | No — persistence of shared sub state is implementation-defined | Yes — persistence to non-volatile storage required before PUBACK |
| **Unacked message re-routed on consumer failure** | **No — `[MQTT-4.8.2-5]` explicitly prohibits this.** Message is discarded if session terminates. | Yes — message lock released immediately; re-dispatched to next consumer |
| **Message ordering guarantee** | No — `[MQTT-4.6.0-6]` scopes ordering to non-shared subs only | Yes — strict ascending order by Stream Sequence Number |
| **Gap detection** | Impossible — no per-message identity | Built-in — Seq gaps are detectable |
| **Named, inspectable entity** | No — `$share/` is a subscription pattern | Yes — `$queue/` is a first-class entity with TTL, max-size, storage policy |

**The bottom line:** `$share/` is a delivery optimization for active subscribers. `$queue/` is a named, durable, persistent message store. They solve different problems. Saying "`$share/` already does this" is like saying "TCP already provides reliable delivery, so we don't need a database." The reliability primitives operate at different levels and serve different purposes.

To Simon's point about the protocol not concerning itself with broker nodes — I agree. And the `$queue/` proposal does not dictate broker architecture. It defines a **client-facing contract**: messages published to `$queue/` topics MUST be persisted before acknowledgment and MUST be delivered in order with gap detection. How the broker achieves this internally is implementation-defined, just as how a broker persists session state today is implementation-defined. The difference is that `$queue/` makes the durability guarantee **normative** rather than optional.

---

### Section 2.2: Packet Identifiers and Message Ordering

**Simon's criticism:** "Packet identifiers are session scoped and not intended for ordering. They are also eligible for reuse within a session. Why would we want to increase the size of session packets by 2 bytes for arbitrary ID space? In what scenario would a client have >65535 packets inflight?"

**Simon is correct on every factual point here, and I want to be clear that the proposal does not conflict with any of them.**

We are **not** proposing to enlarge the Packet Identifier. The 16-bit Packet ID remains exactly as specified in [Section 2.2.1](https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html#_Toc3901026). It continues to serve its original purpose: correlating QoS 1/2 acknowledgments within a single session.

The Stream Sequence Number (`0x30`) is a **separate, additional property** — a new field with a completely different purpose. The confusion is understandable because the original proposal document jumped into wire format details before clearly explaining why a new field is needed. That is my fault — Simon's "too much HOW, not enough WHY" feedback is well taken.

Here is the WHY:

| | Packet Identifier (v5.0) | Stream Sequence Number (v6.0) |
|--|:-:|:-:|
| **What it answers** | "Has this specific QoS handshake completed?" | "Where is this message in the queue's total history?" |
| **Scope** | Per-session, per-connection | Per-queue, cluster-wide, permanent |
| **Assigned by** | Client or broker | Broker only |
| **Recycled?** | Yes — reused after PUBACK/PUBCOMP | Never — monotonically increasing |
| **Survives reconnection?** | No | Yes — persisted across sessions and broker restarts |
| **Purpose** | QoS ack correlation | Ordering, gap detection, exactly-once deduplication, resume-from-position |

The question "when would a client have >65535 packets inflight?" is exactly the right question for Packet Identifiers — and the answer is "never in practice, so 16 bits is fine." But that is the wrong question for Stream Sequences. A queue processing 1,000 messages/second exhausts 65,535 values in 65 seconds. The sequence number represents **total message identity across the lifetime of a queue**, not in-flight count.

The overhead: 5 bytes per `$queue/` PUBLISH (1-byte property ID + 4-byte value). Zero bytes for non-queue topics. Standard pub/sub (`temperature/office`) is completely unaffected.

Both reviewers acknowledge that 2.2 (message ordering across sessions) is a valid gap. The Stream Sequence Number is the mechanism that fills it — without touching the Packet Identifier.

---

### Section 2.3: "Receive Maximum Already Provides Flow Control"

**Georg's criticism:** MQTT v5.0's [`Receive Maximum`](https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html#_Toc3901049) plus the frequency of client acknowledgments already provides flow control.

**`Receive Maximum` is a window size limiter, not a pull mechanism.** It caps the number of QoS 1/2 messages the broker can have in-flight simultaneously. The broker still pushes — it just pushes in a bounded window.

Here is the distinction that matters in practice:

| | `Receive Maximum` (v5.0) | FETCH (v6.0) |
|--|:-:|:-:|
| **Consumer controls *when* to receive** | No — the broker pushes as soon as an ack frees a slot | Yes — consumer issues FETCH when ready. No FETCH = no messages. |
| **Consumer can pause entirely** | Only by disconnecting or withholding acks (both destructive) | Yes — stop issuing FETCH. Messages stay in the queue. |
| **Prevents flood on reconnect** | No — broker immediately pushes up to `Receive Maximum` from backlog | Yes — consumer fetches at its own pace |

**What I have seen in the field:** The "slow consumer death spiral" is one of the most common support issues I dealt with as a TAM. A SCADA historian writing to a database at 10ms per message sets `Receive Maximum = 50`. The broker pushes 50 messages. The historian processes them at 100 msg/sec. But the queue has 500,000 msg/sec incoming. The broker pushes 50 more as each ack arrives. The historian falls further and further behind. Its memory fills. It crashes. It reconnects. The broker immediately pushes another 50 from the now-massive backlog. The historian crashes again.

The customer's workaround: disconnect the historian, let messages pile up in broker session queues, reconnect during a maintenance window and drain slowly. This is operational toil masquerading as flow control.

`Receive Maximum` plus ack pacing can slow down the push rate, but the consumer cannot tell the broker "I am in a maintenance window, hold everything until I come back and ask for it." FETCH can.

FETCH is not a replacement for `Receive Maximum`. Both serve valid purposes. `Receive Maximum` is fine for live pub/sub where you want bounded push delivery. FETCH is for queue consumption where the consumer needs absolute control over when and how much it receives.

---

### Section 2.4: "Cluster-Aware Sequence Numbers" — On the Epoch

**Georg's criticism:** "This is plainly wrong."

**Simon's criticism:** "The protocol does not concern itself with broker nodes — that's the implementation."

I want to address these together because I think the confusion is partly my fault. The original proposal described the Epoch in terms of cluster architecture (node failover, quorum loss, partition events). That framing made it sound like the protocol is prescribing implementation details. It is not.

**The Epoch is not an implementation detail. It is a piece of protocol-level information that the client needs and can act on.**

Here is what the Epoch actually is, stripped of all implementation language:

> **Stream Epoch (`0x35`):** A value carried in CONNACK and PUBLISH packets that tells the client whether the broker's message state is continuous with what the client last saw.
>
> - **Same Epoch as client's stored value:** The broker guarantees that all sequence numbers between the client's last-seen Seq and the current Seq are accounted for. The client can trust its local high-watermark and resume processing.
> - **Different Epoch from client's stored value:** The broker **cannot** guarantee sequence continuity. Something happened — the broker does not tell the client what — that may have caused messages to be lost, reordered, or duplicated. The client MUST discard its local idempotency state and resynchronize.

That is the entire client-facing contract. The protocol does not say "because a cluster node failed" or "because a partition occurred." It says: **"the broker's state may have changed in a way that breaks sequence continuity, and here is how the client knows."**

This is analogous to how MQTT v5.0 handles session state today. When a client reconnects with `cleanStart=false`, the broker tells the client (via the Session Present flag in CONNACK) whether the session exists. The protocol does not dictate *how* the broker persists sessions — it just provides a client-visible signal. The Epoch extends this pattern: it tells the client whether the **queue's sequence state** is continuous, not just whether the session exists.

**Why this matters — from customer experience:**

The most common post-incident question I have heard from customers after a broker restart is: *"Did we lose any messages?"* Today, the honest answer is: "We don't know. The protocol doesn't tell you. You have to reconcile your application-level records against the broker's stored sessions and hope nothing fell through the cracks."

With the Epoch, the answer becomes: "If the Epoch is the same, no. If the Epoch changed, potentially yes — and here is exactly where to start your reconciliation." That is a massive improvement for incident response.

**A single-node broker benefits from this too.** If a standalone HiveMQ instance restarts and loses its in-memory queue state (but retains persisted data), it can increment the Epoch to signal to reconnecting clients that some messages may have been lost during the restart window. No cluster, no nodes, no quorum — just a simple "my state changed, here's your signal." The mechanism is topology-agnostic.

**What operators build today without the Epoch:**

Every customer I have worked with who cares about message continuity has built some version of this in application code:
- Sequence numbers embedded in message payloads
- Checkpoint tables in external databases (Redis, PostgreSQL)
- Post-restart reconciliation jobs that compare producer records against consumer records
- Manual "state reset" procedures that operators execute after broker incidents

The Epoch standardizes this signal at the protocol level. The client library handles it. The application developer does not have to build a reconciliation framework from scratch for every deployment.

---

### Section 2.5: Shared Subscription Semantics — Exclusive Consumer / Hot Standby

**Both reviewers acknowledge this is a valid gap.** MQTT v5.0 does not provide exclusive consumer (hot-standby) semantics. The SQMC exclusive mode in v6.0 addresses a real need — particularly for safety-critical command streams (SECS/GEM S2F21, grid protection relay commands) where strict ordering with automatic failover is non-negotiable.

---

## "This Should Be Handled at the Application Level"

Simon raises this directly: *"There appears to be a mux'ing of what is expected of the application and what is expected of the protocol."*

This is the right question to ask. Every feature in v6.0 **can** be implemented at the application layer. Sequence numbers, gap detection, exactly-once dedup, pull-based flow control, consumer group management — all of it. This is how it is done today.

**But having spent 2.5 years watching customers do exactly this, I can tell you it does not work well in practice.**

### What I Have Seen in Customer Deployments

**1. Every customer reinvents the same wheel, differently.**

I have worked with semiconductor, energy, and automotive customers who all independently built application-layer sequencing on top of MQTT. None of their implementations are compatible. One uses JSON `{"seq": N}`, another uses protobuf with a `sequence_number` field, another uses a custom binary header. Every integration between these systems requires a translation layer that maps one sequence scheme to another. This is the N-squared problem in practice — 50 publishers and 20 consumers means 1,000 pairwise schema agreements, none standardized.

**2. Application-layer reliability has a correctness problem.**

The most common failure mode I have seen is not "the sequence number system doesn't work" — it is "the developer forgot to check the sequence number." Application-layer deduplication requires every consumer to correctly implement sequence validation. In a system with 20 consumers written by 5 different teams over 3 years, at least one of them will have a bug in its dedup logic. I have seen this cause duplicate processing of safety-critical commands — exactly the scenario this proposal is designed to prevent.

When the broker assigns the sequence and the client library handles dedup, the application developer cannot forget. The reliability primitive is in the infrastructure, not in the application code.

**3. The broker cannot optimize what it cannot see.**

When sequence numbers are in the payload, the broker is a dumb pipe. It cannot detect gaps, enforce ordering, perform dedup, resume delivery from a position, or track consumer group progress. These are all things the broker *should* be doing — and things our customers ask us why HiveMQ doesn't do.

**4. Sparkplug proves the pattern.**

[Eclipse Sparkplug B](https://sparkplug.eclipse.org/specification/) already defines application-layer sequencing on MQTT. It proves the need is real and the industry has converged on a common pattern. v6.0 proposes to move that pattern from the payload into the protocol — exactly as MQTT v5.0 moved message expiry, request/response correlation, and shared subscriptions from application-layer conventions into protocol properties.

**5. The extension-first path leads to fragmentation, not validation.**

If we tell customers "build it in your application" or "use a vendor extension," every vendor and every customer builds their own version. We end up with a dozen incompatible implementations of the same five patterns. Standardizing at the protocol level — before fragmentation — gives the ecosystem a single wire representation that every client library and every broker can implement. This is the same argument I made above in [Why Standardize Now](#why-standardize-now--not-ship-an-extension-first): the `$SYS/` fragmentation and HiveMQ's proprietary Declared Shared Subscriptions are proof that the extension-first path does not converge on interoperability.

### The Historical Precedent

MQTT v3.1.1 had no concept of message expiry, request/response correlation, or shared subscriptions. All were implementable at the application layer. MQTT v5.0 moved them into the protocol because the industry had converged on common patterns that benefited from standardization. The same trajectory applies here.

---

## "Do You Think MQTT Should Be a Message Queue?"

Simon asks: *"I think you hit the nail on the head when you said: 'It was not designed to be a message queue.' My question to you would be, do you think it should be? In which case, why not Kafka?"*

### My Direct Answer

**No, MQTT should not become a general-purpose message queue.** It should remain a lightweight pub/sub transport for the vast majority of its use cases. Temperature sensors, dashboards, device commands, live monitoring — all of this is v5.0 territory and should stay there.

**But MQTT is *already being used* as a message queue.** Our customers are doing it right now, with application-layer hacks. The question is not "should MQTT be a message queue?" — it is "given that our customers are already using MQTT as a message queue, should the protocol provide proper primitives, or should we keep telling them to build their own?"

I think we should provide the primitives. Scoped narrowly (`$queue/` namespace only), opt-in (zero overhead for standard pub/sub), and backward-compatible (v5.0 clients and brokers are unaffected).

### Why Not Kafka (The Answer That Never Changes)

**The edge devices cannot run Kafka clients.** A semiconductor fab has 500 tools running embedded MQTT clients on proprietary firmware that will be in service for 15–25 years. These tools cannot be reflashed. The [Kafka JVM requirement](https://docs.confluent.io/platform/current/installation/system-requirements.html) is a non-starter.

The bridge architecture (MQTT → Kafka → Consumer) works but adds operational cost, a failure domain, and a team. Every customer I have worked with who runs this architecture has asked if we can eliminate the bridge. v6.0 is my answer.

---

## "Too Much HOW, Not Enough WHAT and WHY"

**Simon is right, and I appreciate the feedback.** The original proposal led with wire formats and byte layouts. That was a mistake. The audience for this proposal is not protocol implementers (yet) — it is the people who need to understand *why* these changes matter before they evaluate *how* they work.

The WHAT and WHY are simple:

| What Customers Need | Why They Need It | What v5.0 Offers | What v6.0 Adds |
|-----|------|----|----|
| Durable queues that outlive sessions | Consumer maintenance should not cause message loss | `$share/` — but not durable, not ordered, messages lost on session termination per `[MQTT-4.8.2-5]` | `$queue/` — named, persistent, survives all consumer disconnections |
| Message ordering with gap detection | Consumers need to know if a message was lost | Nothing — Packet IDs are session-scoped and recycled | Stream Sequence Number — per-queue, cluster-wide, permanent |
| Pull-based flow control | Slow consumers crash under push load | `Receive Maximum` — caps window, but broker still pushes | FETCH — consumer pulls when ready; no FETCH = no delivery |
| Strict consumer groups with failover | Consumer crashes should not lose in-flight messages | `$share/` — but `[MQTT-4.8.2-5]` discards messages on session termination | SQMC — message lock released on disconnect, re-dispatched immediately |
| Broker state continuity signal | Clients need to know if messages were lost during broker restart | Session Present flag — but only signals session existence, not message continuity | Stream Epoch — signals whether sequence state is continuous |

The genesis for this thinking is 2.5 years of watching our customers solve these problems in application code and asking myself whether we can do better at the protocol level. I believe we can.

---

## Summary of Responses

| Criticism | Response |
|-----------|----------|
| "2.1 is just a shared subscription" | No. The v5.0 spec itself contradicts this: `[MQTT-4.8.2-5]` prohibits re-routing unacked messages to other consumers (messages are lost), `[MQTT-4.6.0-6]` scopes ordering to non-shared subs only, and the spec provides no normative requirement to buffer messages when no subscriber exists. HiveMQ built Declared Shared Subscriptions as a proprietary extension precisely because `$share/` lacks durable queue semantics. |
| "2.2 conflates concepts" | Fair. The proposal does NOT enlarge Packet Identifiers. Stream Sequence is a separate 5-byte property for a separate purpose (ordering, gap detection, dedup), added only to `$queue/` messages. Standard pub/sub is unaffected. |
| "2.3 is Receive Maximum" | `Receive Maximum` caps the in-flight window but the broker still pushes. The consumer cannot say "stop sending until I ask." FETCH inverts the model — no request, no delivery. This eliminates the slow consumer death spiral I have seen repeatedly in customer deployments. |
| "2.4 is plainly wrong" | The Epoch is not an implementation detail — it is a protocol-level signal carried in CONNACK that tells the client whether broker message state is continuous. It does not prescribe clustering, topology, or architecture. A single-node broker can use it. It is analogous to the Session Present flag but for queue sequence state. |
| "Protocol doesn't concern itself with broker nodes" | Agreed — and the Epoch doesn't either. It defines client-facing behavior: "if sequence continuity cannot be guaranteed, tell the client." How the broker determines this internally is implementation-defined. |
| "This should be application-level" | Every customer I have worked with has built these primitives in application code. None of their implementations are compatible. The broker cannot optimize what it cannot see. Sparkplug already proves the need. v6.0 standardizes the pattern. |
| "Why not Kafka?" | Edge devices cannot run Kafka clients. The bridge adds cost and failure domains. v6.0 eliminates the bridge without changing edge devices. |
| "Ship it as an extension first" | The extension-first path leads to fragmentation, not validation. If HiveMQ ships it proprietary, EMQX and AWS build incompatible versions. Standardizing early — before fragmentation — is cheaper than standardizing late. `$SYS/` and Declared Shared Subscriptions are proof. |
| "Too much HOW, not enough WHY" | Fair. This document provides the WHY. The genesis is 2.5 years of TAM work watching customers solve these problems in application code. |

---

## References

- [MQTT v5.0 OASIS Standard](https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html) — Shared Subscriptions (`[MQTT-4.8.2-5]`, Section 4.8), Ordered Topics (`[MQTT-4.6.0-6]`, Section 4.6), Receive Maximum (Section 3.2.2.3.2), Packet Identifiers (Section 2.2.1)
- [HiveMQ: Declared Shared Subscriptions](https://docs.hivemq.com/hivemq/latest/user-guide/declared-shared-subscriptions.html) — HiveMQ's proprietary extension to fill the durable queue gap in `$share/`
- [HiveMQ: MQTT 5 Shared Subscriptions](https://www.hivemq.com/blog/mqtt5-essentials-part7-shared-subscriptions/) — Shared subscription behavior, ordering limitations
- [HiveMQ: Shared Subscription Documentation](https://www.hivemq.com/docs/hivemq/4.13/user-guide/shared-subscriptions.html) — Implementation details and configuration
- [HiveMQ: Client Load Balancing with Shared Subscriptions](https://www.hivemq.com/blog/mqtt-client-load-balancing-with-shared-subscriptions/) — Practical challenges with slow consumers
- [HiveMQ: MQTT vs AMQP for IoT](https://www.hivemq.com/blog/mqtt-vs-amqp-for-iot/) — Protocol complexity comparison
- [Confluent Platform System Requirements](https://docs.confluent.io/platform/current/installation/system-requirements.html) — Kafka resource footprint
- [Apache Kafka Consumer API](https://kafka.apache.org/25/javadoc/org/apache/kafka/clients/consumer/KafkaConsumer.html) — Pull-based poll() API
- [Eclipse Sparkplug Specification](https://sparkplug.eclipse.org/specification/) — Application-layer sequencing on MQTT
- [Sparkplug v2.2 Specification PDF](https://sparkplug.eclipse.org/specification/version/2.2/documents/sparkplug-specification-2.2.pdf) — Sequence number and state management details
- [SEMI SECS/GEM Standard](https://en.wikipedia.org/wiki/SECS/GEM) — Semiconductor equipment communication
- [SEMI E30 (GEM) Specification](https://store-us.semi.org/products/e03000-semi-e30-specification-for-the-generic-model-for-communications-and-control-of-manufacturing-equipment-gem) — Transaction semantics for semiconductor manufacturing
- [IEC 61850](https://en.wikipedia.org/wiki/IEC_61850) — Power grid communication standard
- [IEC 61850 and MQTT Integration](https://www.emqx.com/en/blog/iec-61850-protocol) — Edge transport for grid data
- [NATS JetStream Consumers](https://docs.nats.io/nats-concepts/jetstream/consumers) — Pull-based consumer model reference
- [HiveMQ: Industrial IoT Data Streaming with MQTT](https://www.hivemq.com/blog/building-industrial-iot-data-streaming-architecture-mqtt/) — MQTT at industrial scale
