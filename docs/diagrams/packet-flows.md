# MQTT v6.0 Packet Flow Diagrams

---

## 1. Connection Negotiation

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#FFD600','actorBorder':'#212121','actorTextColor':'#212121','noteBkgColor':'#FFF9C4','noteTextColor':'#212121','activationBkgColor':'#FFF9C4','signalColor':'#212121','signalTextColor':'#212121','labelBoxBkgColor':'#FFF9C4'}}}%%
sequenceDiagram
    participant C as Client
    participant B as Broker

    C->>B: CONNECT level=6 mqtt-ext=v6.0 last-seq=1234 epoch=2
    alt v6.0 broker
        B-->>C: CONNACK 0x00 mqtt-ext=v6.0 epoch=2 limit=5000KB/s
    else v5.0 + extension
        B-->>C: CONNACK 0x84
        C->>B: CONNECT level=5 mqtt-ext=v6.0
        B-->>C: CONNACK 0x00 mqtt-ext=v6.0
    else legacy v5.0
        B-->>C: CONNACK 0x00
        Note over C: fallback — no v6 features
    end
```

---

## 2. Publish → Sequence Assignment (masterless)

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#FFD600','actorBorder':'#212121','actorTextColor':'#212121','noteBkgColor':'#FFF9C4','noteTextColor':'#212121','activationBkgColor':'#FFF9C4','signalColor':'#212121','signalTextColor':'#212121'}}}%%
sequenceDiagram
    participant P as Publisher
    participant N as Any Peer Node
    participant C as Cluster Counter
    participant R as Replica Nodes

    P->>N: PUBLISH QoS=1 $queue/line payload
    N->>C: CAS increment → Seq=1001 claimed (atomic)
    N->>N: Persist Seq=1001 Epoch=2 to NVMe
    par quorum write
        N->>R: Replicate Seq=1001
        R-->>N: ACK
    end
    N-->>P: PUBACK Seq=1001
```

---

## 3. Native FETCH (Protocol Level 6)

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#FFD600','actorBorder':'#212121','actorTextColor':'#212121','noteBkgColor':'#FFF9C4','noteTextColor':'#212121','activationBkgColor':'#FFF9C4','signalColor':'#212121','signalTextColor':'#212121'}}}%%
sequenceDiagram
    participant C as Consumer
    participant B as Broker

    C->>B: SUBSCRIBE $queue/line v6-semantics=competing
    B-->>C: SUBACK

    C->>B: FETCH Type=16 batch=10 last-seq=995
    B-->>C: PUBLISH Seq=996 Epoch=2
    B-->>C: PUBLISH Seq=997 Epoch=2
    B-->>C: PUBLISH Seq=998 Epoch=2
    Note right of B: …up to 10 messages
    C-->>B: PUBACK 996..998
    Note left of C: HWM → 998
    C->>B: FETCH batch=10 last-seq=998
```

---

## 4. Virtual FETCH (Compat Mode)

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#424242','actorBorder':'#212121','actorTextColor':'#FFFFFF','noteBkgColor':'#FFF9C4','noteTextColor':'#212121','activationBkgColor':'#FFF9C4','signalColor':'#212121','signalTextColor':'#212121'}}}%%
sequenceDiagram
    participant C as Consumer (shim)
    participant B as Broker + Extension

    C->>B: PUBLISH $SYS/queues/line/fetch v6-batch=10 last-seq=995
    B->>B: Extension reads 10 msgs from $queue/line
    B-->>C: PUBLISH $queue/line v6-seq=996 v6-epoch=2
    B-->>C: PUBLISH v6-seq=997
    Note right of B: …up to 10 messages
    C-->>B: PUBACK 996..997
    C->>B: next fetch request
```

---

## 5. Competing Consumer — Failover

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#FFD600','actorBorder':'#212121','actorTextColor':'#212121','noteBkgColor':'#FFF9C4','noteTextColor':'#212121','activationBkgColor':'#FFF9C4','signalColor':'#212121','signalTextColor':'#212121'}}}%%
sequenceDiagram
    participant B as Broker
    participant C1 as Consumer 1
    participant C2 as Consumer 2
    participant C3 as Consumer 3

    B->>C1: PUBLISH Seq=100 [locked]
    B->>C2: PUBLISH Seq=101 [locked]
    B->>C3: PUBLISH Seq=102 [locked]
    C2-->>B: PUBACK 101 ✓
    C3-->>B: PUBACK 102 ✓
    C1-xB: DISCONNECT (no PUBACK)
    B->>B: unlock Seq=100
    B->>C2: PUBLISH Seq=100 [re-delivered]
    C2-->>B: PUBACK 100 ✓
```

---

## 6. Exclusive Consumer — Hot-Standby

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#FFD600','actorBorder':'#212121','actorTextColor':'#212121','noteBkgColor':'#FFF9C4','noteTextColor':'#212121','activationBkgColor':'#FFF9C4','signalColor':'#212121','signalTextColor':'#212121'}}}%%
sequenceDiagram
    participant B as Broker
    participant C1 as Primary
    participant C2 as Standby

    B->>C1: PUBLISH Seq=200
    B->>C1: PUBLISH Seq=201
    B--xC2: (no delivery)
    C1-->>B: PUBACK 200..201
    C1-xB: DISCONNECT
    B->>B: promote C2 → Primary
    B->>C2: PUBLISH Seq=202
    C2-->>B: PUBACK 202
```

---

## 7. Gap Detection + Exactly-Once

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#FFD600','actorBorder':'#212121','actorTextColor':'#212121','noteBkgColor':'#FFF9C4','noteTextColor':'#212121','activationBkgColor':'#FFF9C4','signalColor':'#212121','signalTextColor':'#212121'}}}%%
sequenceDiagram
    participant B as Broker
    participant C as Consumer

    B->>C: Seq=500 → process · HWM=500
    B->>C: Seq=501 → process · HWM=501
    Note over B,C: Seq=502 lost in transit
    B->>C: Seq=503 · GAP ALERT (502 missing) · HWM=503
    B->>C: Seq=502 [QoS=1 retry]
    Note over C: 502 ≤ HWM → DISCARD
    C-->>B: PUBACK 502 (discarded)
```

---

## 8. Epoch Reset on Cluster Failover

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#FFD600','actorBorder':'#212121','actorTextColor':'#212121','noteBkgColor':'#FFF9C4','noteTextColor':'#212121','activationBkgColor':'#FFF9C4','signalColor':'#212121','signalTextColor':'#212121'}}}%%
sequenceDiagram
    participant C as Consumer
    participant A as Node A (peer)
    participant B as Node B (peer)

    C->>A: FETCH last-seq=5000 epoch=1
    A-->>C: PUBLISH Seq=5001 Epoch=1 · HWM=5001
    A-xC: Partition — quorum for counter lost · B isolated

    C->>B: CONNECT last-seq=5001 epoch=1
    B->>B: Counter quorum lost during partition\nEpoch incremented to 2
    B-->>C: CONNACK Epoch=2
    Note over C: clear HWM · full resync
    C->>B: FETCH last-seq=0 epoch=2
    B-->>C: PUBLISH Seq=1 Epoch=2
```
