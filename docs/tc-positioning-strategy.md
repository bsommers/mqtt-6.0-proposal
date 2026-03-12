# TC Positioning Strategy: MQTT-RSSP as Track B, Native v6.0 as Track A

> **Author:** Bill Sommers, AI Solutions Lead, HiveMQ, Inc.
> **Date:** March 2026
> **Status:** Strategy document — March 2026
> **Context:** Concrete positioning strategy for OASIS TC submission, synthesizing external technical review feedback

---

## 1. The Two-Track Strategy

The MQTT v6.0 proposal has always contained two separable technical layers. The insight from the external review is not that we should abandon MQTT 6.0 — it is that we should surface that two-track structure explicitly and lead with the right track in OASIS TC discussions.

**Track A — Native MQTT 6.0:** The full protocol revision. Protocol Level 6, Type 16 FETCH packet, binary-efficient property IDs (0x30, 0x35, 0x3A–0x3C), SQMC native enforcement. This is the long-term technical target and the canonical specification. It requires updated client libraries and brokers.

**Track B — Compatible Extension (MQTT-RSSP):** The same semantics, expressed entirely as User Properties and `$SYS/` control topics over Protocol Level 5. Fully compatible with any conformant MQTT 3.1.1 or v5.0 broker. No changes to the wire protocol. This is what gets submitted to OASIS first.

The external review introduced the name **MQTT Reliable Secure Streams Profile (MQTT-RSSP)** for the compatible-extension layer. That name is exactly right. Track B of MQTT v6.0 *is* MQTT-RSSP. Naming it clearly is a positioning decision, not a technical one — the semantics of Track B are already fully specified in the proposal.

The two-track structure resolves the tension that drives TC resistance. The label "MQTT 6.0" by itself signals a major version revision: breaking changes, years of TC work, and ecosystem-wide migration costs. MQTT-RSSP signals something the TC can evaluate and ratify in a fraction of that time. Submitting Track B first does not retreat from Track A; it establishes the semantic framework that makes Track A's native optimizations self-evident to the TC once the profile is ratified.

---

## 2. The OASIS Submission Sequencing

### Phase 1 Submission: MQTT-RSSP (Track B)

Submit the compatible extension profile to OASIS first. The submission scope:

- **Stream Sequence Numbers** — User Property `v6-seq` (string-encoded uint32). Establishes the gap-detection and idempotency semantics.
- **Stream Epoch** — User Property `v6-epoch` (string-encoded uint16). Establishes the session-discontinuity signaling semantics.
- **Payload Encryption Envelope** — User Properties `v6-key-id`, `v6-key-algo`, `v6-key-version`. Establishes the broker-transparent key-reference envelope.
- **SQMC Consumer Modes** — User Property `v6-semantics` in SUBSCRIBE (`competing` or `exclusive`). Establishes competing/exclusive consumer semantics at the subscription level.
- **Virtual FETCH** — PUBLISH to `$SYS/queues/{name}/fetch` with User Property `v6-batch`. Establishes the pull-based flow-control semantics.

Every one of these is a semantic reservation: defining what these fields mean, how clients must produce and consume them, and what conformant broker behavior looks like. Property IDs and packet types are not part of Phase 1. The specification language reads as an interoperability profile, not a protocol revision.

### Phase 2 Submission: Track A Native Extensions

After MQTT-RSSP is standardized and the semantic framework is established, submit the native v6.0 optimizations to OASIS as a protocol extension:

- Type 16 FETCH packet — eliminating the round-trip overhead of Virtual FETCH.
- Property 0x30 (Four Byte Integer) — binary-efficient Stream Sequence Number.
- Property 0x35 (Two Byte Integer) — binary-efficient Stream Epoch.
- Properties 0x3A–0x3C (Key ID, Algorithm, Key Version) — binary-efficient encryption envelope.
- Protocol Level 6 negotiation — formal CONNECT/CONNACK signaling for native v6.0 support.
- SQMC native enforcement — broker-level competing/exclusive consumer arbitration.

