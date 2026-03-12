# SQMC vs. HiveMQ Declared Shared Subscriptions

> **Context:** A common question when reviewing the MQTT v6.0 SQMC proposal is whether HiveMQ's existing [Declared Shared Subscriptions](https://docs.hivemq.com/hivemq/latest/user-guide/declared-shared-subscriptions.html) feature already provides the same capabilities. The short answer: partially, but with four significant gaps — and its existence as a proprietary extension is itself evidence that the standard has a gap.

---

## What Declared Shared Subscriptions Does

HiveMQ Declared Shared Subscriptions are pre-configured `$share/` groups defined in broker configuration (rather than dynamically via SUBSCRIBE). Their key addition over standard `$share/` is that messages are **buffered even when no subscriber is connected** — the queue persists across subscriber disconnects.

This is a real and valuable improvement over the standard `$share/` behavior, where the spec is silent on what to do with messages when no subscriber is active.

---

## The Gaps

Declared Shared Subscriptions solve the offline-buffering problem. They do not solve the remaining gaps that SQMC addresses:

| Capability | `$share/` (MQTT v5.0 Spec) | HiveMQ Declared Shared Subscriptions | SQMC (`$queue/` + v6.0) |
|---|---|---|---|
| **Buffer messages when no subscriber connected** | Not guaranteed — spec is silent | ✅ Yes — HiveMQ's primary addition | ✅ Yes — `$queue/` persists independently |
| **Re-dispatch unacked message on consumer disconnect** | ❌ No — `[MQTT-4.8.2-5]` prohibits; message discarded if session terminates | ❌ No — `[MQTT-4.8.2-5]` still applies at spec level | ✅ Yes — lock released immediately; re-dispatched to next available consumer |
| **Exclusive consumer / hot-standby mode** | ❌ No | ❌ No | ✅ Yes — primary consumer + automatic standby promotion on disconnect |
| **Message ordering guarantee** | ❌ No — `[MQTT-4.6.0-6]` scopes ordering to non-shared subscriptions only | ❌ No | ✅ Yes — strict ascending Stream Sequence Number per queue |
| **Gap detection** | ❌ Impossible — no per-message identity | ❌ Impossible | ✅ Built-in — sequence gaps are detectable and auditable |
| **Survives broker restart (spec-mandated)** | ❌ No — persistence is implementation-defined | ✅ Yes (HiveMQ-specific behavior) | ✅ Yes — persistence to non-volatile storage required before PUBACK |
| **Interoperable across broker vendors** | ✅ Yes — standard | ❌ No — HiveMQ-proprietary | ✅ Yes — standardized wire format |
| **Named, inspectable entity** | ❌ No — subscription pattern only | ❌ No — broker config entry only | ✅ Yes — `$queue/` is a first-class entity with TTL, max-size, storage policy |

---

## The Critical Gap: `[MQTT-4.8.2-5]`

The most consequential difference is message re-dispatch on consumer failure. [MQTT v5.0 Section 4.8.2, normative requirement `[MQTT-4.8.2-5]`](https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html#_Toc3901250) states:

> *"If the Client's Session terminates before the Client reconnects, the Server MUST NOT send the Application Message to any other subscribed Client."*

This means: if a consumer in any `$share/` group (including a Declared Shared Subscription) receives a QoS 1 message, disconnects before sending PUBACK, and its session expires — the message is **discarded**. The spec explicitly prohibits the broker from re-delivering it to another consumer.

In traditional competing-consumer queues (AMQP, JMS, Kafka consumer groups), an unacknowledged message is returned to the queue and re-dispatched. In MQTT v5.0 shared subscriptions, it is destroyed.

SQMC breaks from this by treating `$queue/` topics as session-independent persistent stores. When a competing consumer disconnects, the message lock is released by the broker and the message is immediately re-dispatched — regardless of session state. This is the behavior industrial systems require and cannot get from any `$share/`-based mechanism, proprietary or otherwise.

---

## The Exclusive Consumer Gap

Declared Shared Subscriptions provide no equivalent to SQMC Exclusive Consumer mode. There is no mechanism in `$share/` — declared or dynamic — to designate one consumer as primary and hold others as hot standbys that take over instantly on primary disconnect while preserving strict ordering.

This pattern is non-negotiable for safety-critical command streams: SECS/GEM S2F21 (Remote Start), grid protection relay commands, and financial settlement messages where exactly one consumer must process each message in strict order, with zero-delay failover and no message loss or duplication on consumer failure.

---

## Why Declared Shared Subscriptions Is the Argument, Not the Counterargument

The existence of Declared Shared Subscriptions as a HiveMQ-proprietary feature is itself evidence that the MQTT standard has a gap. HiveMQ built it because `$share/` alone did not satisfy customer requirements. The same customers who use Declared Shared Subscriptions are the ones asking for re-dispatch-on-failure and exclusive consumer semantics — features that Declared Shared Subscriptions does not provide.

The extension-first path (build it proprietary, standardize later) is also how `$SYS/` became permanently fragmented: EMQX, Mosquitto, and HiveMQ each implemented it differently, and 15 years later there is still no standard. If SQMC semantics are standardized now — before EMQX, AWS IoT Core, and others build incompatible variants — the ecosystem gets a single interoperable wire representation. If they are not, every customer running two broker vendors will need a translation layer between competing proprietary implementations.

---

## Summary

Declared Shared Subscriptions is a useful proprietary improvement to `$share/` that addresses the offline-buffering gap. It does not address:

1. **Message re-dispatch on consumer failure** — `[MQTT-4.8.2-5]` prohibits this at the spec level for all `$share/`-based mechanisms
2. **Exclusive consumer / hot-standby semantics** — not available in any `$share/` variant
3. **Message ordering guarantees** — explicitly out of scope for shared subscriptions per the v5.0 spec
4. **Interoperability** — a HiveMQ-only feature; no other broker supports it

SQMC addresses all four. Its standardization closes the gap that Declared Shared Subscriptions can only partially fill — and closes it in a way that works across every v6.0-compliant broker.
