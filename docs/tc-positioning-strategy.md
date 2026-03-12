# TC Positioning Strategy: From "MQTT 6.0" to MQTT-RSSP

> **Author:** Bill Sommers, AI Solutions Lead, HiveMQ, Inc.
> **Date:** March 2026
> **Status:** Internal strategy document — not for external distribution
> **Context:** Synthesizes an external ChatGPT technical review into a concrete committee positioning strategy

---

## 1. The Strategic Problem

The label "MQTT 6.0" is, by itself, a near-fatal framing for an OASIS TC submission. Major version numbers carry a specific meaning in standards bodies: breaking changes, years of TC work, ecosystem-wide migration costs, and competitive fragmentation while the draft is in flight. The OASIS MQTT TC spent roughly four years taking MQTT 5.0 from proposal to ratification. Asking the committee to open a "6.0" track is asking them to sign up for another four years — before they have read a single sentence of the proposal.

This resistance is not irrational. MQTT 5.0 was explicitly designed with User Properties, an extensible property ID space, and a reserved property range precisely to enable future extensions *without* requiring a version bump. Members of the TC will read "MQTT 6.0" and their first question will be: "Why couldn't this be done with User Properties and a profile?" If the answer to that question is not airtight, the proposal dies in the first review session.

The external review is correct: the current framing triggers maximum TC resistance before the technical merit of the proposal gets a fair hearing. The fix is not to improve the technical arguments — those are already solid, as the rebuttals document demonstrates — it is to change the frame entirely so the committee evaluates the proposal on its merits rather than its version number.

---

## 2. The Reframe: Two-Track Positioning

The core insight from the external review is that the proposal contains two separable things that should be presented through two separate lenses:

**Track 1 — For OASIS TC submission:** Position the proposal as the **MQTT Reliable Secure Streams Profile (MQTT-RSSP)** — an interoperability profile fully compatible with MQTT 3.1.1 and MQTT 5.0, requiring no changes to the broker wire protocol, implemented via User Properties and payload conventions that any conformant MQTT 5.0 broker can forward without modification.

**Track 2 — For HiveMQ product:** The broker-side extensions — native `$queue/` persistence, Virtual FETCH enforcement, SQMC consumer mode arbitration, and Epoch management — are HiveMQ's above-and-beyond implementation of the profile. They are not required for MQTT-RSSP profile conformance; they are value-added broker behaviors that HiveMQ ships as a competitive differentiator.

This two-track structure maps directly onto the existing lift documents. The "application layer profile" in Option A and Option C is exactly MQTT-RSSP. The MQTT 6.0 transport extension spec becomes the HiveMQ-specific broker optimization layer. What gets submitted to OASIS is the profile; what HiveMQ ships as a product is the native broker support for that profile.

The framing shift is not cosmetic. Under the MQTT-RSSP frame:

- A client running MQTT-RSSP on a Mosquitto broker today — using only User Properties and payload conventions — is a conformant implementation
- A client running MQTT-RSSP on HiveMQ with native `$queue/` support gets better performance, lower latency, and stronger durability guarantees — but is still running the same profile
- The TC is being asked to ratify an interoperability spec for a pattern that already exists in production (Sparkplug B sequence numbers, application-layer idempotency tables, session resume logic), not to approve a new protocol version

**The compatibility statement to include in every document:**

> "This profile introduces no changes to the MQTT wire protocol and is fully interoperable with existing MQTT 3.1.1 and MQTT 5.0 brokers."

That single sentence removes approximately 70% of the standard committee objections before the technical review begins.

---

## 3. Answering the Two Fatal Questions

Two questions will be raised in the first TC review session. If they are not answered concisely and confidently, they become blockers that derail the entire proposal. Do not bury the answers in appendices — put them in the abstract.

### Q1: "Why isn't TLS already sufficient?"

TLS protects the transport hop — client to broker to subscriber. It terminates at the broker. In a multi-tenant cloud broker, a federated bridge deployment, or any infrastructure where the broker is operated by a third party, TLS provides no protection against the broker itself. The broker decrypts, reads, re-encrypts, and forwards. For semiconductor equipment vendors shipping process recipes to tools on a customer's factory floor, the cloud broker IS an attacker surface — not a hypothetical one, a contractual one: the broker operator's SLA explicitly disclaims liability for payload content.