At this point, the TC is not being asked to evaluate the semantics — those are already ratified in MQTT-RSSP. They are being asked to approve an optimized wire encoding for semantics the ecosystem has already standardized. This is a much smaller ask.

### Why This Mirrors Standard OASIS Practice

This sequencing is how OASIS standards commonly evolve. A profile specification establishes what an implementation is required to do. An optimized protocol encoding follows once the interoperability baseline exists. MQTT-RSSP as profile first, native v6.0 optimizations as protocol extension second, follows the same pattern as WS-Security to WS-Trust, or AMQP Management to AMQP 1.0.

---

## 3. The Compatibility Statement That Wins Reviewers

Every document prepared for TC review should include this statement, verbatim, in the abstract or first paragraph:

> "MQTT-RSSP introduces no changes to the MQTT wire protocol and is fully interoperable with existing MQTT 3.1.1 and MQTT 5.0 brokers. It is a standardized semantic layer that implementations may additionally optimize using the native v6.0 extensions in Track A."

That single paragraph removes approximately 70% of the reflexive TC resistance before the technical review begins. It signals:

- No ecosystem disruption — existing deployments are unaffected.
- No breaking changes — every conformant MQTT 5.0 broker can forward MQTT-RSSP messages today.
- A clear upgrade path — Track A is positioned as a performance optimization, not a requirement.

A client running MQTT-RSSP on Mosquitto today — using only User Properties and payload conventions — is a conformant implementation. A client running MQTT-RSSP on HiveMQ with native `$queue/` support gets better performance, stronger durability guarantees, and lower latency — but is running the same profile. This is not a hypothetical compatibility story; it is the Track B architecture that already exists in the proposal.

---

## 4. Answering the Two Fatal Questions

Two questions will be raised in the first TC review session. If they are not answered concisely and confidently, they become blockers that derail the entire proposal. Do not bury the answers in appendices — put them in the abstract.

### Q1: "Why isn't TLS already sufficient?"

TLS protects the transport hop — client to broker to subscriber. It terminates at the broker. In a multi-tenant cloud broker, a federated bridge deployment, or any infrastructure where the broker is operated by a third party, TLS provides no protection against the broker itself. The broker decrypts, reads, re-encrypts, and forwards. For semiconductor equipment vendors shipping process recipes to tools on a customer's factory floor, the cloud broker IS an attacker surface — not a hypothetical one, a contractual one: the broker operator's SLA explicitly disclaims liability for payload content.

MQTT-RSSP payload encryption (Phase 1: User Properties `v6-key-id`, `v6-key-algo`, `v6-key-version`; Phase 2: Properties 0x3A–0x3C) protects the data across the entire messaging lifecycle, not just the network path. The broker forwards an opaque payload with metadata. It cannot read process parameters, safety-critical commands, or proprietary control sequences. The pattern is precise: TLS = network confidentiality; MQTT-RSSP = data confidentiality. They are complementary, not redundant.

### Q2: "Who manages the keys?"

The profile defines only how encrypted payloads reference keys: a `key_id`, an `algorithm` identifier, and a `key_version`. Key distribution, rotation, and revocation are explicitly out of scope. Deployments integrate with whatever key management they already operate — device provisioning systems, enterprise PKI, HSMs, SPIFFE/SPIRE workload identity. The same design pattern as TLS SNI: the protocol references an identity, the PKI manages it. MQTT-RSSP does not introduce a new key management problem; it introduces a standard envelope for referencing keys from whatever system already manages them.

---

## 5. Feature-by-Feature TC Positioning

Each feature needs a two-to-three sentence TC pitch that connects it to a concrete, documented ecosystem problem. Abstract arguments about reliability do not move standards committees; specific evidence of fragmentation does.

For each feature, the Phase 1 submission (MQTT-RSSP, Track B) is the TC ask. The Phase 2 form (Track A native extension) is the optimization path presented as future work.

**Stream Sequence Numbers**

- Phase 1 (MQTT-RSSP): User Property `v6-seq` (string-encoded uint32 in every PUBLISH).
- Phase 2 (Track A): Property 0x30, Four Byte Integer.

