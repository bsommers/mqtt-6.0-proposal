# Cluster Failover & Epoch Management Diagrams

---

## 1. Cluster Queue Ownership (C4)

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','secondaryColor':'#424242','tertiaryColor':'#FFF9C4'}}}%%
C4Context
    title HiveMQ v6.0 — Cluster Queue Ownership

    Person(pub, "Publisher")
    Person(con, "Consumer")

    System_Boundary(cluster, "HiveMQ Cluster (consistent hash ring)") {
        System(n1, "Node 1", "Leader: $queue/line_1, $queue/events_A")
        System(n2, "Node 2", "Leader: $queue/line_2, $queue/alarms")
        System(n3, "Node 3", "Leader: $queue/line_3, $queue/fdc_data")
    }

    Rel(pub, n1, "PUBLISH $queue/line_1", "hash → Node 1")
    Rel(con, n3, "FETCH $queue/fdc_data", "hash → Node 3")
    Rel(n1, n2, "Replicate", "async")
    Rel(n2, n3, "Replicate", "async")
    Rel(n3, n1, "Replicate", "async")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

---

## 2. Leader Node State Machine

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121'}}}%%
stateDiagram-v2
    direction LR
    [*] --> Candidate : start / leader lost
    Candidate --> Leader : win election
    Candidate --> Follower : another node wins
    Leader --> EpochReset : continuity gap detected
    EpochReset --> Leader : Epoch++ · notify clients
    Leader --> [*] : node crash
    Follower --> Candidate : heartbeat timeout
    Follower --> Follower : receive replicated data

    note right of EpochReset : Increment Epoch\nDisconnect consumers\nwith 0xA0
```

---

## 3. Quorum Replication

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','actorBkg':'#FFD600','actorBorder':'#212121','actorTextColor':'#212121','noteBkgColor':'#FFF9C4','noteTextColor':'#212121','activationBkgColor':'#FFF9C4','signalColor':'#212121','signalTextColor':'#212121'}}}%%
sequenceDiagram
    participant P as Publisher
    participant L as Leader
    participant R1 as Replica 1
    participant R2 as Replica 2

    P->>L: PUBLISH $queue/prod
    L->>L: Seq=1099 Epoch=1 · NVMe write
    par RF=2
        L->>R1: Replicate 1099
        R1-->>L: ACK
    and
        L->>R2: Replicate 1099
        R2-->>L: ACK
    end
    L-->>P: PUBACK 1099
    L-xR1: Node L crashes
    Note over R1: R1 has 1099 ✓\nelected Leader · Epoch=1 unchanged
```

---

## 4. Failover Decision Tree

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','edgeLabelBackground':'#FFFFFF'}}}%%
flowchart TD
    FAIL["Node failure"] --> Q1{"New leader has\nall data?"}

    Q1 -->|Yes| OK["Same Epoch\nResume normally"]
    Q1 -->|No| Q2{"Gap size?"}

    Q2 -->|Small| WARN["Epoch++\nResume from\nlast confirmed Seq"]
    Q2 -->|Large / partition| CRIT["Epoch++\nFull client resync\nfrom Seq=0"]

    classDef ok fill:#FFD600,stroke:#212121,color:#212121
    classDef warn fill:#9E9E9E,stroke:#212121,color:#212121
    classDef crit fill:#212121,stroke:#FFD600,color:#FFD600

    class OK ok
    class WARN warn
    class CRIT crit
```

---

## 5. Client Reconnect Decision Tree

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121','edgeLabelBackground':'#FFFFFF'}}}%%
flowchart TD
    RC["Client reconnects\nlast-seq=N epoch=E"] --> E{"Epoch\nmatches?"}

    E -->|Yes| S{"Seq N\nexists?"}
    E -->|No – changed| RESET["CONNACK new Epoch\nClient clears HWM\nFull resync"]

    S -->|Yes| RESUME["Resume from N+1\nNo disruption"]
    S -->|No – gap| GAP["Resume from\nearliest Seq\nFlag missing range"]

    classDef ok fill:#FFD600,stroke:#212121,color:#212121
    classDef warn fill:#9E9E9E,stroke:#212121,color:#212121
    classDef crit fill:#212121,stroke:#FFD600,color:#FFD600

    class RESUME ok
    class GAP warn
    class RESET crit
```

---

## 6. Tiered Storage

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

## 7. Epoch Timeline

```mermaid
%%{init:{'theme':'base','themeVariables':{'primaryColor':'#FFD600','primaryTextColor':'#212121','primaryBorderColor':'#212121','lineColor':'#212121'}}}%%
timeline
    title $queue/production_line · Epoch History
    section Epoch 1
        Seq 1–5000  : Node 1 leader · normal operation
        Seq 5001    : Node 1 crash · replication at Seq 4998
    section Epoch 2
        Seq 0–2000  : Node 2 elected · all clients resync
        Seq 2001–8500 : Stable · Node 2 leader
    section Epoch 2 (cont.)
        Seq 8501+   : Node 3 clean handoff · Epoch unchanged
```