MQTT-RSSP payload encryption (Properties 0x3A-0x3C) protects the data across the entire messaging lifecycle, not just the network path. The broker forwards an opaque payload with metadata. It cannot read process parameters, safety-critical commands, or proprietary control sequences. The pattern is precise: TLS = network confidentiality; MQTT-RSSP = data confidentiality. TLS and MQTT-RSSP are complementary, not redundant.

### Q2: "Who manages the keys?"

The profile defines only how encrypted payloads reference keys: a `key_id`, an `algorithm` identifier, and a `key_version`. Key distribution, rotation, and revocation are explicitly out of scope. Deployments integrate with whatever key management they already operate — device provisioning systems, enterprise PKI, HSMs, SPIFFE/SPIRE workload identity. The same design pattern as TLS SNI: the protocol references an identity, the PKI manages it. MQTT-RSSP does not introduce a new key management problem; it introduces a standard envelope for referencing keys from whatever system already manages them.

---

## 4. Feature-by-Feature TC Positioning

Each feature needs a two-to-three sentence TC pitch that connects it to a concrete, documented ecosystem problem. Abstract arguments about reliability do not move standards committees; specific evidence of fragmentation does.

**Stream Sequence Numbers (Property 0x30)**

This standardizes the single most-reimplemented pattern in IIoT MQTT deployments. Every Eclipse Sparkplug B deployment already implements a 64-bit `seq` field in protobuf payloads for exactly this purpose — gap detection and ordered delivery. MQTT-RSSP moves the sequence number from a payload-embedded convention into a standard envelope property so any client library can implement it once, interoperably, without a custom serialization format.

**Stream Epoch (Property 0x35)**

A simple replay protection mechanism across device restarts and broker failovers, analogous to TLS session tickets. The Epoch is a monotonically increasing uint16 that subscribers use to detect and discard stale replays and to know when their local idempotency state is no longer valid. It requires no broker coordination beyond incrementing a counter on state discontinuity events; a single-node Mosquitto instance can implement it correctly. Zero broker architecture changes required.

**Payload Encryption (Properties 0x3A-0x3C)**

Three optional User Properties constitute a broker-transparent encrypted envelope. No broker changes. No key material in the protocol. Solves the multi-tenant broker trust problem that every large industrial MQTT customer has raised independently — the problem that today forces them to implement ad-hoc payload encryption with no standard key-reference format, making interoperability between equipment vendors impossible.

**SQMC (Single-Queue Multi-Consumer)**

This is the most controversial feature; it must be framed carefully. Do not present it as a QoS replacement. Present it as application-level verifiable delivery confirmation for safety-critical command streams. MQTT QoS 1 and QoS 2 guarantee delivery semantics at the transport layer. SQMC provides cryptographic proof — via the sequence number and acknowledgment protocol — that the correct subscriber received and validated the correct message. This is required for SECS/GEM S2F21 process start command handshakes, IEC 61850 grid protection relay sequences, and other safety-critical applications where "I sent it and the broker said OK" is not a sufficient guarantee.

---

## 5. What to Avoid Saying

Language matters in TC submissions. Certain phrases activate pattern-matching against past standards failures and produce reflexive resistance before the technical argument is heard. For each phrase to avoid, there is a preferred alternative that conveys the same technical content without the political cost.

| Avoid | Use instead |
|---|---|
| "MQTT 6.0" | "MQTT Reliable Secure Streams Profile (MQTT-RSSP)" |
| "major protocol revision" | "interoperability profile" |
| "new packet type" | "payload convention / User Property extension" |
| "breaking change" | "additive, opt-in extension" |
| "broker encryption support" | "broker-transparent security" |
| "we need a new version" | "we are standardizing patterns already in production" |
| "replaces MQTT 5.0 features" | "complements existing MQTT 5.0 semantics" |