This standardizes the single most-reimplemented pattern in IIoT MQTT deployments. Every Eclipse Sparkplug B deployment already implements a 64-bit `seq` field in protobuf payloads for exactly this purpose — gap detection and ordered delivery. MQTT-RSSP moves the sequence number from a payload-embedded convention into a standard envelope property so any client library can implement it once, interoperably, without a custom serialization format.

**Stream Epoch**

- Phase 1 (MQTT-RSSP): User Property `v6-epoch` (string-encoded uint16 in every PUBLISH).
- Phase 2 (Track A): Property 0x35, Two Byte Integer.

A simple replay protection mechanism across device restarts and broker failovers, analogous to TLS session tickets. The Epoch is a monotonically increasing uint16 that subscribers use to detect and discard stale replays and to know when their local idempotency state is no longer valid. A single-node Mosquitto instance can implement it correctly by incrementing a counter on restart. Zero broker architecture changes required.

**Payload Encryption Envelope**

- Phase 1 (MQTT-RSSP): User Properties `v6-key-id`, `v6-key-algo`, `v6-key-version`.
- Phase 2 (Track A): Properties 0x3A (Key ID), 0x3B (Algorithm), 0x3C (Key Version).

Three optional User Properties constitute a broker-transparent encrypted envelope. No broker changes. No key material in the protocol. Solves the multi-tenant broker trust problem that every large industrial MQTT customer has raised independently — the problem that today forces them to implement ad-hoc payload encryption with no standard key-reference format, making interoperability between equipment vendors impossible.

**SQMC (Single-Queue Multi-Consumer)**

- Phase 1 (MQTT-RSSP): User Property `v6-semantics` in SUBSCRIBE (`competing` or `exclusive`).
- Phase 2 (Track A): SQMC native enforcement in Protocol Level 6 broker.

This feature must be framed carefully. Do not present it as a QoS replacement. Present it as application-level verifiable delivery confirmation for safety-critical command streams. MQTT QoS 1 and QoS 2 guarantee delivery semantics at the transport layer. SQMC provides cryptographic proof — via the sequence number and acknowledgment protocol — that the correct subscriber received and validated the correct message. This is required for SECS/GEM S2F21 process start command handshakes, IEC 61850 grid protection relay sequences, and other safety-critical applications where "I sent it and the broker said OK" is not a sufficient guarantee.

**FETCH (Pull-Based Flow Control)**

- Phase 1 (MQTT-RSSP): Virtual FETCH via PUBLISH to `$SYS/queues/{name}/fetch` with User Property `v6-batch`.
- Phase 2 (Track A): Type 16 FETCH packet (dedicated Control Packet Type).

Virtual FETCH is broker-transparent and implementable today as a HiveMQ extension plugin with no wire-protocol changes. It solves the "thundering herd" problem where a recovering consumer is flooded with backlogged messages. Phase 2 replaces the control-topic round-trip with a dedicated packet type, eliminating the overhead of Topic Name encoding in the request path. The semantic specification — what the broker MUST hold, what it MUST release, what the batch-size bound means — is identical in both phases.

---

## 6. What NOT to Say / What TO Say

Language matters in TC submissions. Certain phrases activate pattern-matching against past standards failures and produce reflexive resistance before the technical argument is heard. For each phrase to avoid, there is a preferred alternative that conveys the same technical content without the political cost.

| Avoid | Use instead |
|---|---|
| "MQTT 6.0 protocol revision" (as the primary identifier) | "MQTT Reliable Secure Streams Profile (MQTT-RSSP)" |
| "major protocol revision" | "interoperability profile" |
| "new packet type" (in Phase 1 context) | "payload convention / User Property extension" |
| "breaking change" | "additive, opt-in extension" |
| "broker encryption support" | "broker-transparent security" |
| "we need a new version" | "we are standardizing patterns already in production" |
| "replaces MQTT 5.0 features" | "complements existing MQTT 5.0 semantics" |
| "Track A is the real proposal" | "Track A provides native wire-efficiency optimizations for the standardized profile" |

The argument "we are standardizing patterns already in production" is both true and persuasive: Sparkplug B sequence numbers, application-layer idempotency tables, and session resume logic are in production at scale today. MQTT-RSSP is a standardization of existing practice, not a proposal to change practice.

