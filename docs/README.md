# MQTT Version 6.0 — Industrial Stream & Advanced Queuing Extension

> **Status:** Draft Proposal — Based on exploratory design session, March 2026
> **Author:** Bill Sommers, AI Solutions Lead, HiveMQ, Inc.
> **Base Specification:** [MQTT v5.0 OASIS Standard](https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html)

---

## Table of Contents

### Overview
1. [Executive Summary](executive-summary.md)
2. [Motivation, Rationale & Intended Audience](motivation.md)
3. [Design Goals & Motivation](#design-goals)

### Specification
3. [MQTT v6.0 Full Specification](spec/mqtt-v6.0-spec.md)
4. [Protocol Changes from v5.0](spec/mqtt-v6.0-spec.md#5-summary-of-changes-v50-vs-v60)
5. [Compatibility Analysis](spec/mqtt-v6.0-spec.md#6-compatibility-layer)

### Architecture & Diagrams
6. [System Architecture Diagrams](diagrams/architecture.md)
7. [Packet Flow Diagrams](diagrams/packet-flows.md)
8. [Cluster Failover & Epoch Diagrams](diagrams/cluster-failover.md)

### Analysis
9. [Alternative Approaches](alternatives.md)
10. [Addressing Criticisms — Point-by-Point Rebuttals](rebuttals.md)
11. [Critical Perspectives & Rebuttals](critiques-and-rebuttals.md)
12. [Technical Pitfalls & Mitigations](critiques-and-rebuttals.md#technical-pitfalls)
13. [Performance Analysis: High-Volume & DEP Scale](performance-analysis.md)
14. [Critical Analyses: Security, OT SRE, and Protocol Design](critical-analyses.md)
15. [SQMC vs. HiveMQ Declared Shared Subscriptions](sqmc-vs-declared-shared-subscriptions.md)

### Application Layer Lift
15. [The Lift — Overview & Feature Split](lift-overview.md)
16. [Option A: Slim Protocol + MQTT Stream Application Profile](lift-option-a.md)
17. [Option B: Protocol Spec + Normative Annex A](lift-option-b.md)
18. [Option C: Two Independent Specifications](lift-option-c.md)

### Reference Implementations
14. [Python v6.0 Shim (`gmqtt`)](../src/python/mqtt_v6_shim.py)
15. [Protobuf Schema](../src/proto/mqtt_v6.proto)
16. [HiveMQ Java Extension](../src/java/MqttV6Interceptor.java)

### Consolidated Reference
17. [Full Proposal PDF (all sections + rendered diagrams)](mqtt-v6.0-proposal.pdf)

---

## Design Goals

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

The proposal exists in **two variants** — see [Alternatives](alternatives.md) for full discussion:

### Track A: Native v6.0 (Breaking)
Introduces `FETCH` as a true Control Packet Type 16. Requires v6.0-aware broker and clients. Protocol Level in CONNECT is `6`.

### Track B: Compatible Extension (Non-Breaking)
Tunnels all v6.0 features through v5.0 Property and User Property fields. Works on existing v5.0 brokers with a HiveMQ Extension Plugin. Protocol Level remains `5`.

The **recommended path** is Native v6.0 with an optional Compatibility Layer for hybrid deployments.

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
