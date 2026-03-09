# MQTT v6.0 Packet Flow Diagrams

---

## 1. v6.0 Connection Negotiation

```mermaid
sequenceDiagram
    participant C as Client
    participant B as Broker (v6.0)

    Note over C,B: Connection Handshake
    C->>B: CONNECT<br/>Protocol Level: 6<br/>User Property: mqtt-ext=v6.0<br/>User Property: v6-last-seq=1234<br/>User Property: v6-epoch=2

    alt Broker supports v6.0
        B-->>C: CONNACK (0x00 Success)<br/>User Property: mqtt-ext=v6.0<br/>Stream Epoch (0x35): 2<br/>Throughput Limit (0x41): 5000 KB/s
        Note over C,B: v6.0 mode active
    else Broker is v5.0 only
        B-->>C: CONNACK (0x84 Unsupported Protocol)<br/>[no v6.0 properties]
        C->>B: CONNECT (retry)<br/>Protocol Level: 5<br/>User Property: mqtt-ext=v6.0
        B-->>C: CONNACK (0x00 Success)<br/>User Property: mqtt-ext=v6.0
        Note over C,B: Compatibility Mode active
    else Legacy broker (no v6 extension)
        B-->>C: CONNACK (0x00 Success)<br/>[no v6.0 properties]
        Note over C,B: Fallback to pure v5.0
    end
```

---

## 2. Publish to `$queue/` — Sequence Assignment

```mermaid
sequenceDiagram
    participant P as Publisher
    participant B as Broker (Queue Leader)
    participant R as Replica Node

    P->>B: PUBLISH QoS=1<br/>Topic: $queue/production_line<br/>Payload: sensor_data_42

    B->>B: Assign Stream Sequence: 1001<br/>Stamp Stream Epoch: 2<br/>Write to persistent storage

    par Replicate
        B->>R: Replicate (Seq=1001, Epoch=2)
    end

    B-->>P: PUBACK (Seq=1001)
    Note over P,B: Publisher receives ACK only<br/>after durable write + replication

    B->>P: (next publish ready)
```

---

## 3. Native FETCH Flow (Protocol Level 6)

```mermaid
sequenceDiagram
    participant C as Consumer
    participant B as Broker

    Note over C,B: Consumer subscribes
    C->>B: SUBSCRIBE<br/>Topic: $queue/production_line<br/>User Property: v6-semantics=competing<br/>User Property: v6-group=factory_workers
    B-->>C: SUBACK

    Note over C,B: Consumer pulls messages
    C->>B: FETCH (Type 16)<br/>Packet ID: 42<br/>Batch Size (0x42): 10<br/>Last Received Seq (0x30): 995<br/>Topic: $queue/production_line

    B->>B: Retrieve next 10 messages<br/>starting from Seq 996

    B-->>C: PUBLISH QoS=1<br/>Seq (0x30): 996<br/>Epoch (0x35): 2<br/>Payload: msg_996
    B-->>C: PUBLISH QoS=1 Seq=997 ...
    B-->>C: PUBLISH QoS=1 Seq=998 ...
    Note over B,C: ... (up to 10 messages)

    C-->>B: PUBACK (996)
    C-->>B: PUBACK (997)
    C-->>B: PUBACK (998)
    Note over C: Update High-Watermark to 998

    Note over C,B: Consumer requests next batch
    C->>B: FETCH Batch=10 Last-Seq=998
```

---

## 4. Virtual FETCH Flow (Compatibility Mode — v5.0 Broker + Extension)

```mermaid
sequenceDiagram
    participant C as Consumer (v6 Shim)
    participant B as Broker (v5.0 + v6 Extension)

    C->>B: PUBLISH QoS=1<br/>Topic: $SYS/queues/production_line/fetch<br/>User Property: v6-batch=10<br/>User Property: v6-last-seq=995

    B->>B: Extension intercepts<br/>Reads 10 messages from<br/>$queue/production_line store

    B-->>C: PUBLISH QoS=1<br/>Topic: $queue/production_line<br/>User Property: v6-seq=996<br/>User Property: v6-epoch=2<br/>Payload: msg_996
    B-->>C: PUBLISH (v6-seq=997) ...
    Note over B,C: ... up to 10 messages

    C-->>B: PUBACK (996)
    C->>B: (next fetch request)
```