Critically: do not hide Track A. Present the two-track structure transparently. The TC should understand that MQTT-RSSP is Phase 1 and that native v6.0 optimizations are Phase 2. Hiding Track A and then introducing it later looks like a bait-and-switch. Presenting both tracks upfront — with MQTT-RSSP as the submission surface and Track A as deferred optimization — demonstrates technical honesty and strategic maturity.

---

## 7. Estimated Acceptance Probability

Based on the external review's assessment and the positioning analysis above:

| Framing | Probability | Why |
|---|---|---|
| "MQTT 6.0 protocol revision only (no profile)" | ~10-15% | Major version, breaking changes, years of TC work; triggers maximum resistance before technical merit is heard |
| "MQTT-RSSP profile (Track B) + optional Track A optimization" | ~50-70% | Profile framing = low risk; broker transparency removes ecosystem disruption concerns; Track A deferred to Phase 2 after profile is ratified |
| "MQTT-RSSP profile without Track A" | ~40-60% | Removes the long-term technical target and native-efficiency story; less compelling to TC members evaluating ecosystem impact |

The delta between the bottom and middle rows is entirely structural. Track A remains the technical target; positioning it as Phase 2 — an optimization of an already-standardized semantic profile — removes the barrier to Phase 1 acceptance without abandoning the long-term goal.

The ~50-70% range under MQTT-RSSP framing is conditional on answering the two fatal questions (TLS sufficiency, key management) concisely in the abstract, and on keeping payload encryption clearly marked as optional. If SQMC is submitted as a separate follow-on to the core MQTT-RSSP profile (Stream Sequence + Epoch + payload encryption envelope), the acceptance probability for the core submission likely rises above 70%.

---

## 8. Relationship to Lift Documents

The two-track structure maps directly onto the lift document architecture options.

**MQTT-RSSP (Track B, Phase 1 submission)** is closest to **Option A** (slim protocol with companion profile) and to **Option C Phase 1**: the client-side obligations — gap detection state machine, epoch resync procedure, high-watermark persistence, exactly-once workflow — become the normative content of the MQTT-RSSP specification. The broker-side obligations (Property 0x30 assignment, `$queue/` persistence, SQMC arbitration) become SHOULD/RECOMMENDED behaviors for brokers wishing to natively support MQTT-RSSP, rather than MUST requirements gated on a new protocol level.

In Option C terms: the "MQTT Stream 1.0 application protocol" layer IS the MQTT-RSSP OASIS submission. Rename it consistently across the lift documents before the TC review package is assembled.

**Track A (native v6.0, Phase 2 submission)** maps to the HiveMQ product layer and to Option C Phase 2: the "MQTT 6.0 transport extension" broker obligations (native FETCH enforcement, binary Property IDs, Protocol Level 6 CONNECT/CONNACK negotiation) are what HiveMQ ships as a competitive differentiator and what Phase 2 proposes to OASIS once the semantic framework is established.

The practical consequence: what gets submitted to OASIS first is the profile, not the transport. What HiveMQ ships as a product today is the native broker support for that profile. The technical content of both Track A and Track B is identical to the existing proposal — the only change is submission sequencing and primary identifier.

---

## 9. Five Predictable TC Objections and Counter-Arguments

These objections will be raised in the first TC review session. Having crisp, pre-prepared responses prevents them from becoming blockers.

> **Note:** The committee's decision hierarchy for objections is: (1) backwards compatibility, (2) complexity, (3) protocol scope, (4) interoperability, (5) implementation difficulty. Address the first two convincingly and the rest become manageable.

**Objection 1: "This makes MQTT too complicated."**

Counter: Position as optional metadata, not mandatory behavior. Constrained devices do not need to generate sequence numbers. Brokers do not need to interpret them. These are receiver-side semantics: MQTT transport unchanged, MQTT semantics unchanged, MQTT metadata extended. The same argument was made about MQTT 5.0 properties — the ecosystem absorbed it. Any deployment that does not use `$queue/`, Stream Sequence, or Epoch sees zero change to the protocol they operate today.