The last two are particularly important. The argument "we are standardizing patterns already in production" is both true and persuasive: Sparkplug B sequence numbers, application-layer idempotency tables, and session resume logic are in production at scale today. MQTT-RSSP is a standardization of existing practice, not a proposal to change practice.

---

## 6. Relationship to Existing Lift Documents

The MQTT-RSSP reframe maps cleanly onto the lift document structure. Under the Option C architecture:

- **MQTT 6.0 transport extension** (broker obligations: Property 0x30/0x35 assignment, `$queue/` persistence, Virtual FETCH enforcement, SQMC arbitration) becomes the HiveMQ product layer — the above-and-beyond broker implementation that makes everything work natively, but is not required for profile conformance.

- **MQTT Stream 1.0 application protocol** (client obligations: gap detection state machine, epoch resync procedure, high-watermark persistence, exactly-once workflow) becomes the normative content of the MQTT-RSSP OASIS submission.

In other words: what gets submitted to OASIS is essentially the MQTT Stream 1.0 spec from lift-option-c, rebranded as MQTT-RSSP and framed as a profile over MQTT 5.0 rather than a layer above MQTT 6.0. The broker-side primitive requirements (Property 0x30 assignment, `$queue/` persistence) become SHOULD/RECOMMENDED behaviors for brokers that wish to natively support MQTT-RSSP, rather than MUST requirements for a new protocol level.

This is not a retreat from the technical proposal. The technical content is identical. The OASIS submission surface is dramatically smaller, the risk profile for TC reviewers is dramatically lower, and the path to ratification is dramatically shorter.

---

## 7. Estimated TC Acceptance Probability

Based on the external review's assessment and the positioning analysis above:

| Framing | Acceptance Probability | Why |
|---|---|---|
| "MQTT 6.0 protocol revision" | ~10-15% | Triggers maximum resistance before technical merit is heard; implies breaking changes, years of TC work, and ecosystem disruption; competes with TC members' investment in MQTT 5.0 |
| "MQTT Reliable Secure Streams Profile (MQTT-RSSP)" | ~50-70% | Profile framing signals low risk; broker transparency removes ecosystem disruption concerns; standardizing documented fragmentation (Sparkplug, ad-hoc sequence numbers) is a recognized TC mandate |

The delta between these two outcomes is not in the technical proposal — the proposal is sound in either frame. The delta is entirely in how the TC perceives its own workload and risk exposure. MQTT-RSSP asks the TC to ratify an interoperability profile for patterns already in production. MQTT 6.0 asks the TC to approve a new protocol version. These are structurally different asks with structurally different acceptance rates.

The ~50-70% range under MQTT-RSSP framing is conditional on answering the two fatal questions (TLS sufficiency, key management) concisely in the abstract, and on keeping the payload encryption feature clearly marked as optional. If SQMC is submitted as a separate follow-on proposal rather than bundled in the initial submission, the acceptance probability for the core profile (Stream Sequence + Epoch + payload encryption envelope) likely rises above 70%.

---

## 8. Recommended Next Steps

1. **Rename all external-facing documents** to use "MQTT-RSSP" or "MQTT Reliable Secure Streams Profile" as the primary identifier. Keep "MQTT 6.0" as a parenthetical for internal reference only.

2. **Add the compatibility statement** ("This profile introduces no changes to the MQTT wire protocol...") to the abstract or first paragraph of every document intended for TC review.

3. **Prepend the TLS question answer** to the executive summary before the feature list. TC reviewers will ask it; answer it before they need to.

4. **Consider a two-phase submission**: Phase 1 covers Stream Sequence Numbers, Stream Epoch, and the payload encryption envelope (the broker-transparent features). Phase 2 covers SQMC. The Phase 1 submission has a cleaner "broker transparency" story and a higher acceptance probability. SQMC requires broker-side enforcement and is the most controversial feature; letting Phase 1 establish credibility before introducing it is strategically sound.

5. **Align the lift documents**: Update lift-option-c.md to reflect that "MQTT Stream 1.0" IS the MQTT-RSSP OASIS submission. The naming should be consistent before the TC review package is assembled.
