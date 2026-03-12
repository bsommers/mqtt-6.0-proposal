# MQTT Version 6.0 — Industrial Stream & Advanced Queuing Extension

> **Status:** Draft Proposal — Based on exploratory design session, March 2026
> **Author:** Bill Sommers, AI Solutions Lead, HiveMQ, Inc.
> **Base Specification:** [MQTT v5.0 OASIS Standard](https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html)

---

## Audience Reading Paths

**Standards Committee Member**
> Start here: [Executive Summary](executive-summary.md) → [TC Positioning Strategy](tc-positioning-strategy.md) → [Alternative Approaches](alternatives.md) → [Addressing Criticisms](rebuttals.md)
> *(~25 minutes. Executive Summary now contains the core technical case, two-track framing, and standardization path. TC Positioning Strategy has the OASIS submission sequencing and objection responses. Deep-dive: [Motivation](motivation.md) for full technical justification of each feature.)*

**HiveMQ Engineer / Implementer**
> Start here: [Executive Summary](executive-summary.md) → [Motivation](motivation.md) → [Full Specification](spec/mqtt-v6.0-spec.md) → [Critical Perspectives & Pitfalls](critiques-and-rebuttals.md) → [Reference Implementations](#reference-implementations)

**Skeptic / Challenger**
> Start here: [TC Positioning Strategy](tc-positioning-strategy.md) → [Addressing Criticisms](rebuttals.md) → [Critical Perspectives & Pitfalls](critiques-and-rebuttals.md) → [Application Layer Lift — Overview](lift-overview.md)

---

## Table of Contents

### Strategy & Framing
1. [TC Positioning Strategy — MQTT-RSSP Reframe & Acceptance Playbook](tc-positioning-strategy.md)

### Overview
2. [Executive Summary](executive-summary.md)
3. [Motivation, Rationale & Intended Audience](motivation.md)

### Specification
4. [MQTT v6.0 Full Specification](spec/mqtt-v6.0-spec.md)
5. [Protocol Changes from v5.0](spec/mqtt-v6.0-spec.md#5-summary-of-changes-v50-vs-v60)
6. [Compatibility Analysis](spec/mqtt-v6.0-spec.md#6-compatibility-layer)

### Architecture & Diagrams
7. [System Architecture Diagrams](diagrams/architecture.md)
8. [Packet Flow Diagrams](diagrams/packet-flows.md)
9. [Cluster Failover & Epoch Diagrams](diagrams/cluster-failover.md)

### Application Layer Lift
10. [The Lift — Overview & Feature Split](lift-overview.md)
11. [Option A: Slim Protocol + MQTT Stream Application Profile](lift-option-a.md)
12. [Option B: Protocol Spec + Normative Annex A](lift-option-b.md)
13. [Option C: Two Independent Specifications](lift-option-c.md)

### Analysis & Rebuttals
14. [Alternative Approaches](alternatives.md)
15. [Addressing Criticisms — Point-by-Point Rebuttals](rebuttals.md)
16. [Critical Perspectives & Rebuttals](critiques-and-rebuttals.md)
17. [Technical Pitfalls & Mitigations](critiques-and-rebuttals.md#technical-pitfalls)
18. [SQMC vs. HiveMQ Declared Shared Subscriptions (Full Detail)](sqmc-vs-declared-shared-subscriptions.md) (see also: Motivation doc for integrated summary)
19. [Performance Analysis: High-Volume & DEP Scale](performance-analysis.md)
20. [Critical Analyses: Security, OT SRE, and Protocol Design](critical-analyses.md)

### Reference Implementations
21. [Python v6.0 Shim (`gmqtt`)](../src/python/mqtt_v6_shim.py)
22. [Protobuf Schema](../src/proto/mqtt_v6.proto)
23. [HiveMQ Java Extension](../src/java/MqttV6Interceptor.java)

### Consolidated Reference
24. [Full Proposal PDF (all sections + rendered diagrams)](mqtt-v6.0-proposal.pdf)

---

MQTT v6.0 solves three hard problems of industrial IoT that MQTT v5.0 leaves to application-layer hacks:

| Problem | v5.0 Status | v6.0 Solution |
|---------|-------------|---------------|
| **Message Ordering** | 16-bit per-session Packet ID, reused frequently | 32-bit monotonic Stream Sequence (per queue, cluster-wide) |
| **Flow Control** | Broker pushes all messages; consumer can be flooded | Pull-based FETCH packet; consumer dictates rate |
| **Cluster Consistency** | Opaque to clients; failover is implementation-defined | Epoch-based failover; clients detect and resync after cluster partition |
| **Durable Queues** | Session-bound; lost if client disconnects | Named `$queue/` namespace; persists independently of sessions |
| **Consumer Patterns** | Shared Subscriptions with loose semantics | SQMC: strict Competing (round-robin) and Exclusive (hot-standby) modes |

---

## Two Tracks

The proposal exists in **two variants** with one recommended submission sequence:

### Track B: MQTT-RSSP — Compatible Extension (Submit First)
All semantics expressed as MQTT v5.0 User Properties and `$SYS/` control topics. Works on existing v5.0 brokers with zero wire-protocol changes. This is the **MQTT Reliable Secure Streams Profile (MQTT-RSSP)** — the Phase 1 OASIS submission. Protocol Level remains `5`.

### Track A: Native v6.0 (Deferred Optimization)
Introduces `FETCH` as Control Packet Type 16, binary Property IDs (`0x30`, `0x35`, `0x3A`–`0x3C`), and Protocol Level `6`. Requires v6.0-aware broker and clients. The Phase 2 OASIS submission — once MQTT-RSSP is ratified, Track A native extensions are the efficiency optimization for the already-standardized semantics.

The **recommended path** is Track B first. See [TC Positioning Strategy](tc-positioning-strategy.md) for the full submission sequencing rationale and acceptance probability analysis.

---

## Key Terminology

| Term | Definition |
|------|-----------|
| **Stream Sequence Number** | A 32-bit monotonic integer (Property `0x30`) assigned per `$queue/` message; immutable across the cluster |
| **Stream Epoch** | A 16-bit counter (Property `0x35`) incremented when cluster failover causes sequence discontinuity |
| **FETCH** | New Control Packet (Type 16) enabling pull-based flow control |
| **`$queue/`** | Topic namespace for named, durable, session-independent queues |
| **SQMC** | Single-Queue Multi-Consumer — strict load balancing with Competing or Exclusive semantics |
| **Virtual FETCH** | Compatibility-mode equivalent of FETCH using `PUBLISH` to `$SYS/queues/{name}/fetch` |
| **High-Watermark** | Client-side record of the last successfully processed sequence number |
| **Distributed Sequence Counter** | A cluster-wide atomic counter in HiveMQ's data grid, one per `$queue/`; any peer node increments it atomically to claim the next sequence number without routing constraints |
