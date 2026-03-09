# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains a proposal for **MQTT Version 6.0**, an industrial-grade extension to the MQTT 5.0 protocol. The source material is a Gemini AI chat export (`input/MQTT_V6.0-Proposal.md`) that was collaboratively developed to explore extending MQTT 5.0 for high-integrity industrial IoT, specifically semiconductor manufacturing (SECS/GEM).

## Repository Structure

```
input/    - Source material (Gemini AI chat export of the full proposal conversation)
docs/     - Generated documentation (markdown, diagrams)
spec/     - Formal specification files
src/      - Code examples (Python shims, Java HiveMQ extensions, Protobuf schemas)
output/   - Rendered/exported artifacts
```

## Core Proposal: MQTT v6.0 Key Features

All v6.0 extensions are **non-breaking and property-based** (binary-compatible with v5.0 parsers):

1. **32-bit Stream Sequence Numbers** (`Property 0x30`) — Monotonic, cluster-wide message identity replacing the 16-bit per-session Packet ID.
2. **Stream Epoch** (`Property 0x35`) — 16-bit cluster "era" counter, incremented on catastrophic failover; clients reset idempotency state on epoch change.
3. **`$queue/` Namespace** — Named, durable persistent queues that exist independently of client sessions.
4. **Virtual FETCH** — Pull-based flow control via `PUBLISH` to `$SYS/queues/{name}/fetch` with `batch-size` user property; replaces the push-flood model.
5. **SQMC Semantics** — Single-Queue Multi-Consumer with `v6-semantics: competing` (round-robin) or `v6-semantics: exclusive` (primary + hot-standby) via SUBSCRIBE user properties.
6. **Throughput Limit** (`Property 0x41`) — Broker-enforced KB/s throttling in CONNACK.
7. **v6.0 Handshake** — `CONNECT` includes `User Property: ("mqtt-ext", "v6.0")`; broker echoes it in `CONNACK` to confirm support.

## Compatibility Notes

- `FETCH` as a new packet Type 16 was **rejected** (breaks v5.0); replaced by Virtual FETCH via control topics.
- Modifying `SUBSCRIBE` bits 6-7 was **rejected** (breaks v5.0); replaced by `v6-semantics` User Property.
- Property IDs `0x30` and `0x35` are in the reserved range but safe in v5.0 (unknown properties are ignored).
- The `$queue/` namespace is a "soft break" — v5.0 brokers may misroute; mitigated by v6-handshake fallback.

## Cluster Architecture (HiveMQ Shared-Nothing)

- Queue ownership via consistent hashing — each `$queue/` has a Leader Node.
- On leader failure: Epoch increments, new leader triggers client resync.
- Client reconnect sends `Last Received Seq` and `Current Epoch` in CONNECT for seamless resume.
- `StreamMetadata` (Seq + Epoch) is replicated as part of session state across the cluster data grid.

## Reference Material

- MQTT v5.0 spec: https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html
- HiveMQ Extension SDK: Java `PublishInboundInterceptor`, `ClusterService`, `ManagedPersistenceService`
- Client library used in examples: `gmqtt` (Python asyncio)
- Industrial protocol context: SECS/GEM (SEMI Equipment Communications Standard)
