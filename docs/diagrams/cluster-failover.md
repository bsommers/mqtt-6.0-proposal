# Cluster Failover & Epoch Management Diagrams

> **Architecture note:** HiveMQ is a **masterless, shared-nothing cluster** — all nodes are peers with no permanent leaders and no consensus protocol (Raft/Paxos). Sequence monotonicity is guaranteed by a **Distributed Sequence Counter** (atomic CAS) in HiveMQ's replication data grid, not by sticky routing to a leader node.

---

## 1. Masterless Cluster — Any Node Sequences Any Publish (C4)

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','secondaryColor':'#424242','tertiaryColor':'#FFF9C4'}}}%%
C4Context
    title HiveMQ v6.0 — Masterless Cluster (all nodes are peers)

    Person(pub, "Publisher")
    Person(con, "Consumer")

    System_Boundary(cluster, "HiveMQ Cluster — no leaders, no routing constraints") {
        System(n1, "Node 1", "Peer node · handles any publish or FETCH")
        System(n2, "Node 2", "Peer node · handles any publish or FETCH")
        System(n3, "Node 3", "Peer node · handles any publish or FETCH")
        System(counter, "Distributed Seq Counter", "Cluster data grid · atomic CAS per $queue/")
    }

    Rel(pub, n1, "PUBLISH $queue/line", "any node")
    Rel(pub, n2, "PUBLISH $queue/events", "any node")
    Rel(con, n3, "FETCH $queue/line", "any node")
    Rel(n1, counter, "CAS increment → claim Seq N", "")
    Rel(n2, counter, "CAS increment → claim Seq N", "")
    Rel(n1, n2, "Replicate message+Seq", "data grid")
    Rel(n2, n3, "Replicate message+Seq", "data grid")

    UpdateLayoutConfig($c4ShapeInRow="4", $c4BoundaryInRow="1")
```

---

## 2. Sequence Assignment — Distributed Counter (No Leader Required)

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#FFD600','actorBorder':'#212121','actorTextColor':'#212121','noteBkgColor':'#FFF9C4','noteTextColor':'#212121','activationBkgColor':'#FFF9C4','signalColor':'#212121','signalTextColor':'#212121'}}}%%
sequenceDiagram
    participant P as Publisher
    participant N as Any Node
    participant C as Cluster Counter
    participant R as Replica Nodes

    P->>N: PUBLISH $queue/line payload
    N->>C: CAS increment → claim Seq=1001
    C-->>N: Seq=1001 confirmed (atomic)
    N->>N: Persist msg+Seq=1001 locally
    par quorum write
        N->>R: Replicate Seq=1001
        R-->>N: ACK (quorum met)
    end
    N-->>P: PUBACK Seq=1001
    Note over N,C: Any other node concurrently claiming\nwill get Seq=1002 — no conflict
```

---

## 3. Node Crash — No Leader Election Required

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#FFD600','actorBorder':'#212121','actorTextColor':'#212121','noteBkgColor':'#FFF9C4','noteTextColor':'#212121','activationBkgColor':'#FFF9C4','signalColor':'#212121','signalTextColor':'#212121'}}}%%
sequenceDiagram
    participant P as Publisher
    participant A as Node A
    participant C as Cluster Counter
    participant B as Node B (peer)

    P->>A: PUBLISH $queue/line
    A->>C: CAS → Seq=1099 claimed
    A->>A: Persist Seq=1099 (quorum write to B)
    A-->>P: PUBACK 1099
    A-xC: Node A crashes
    Note over B: Node A gone · B already has\nSeq=1099 (quorum write) ✓\nEpoch unchanged · no resync needed
    P->>B: PUBLISH $queue/line (reconnects to B)
    B->>C: CAS → Seq=1100 claimed
    B-->>P: PUBACK 1100