**Objection 2: "This looks like Kafka, not MQTT."**

Counter: Reframe as telemetry validation, not stream infrastructure. The key distinction: in Kafka, ordering is managed by broker partitions. In MQTT v6.0, ordering is *detected* using publisher metadata. The broker plays no role in sequencing — it forwards properties unchanged. "This proposal does not introduce broker-managed logs or partitions. It only enables receivers to verify telemetry completeness." The difference between gap detection and stream partitioning is architectural, not cosmetic.

**Objection 3: "This assumes broker clustering."**

Counter: Reframe Epoch as a publisher/broker lifecycle marker, not a distributed-systems construct. "Epoch = publisher restart marker" — not a consensus epoch. A single-node Mosquitto instance that restarts and cannot guarantee sequence continuity increments the Epoch. No clustering, no Raft/Paxos required. The Epoch is topology-agnostic. This reframe is critical — it removes the most technically intimidating aspect of the proposal before it becomes a blocker.

**Objection 4: "Can't this be done at the application layer?"**

Counter: It can, and it is — today, by every industrial customer, incompatibly. Vendor A uses JSON `{"seq": N}`, Vendor B uses protobuf `sequence_id`, Vendor C uses a custom binary header. No generic tooling can observe any of them. Protocol-level metadata enables: broker observability, generic client libraries, standard debugging tools, cross-vendor telemetry validation. The interoperability argument is the strongest one for standards bodies: MQTT-RSSP is a standardization of existing practice, not a proposal to change practice.

**Objection 5: "Will this break existing clients?"**

Counter: MQTT v5.0 requires conformant implementations to ignore unknown property IDs. Stream Sequence (0x30), Epoch (0x35), and payload encryption properties (0x3A–0x3C) are all in the currently unassigned range. Clients ignoring them remain fully compliant. The Compatibility Layer (Track B / MQTT-RSSP) implements all semantics as User Properties — zero wire-level changes. This is the same strategy MQTT 5.0 used when adding properties to 3.1.1. The backwards-compatibility story is the same answer that got v5.0 through the TC.

---

## 10. Vendor Alignment Strategy

Three vendors whose support dramatically shifts committee dynamics toward acceptance.

**HiveMQ** — Enterprise deployments and protocol thought leadership. HiveMQ customers already ask for telemetry gap detection and reconnect validation. An endorsement from HiveMQ signals enterprise production readiness. Target message: "Standardized telemetry sequencing improves operational observability in large MQTT deployments."

**EMQX** — Largest broker installation base globally (telecom, automotive, industrial). Already exploring persistent stream features. A standard property allows them to build telemetry gap detection and stream observability dashboards without proprietary extensions. Target message: "Standard sequence metadata enables cross-broker interoperability for industrial telemetry."

**IBM** — Protocol lineage and institutional credibility within OASIS. IBM's historical role in MQTT creation gives their voice weight in standards discussions. Target message: "Telemetry continuity metadata strengthens MQTT's data integrity guarantees without altering its lightweight nature."

> **The ideal scenario** is two independent broker vendors who already implement the feature. At that point the conversation shifts from "should we do this?" to "how should we standardize this?" — a fundamentally different committee dynamic.

---

## 11. The Observability Commercial Hook

The observability angle resonates with vendors because it enables new commercial features that differentiate their products. Protocol-level metadata opens a class of broker capabilities that User Properties alone cannot support:

- Broker dashboards showing telemetry gap rates per device
- Alerting on device restart events via Epoch changes
- Edge buffering validation (did the gateway actually forward everything?)
- Telemetry health scoring across device fleets
- SLA validation for industrial data pipelines

Most MQTT proposals solve broker problems. This proposal solves **system problems** — specifically, the operational failure modes that occur in edge computing, industrial automation, and AI data pipelines. Those are the environments MQTT now dominates, and the environments where operational visibility has the highest business value.

This framing also separates MQTT-RSSP from the "Kafka competitor" narrative: Kafka solves throughput. MQTT-RSSP solves observability and recovery. These are different markets, different buyers, and different arguments in front of the TC.