---

## 5. Competing Consumer — Message Locking and Failover

```mermaid
sequenceDiagram
    participant B as Broker
    participant C1 as Consumer 1
    participant C2 as Consumer 2
    participant C3 as Consumer 3

    Note over C1,C3: All subscribe with v6-semantics=competing

    B->>C1: PUBLISH Seq=100 [LOCKED to C1]
    B->>C2: PUBLISH Seq=101 [LOCKED to C2]
    B->>C3: PUBLISH Seq=102 [LOCKED to C3]

    C2-->>B: PUBACK Seq=101 ✓ [LOCK RELEASED]
    C3-->>B: PUBACK Seq=102 ✓ [LOCK RELEASED]

    Note over C1: Consumer 1 crashes!
    C1-xB: [DISCONNECT - no PUBACK for Seq=100]

    B->>B: Lock timeout / disconnect detected<br/>Release lock on Seq=100

    B->>C2: PUBLISH Seq=100 [RE-DELIVERED, LOCKED to C2]
    C2-->>B: PUBACK Seq=100 ✓
```

---

## 6. Exclusive Consumer — Hot-Standby Failover

```mermaid
sequenceDiagram
    participant B as Broker
    participant C1 as Primary Consumer
    participant C2 as Hot Standby

    Note over B,C2: Both subscribe with v6-semantics=exclusive
    Note over B,C1: C1 subscribed first → Primary

    B->>C1: PUBLISH Seq=200 (active delivery)
    B->>C1: PUBLISH Seq=201
    B-xC2: (Standby — no messages sent)

    C1-->>B: PUBACK 200
    C1-->>B: PUBACK 201

    Note over C1: Primary disconnects!
    C1-xB: DISCONNECT

    B->>B: Promote C2 to Primary<br/>Resume from Seq=202

    B->>C2: PUBLISH Seq=202 (now Primary)
    B->>C2: PUBLISH Seq=203
    C2-->>B: PUBACK 202
```

---

## 7. Gap Detection and Exactly-Once Processing

```mermaid
sequenceDiagram
    participant B as Broker
    participant C as Consumer (with High-Watermark DB)

    B->>C: PUBLISH Seq=500
    C->>C: 500 > HWM(499) → PROCESS<br/>Update HWM=500

    B->>C: PUBLISH Seq=501
    C->>C: 501 > HWM(500) → PROCESS<br/>Update HWM=501

    Note over B,C: Network glitch — Seq 502 dropped by broker

    B->>C: PUBLISH Seq=503
    C->>C: 503 > HWM(501) BUT gap detected!<br/>Expected 502, got 503<br/>ALERT: missing Seq=502
    C->>C: PROCESS Seq=503<br/>Update HWM=503

    Note over B,C: Broker retries (QoS=1 redelivery)
    B->>C: PUBLISH Seq=502 [redelivered]
    C->>C: 502 <= HWM(503)<br/>DUPLICATE → PUBACK but DISCARD
    C-->>B: PUBACK (duplicate discarded)
```

---

## 8. Epoch Reset During Cluster Failover

```mermaid
sequenceDiagram
    participant C as Consumer
    participant A as Node A (former leader)
    participant B as Node B (new leader)

    Note over C,A: Normal operation
    C->>A: FETCH Last-Seq=5000 Epoch=1
    A-->>C: PUBLISH Seq=5001 Epoch=1
    C-->>A: PUBACK 5001, HWM=5001

    Note over A: Node A crashes!
    Note over A,B: Replication lag: Node B has up to Seq=4998 only

    C->>B: CONNECT v6-last-seq=5001 v6-epoch=1
    B->>B: Check queue: highest replicated Seq=4998<br/>Client says 5001 — EPOCH RESET required

    B-->>C: CONNACK Stream Epoch=2
    Note over C: Epoch changed (1 → 2)<br/>Clear idempotency table<br/>Perform full resync

    C->>B: FETCH Last-Seq=0 Epoch=2
    B-->>C: PUBLISH Seq=1 Epoch=2 (queue rebuilt)
    Note over B,C: Consumer resumes from new epoch
```
