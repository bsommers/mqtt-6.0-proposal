# Cluster Failover & Epoch Management Diagrams

> **Architecture note:** HiveMQ is a **masterless, shared-nothing cluster** — all nodes are peers with no permanent leaders and no consensus protocol (Raft/Paxos). Sequence monotonicity is guaranteed by a **Distributed Sequence Counter** (atomic CAS) in HiveMQ's replication data grid, not by sticky routing to a leader node.

---

## 1. Masterless Cluster — Any Node Sequences Any Publish (C4)

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFFFFF','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','secondaryColor':'#FFFFFF','tertiaryColor':'#FFFFFF'}}}%%
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

## 2. Sequence Assignment — Distributed Counter

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFFFFF','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#FFFFFF','actorBorder':'#212121','actorTextColor':'#212121','noteBkgColor':'#FFD600','noteTextColor':'#212121','activationBkgColor':'#F5F5F5','signalColor':'#212121','signalTextColor':'#212121'}}}%%
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
    Note over N,C: Concurrent publish on any node gets Seq=1002
```

---

## 3. Node Crash — No Election Required

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFFFFF','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#FFFFFF','actorBorder':'#212121','actorTextColor':'#212121','noteBkgColor':'#FFD600','noteTextColor':'#212121','activationBkgColor':'#F5F5F5','signalColor':'#212121','signalTextColor':'#212121'}}}%%
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
    Note over B: B already has Seq=1099 via quorum write<br/>Epoch unchanged — no resync needed
    P->>B: PUBLISH $queue/line (reconnects to B)
    B->>C: CAS → Seq=1100 claimed
    B-->>P: PUBACK 1100
```

---

## 4. Partition Event — When Epoch Increments

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFFFFF','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#FFFFFF','actorBorder':'#212121','actorTextColor':'#212121','noteBkgColor':'#FFD600','noteTextColor':'#212121','activationBkgColor':'#F5F5F5','signalColor':'#212121','signalTextColor':'#212121'}}}%%
sequenceDiagram
    participant P as Publisher
    participant A as Node A (partitioned)
    participant B as Node B (surviving)
    participant C as Cluster Counter

    Note over A,B: Network partition splits cluster
    P->>A: PUBLISH (partition side)
    A->>A: Cannot reach quorum for CAS
    A-->>P: PUBLISH rejected — 0x97 Quota Exceeded
    Note over A: CAS refused — quorum unreachable

    Note over A,B: Partition heals
    B->>C: Counter state verified
    Note over B: Quorum lost → Epoch++, notify consumers<br/>Quorum intact → Epoch unchanged
```

---

## 5. Failure Outcomes Decision Tree

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFFFFF','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','edgeLabelBackground':'#FFFFFF'}}}%%
flowchart TD
    FAIL["Node crash or<br/>partition heals"] --> Q1{"Quorum write<br/>completed for<br/>all in-flight msgs?"}

    Q1 -->|Yes| OK["Same Epoch<br/>Peers have full data<br/>No client action"]
    Q1 -->|No — orphaned Seq| Q2{"Counter quorum<br/>survived?"}

    Q2 -->|Yes| GAP["Gap in sequence range<br/>Epoch unchanged<br/>Consumers notified of<br/>missing Seq range"]
    Q2 -->|No — partition split counter| EPOCH["Epoch++<br/>Broadcast new Epoch<br/>Clients full-resync"]

    classDef highlight fill:#FFD600,stroke:#212121,color:#212121
    classDef critical fill:#212121,stroke:#212121,color:#FFFFFF

    class OK highlight
    class EPOCH critical
```

---

## 6. Client Reconnect Decision Tree

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFFFFF','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','edgeLabelBackground':'#FFFFFF'}}}%%
flowchart TD
    RC["Client reconnects<br/>last-seq=N epoch=E<br/>(any peer node)"] --> E{"Epoch<br/>matches?"}

    E -->|Yes| S{"Seq N in<br/>data grid?"}
    E -->|No — incremented| RESET["CONNACK new Epoch<br/>Client clears HWM<br/>Full resync from Seq=0"]

    S -->|Yes| RESUME["Resume from N+1<br/>No disruption"]
    S -->|No — orphaned Seq| GAP["Resume from earliest<br/>Flag gap range to client<br/>Epoch unchanged"]

    classDef highlight fill:#FFD600,stroke:#212121,color:#212121
    classDef critical fill:#212121,stroke:#212121,color:#FFFFFF

    class RESUME highlight
    class RESET critical
```

---

## 7. Tiered Storage

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFFFFF','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','clusterBkg':'#F5F5F5'}}}%%
graph LR
    subgraph Broker
        HOT["HOT<br/>RAM / NVMe<br/>~1k msgs · sub-ms"]
        WARM["WARM<br/>NVMe SSD<br/>~1M msgs · ~1ms"]
    end
    COLD["COLD<br/>Object Store<br/>unlimited · ~100ms"]

    PUB["Publisher"] -->|write| HOT
    HOT -->|evict| WARM
    WARM -->|evict| COLD

    CON1["Consumer<br/>(recent)"] -->|FETCH| HOT
    CON2["Consumer<br/>(backlog)"] -->|FETCH| WARM
    AUD["Audit / Replay"] -->|read| COLD

    classDef highlight fill:#FFD600,stroke:#212121,color:#212121
    class HOT highlight
```

---

## 8. Epoch Timeline

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFFFFF','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121'}}}%%
timeline
    title $queue/production_line · Epoch History
    section Epoch 1
        Seq 1–5000  : All nodes healthy · quorum writes succeed
        Node A crash : Quorum on B+C intact · data preserved · Epoch unchanged
        Seq 5001+   : B and C continue without interruption
    section Epoch 2
        Partition event : Counter quorum lost · Epoch incremented to 2
        Seq 0+      : All consumers resync to new epoch
```