```

---

## 4. Partition Event — When Epoch Increments

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#FFD600','actorBorder':'#212121','actorTextColor':'#212121','noteBkgColor':'#FFF9C4','noteTextColor':'#212121','activationBkgColor':'#FFF9C4','signalColor':'#212121','signalTextColor':'#212121'}}}%%
sequenceDiagram
    participant P as Publisher
    participant A as Node A (partitioned)
    participant B as Node B (surviving)
    participant C as Cluster Counter

    Note over A,B: Network partition splits cluster
    P->>A: PUBLISH (partition side)
    A->>A: Cannot reach quorum for CAS
    A-->>P: PUBACK rejected (0x97 Quota Exceeded)
    Note over A: A refuses to claim Seq\n— CAS requires quorum

    Note over A,B: Partition heals
    B->>C: Counter state verified — epoch intact
    Note over B: If counter quorum was lost:\nEpoch++ · notify all consumers\n\nIf counter quorum survived:\nEpoch unchanged · no resync needed
```

---

## 5. Failure Outcomes Decision Tree

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','edgeLabelBackground':'#FFFFFF'}}}%%
flowchart TD
    FAIL["Node crash or\npartition heals"] --> Q1{"Quorum write\ncompleted for\nall in-flight msgs?"}

    Q1 -->|Yes| OK["Same Epoch\nPeers have full data\nNo client action"]
    Q1 -->|No — orphaned Seq| Q2{"Counter quorum\nsurvived?"}

    Q2 -->|Yes| GAP["Gap in sequence range\nEpoch unchanged\nConsumers notified of\nmissing Seq range"]
    Q2 -->|No — partition split counter| EPOCH["Epoch++\nBroadcast new Epoch\nClients full-resync"]

    classDef ok fill:#FFD600,stroke:#212121,color:#212121
    classDef warn fill:#9E9E9E,stroke:#212121,color:#212121
    classDef crit fill:#212121,stroke:#FFD600,color:#FFD600

    class OK ok
    class GAP warn
    class EPOCH crit
```

---

## 6. Client Reconnect Decision Tree

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','edgeLabelBackground':'#FFFFFF'}}}%%
flowchart TD
    RC["Client reconnects\nlast-seq=N epoch=E\n(to any peer node)"] --> E{"Epoch\nmatches?"}

    E -->|Yes| S{"Seq N in\ndata grid?"}
    E -->|No – incremented| RESET["CONNACK new Epoch\nClient clears HWM\nFull resync from Seq=0"]

    S -->|Yes| RESUME["Resume from N+1\nNo disruption"]
    S -->|No – orphaned Seq| GAP["Resume from earliest\nFlag gap range to client\nEpoch unchanged"]

    classDef ok fill:#FFD600,stroke:#212121,color:#212121
    classDef warn fill:#9E9E9E,stroke:#212121,color:#212121
    classDef crit fill:#212121,stroke:#FFD600,color:#FFD600

    class RESUME ok
    class GAP warn
    class RESET crit
```

---

## 7. Tiered Storage

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','clusterBkg':'#FFF9C4'}}}%%
graph LR
    subgraph Broker
        HOT["HOT\nRAM / NVMe\n~1k msgs · sub-ms"]
        WARM["WARM\nNVMe SSD\n~1M msgs · ~1ms"]
    end
    COLD["COLD\nObject Store\nunlimited · ~100ms"]

    PUB["Publisher"] -->|write| HOT
    HOT -->|evict| WARM
    WARM -->|evict| COLD

    CON1["Consumer\n(recent)"] -->|FETCH| HOT
    CON2["Consumer\n(backlog)"] -->|FETCH| WARM
    AUD["Audit / Replay"] -->|read| COLD

    classDef hot fill:#FFD600,stroke:#212121,color:#212121
    classDef warm fill:#9E9E9E,stroke:#212121,color:#212121
    classDef cold fill:#424242,stroke:#212121,color:#FFFFFF
    classDef actor fill:#FFFFFF,stroke:#212121,color:#212121

    class HOT hot
    class WARM warm
    class COLD cold
    class PUB,CON1,CON2,AUD actor
```

---

## 8. Epoch Timeline

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121'}}}%%
timeline
    title $queue/production_line · Epoch History
    section Epoch 1
        Seq 1–5000  : All nodes healthy · quorum writes succeed
        Seq 5001    : Node A crashes · quorum on B+C → data intact
    section Epoch 1 (cont.)
        Seq 5001+   : B+C continue · Epoch unchanged (quorum survived)
    section Epoch 2 (partition event)
        Counter reset : Network partition split counter quorum\nSurviving side increments Epoch · clients resync
        Seq 0+      : New epoch · all consumers reconcile
```
