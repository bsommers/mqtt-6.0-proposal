# Cluster Failover & Epoch Management Diagrams

---

## 1. HiveMQ Shared-Nothing Cluster: Queue Ownership

```mermaid
graph TD
    subgraph Cluster["HiveMQ v6.0 Cluster (5 Nodes)"]
        N1["Node 1<br/>Leader: $queue/line_1<br/>Leader: $queue/events_A"]
        N2["Node 2<br/>Leader: $queue/line_2<br/>Leader: $queue/alarms"]
        N3["Node 3<br/>Leader: $queue/line_3<br/>Leader: $queue/fdc_data"]
        N4["Node 4<br/>Leader: $queue/line_4<br/>Leader: $queue/events_B"]
        N5["Node 5<br/>Leader: $queue/line_5<br/>Leader: $queue/commands"]
        RING["Consistent Hash Ring<br/>MD5($queue/name) mod N"]
    end

    N1 <-.->|Replicate| N2
    N2 <-.->|Replicate| N3
    N3 <-.->|Replicate| N4
    N4 <-.->|Replicate| N5
    N5 <-.->|Replicate| N1

    RING -.->|Hash routing| N1
    RING -.->|Hash routing| N3
    RING -.->|Hash routing| N5

    PUB["Publisher"] -->|$queue/line_1| N1
    CON["Consumer"] -->|FETCH $queue/fdc_data| N3
```

---

## 2. Leader Election State Machine

```mermaid
stateDiagram-v2
    [*] --> Candidate: Node starts / leader lost

    Candidate --> Leader: Win election<br/>(Raft / consistent hash)
    Candidate --> Follower: Another node wins

    Leader --> Leader: Normal operation<br/>Sequence incrementing

    Leader --> Epoch_Reset: Cannot guarantee<br/>sequence continuity
    Epoch_Reset --> Leader: Increment Epoch<br/>Notify all consumers

    Leader --> Dead: Node crash / partition
    Dead --> [*]

    Follower --> Candidate: Leader heartbeat lost
    Follower --> Follower: Receive replicated data
```

---

## 3. Replication and Quorum Acknowledgement

```mermaid
sequenceDiagram
    participant P as Publisher
    participant L as Leader Node (Node 1)
    participant R1 as Replica Node 2
    participant R2 as Replica Node 3

    P->>L: PUBLISH $queue/production<br/>Payload: sensor_batch_99

    L->>L: Assign Seq=1099, Epoch=1<br/>Write to local NVMe

    par Parallel Replication (Replication-Factor=2)
        L->>R1: Replicate Seq=1099
        R1-->>L: ACK
    and
        L->>R2: Replicate Seq=1099
        R2-->>L: ACK
    end

    L-->>P: PUBACK Seq=1099
    Note over P,L: Acknowledged only after<br/>2 replicas confirmed durability

    Note over L: Node 1 crashes!

    Note over R1: R1 wins election<br/>R1 has Seq=1099 ✓<br/>No Epoch Reset needed
    R1->>R1: Become Leader<br/>Epoch=1 (unchanged)
```

---

## 4. Failure Scenarios and Outcomes

```mermaid
flowchart TD
    FAIL["Node Failure Detected"] --> CHECK{"Does new leader have<br/>all replicated data?"}

    CHECK -->|"Yes — clean failover"| CLEAN["Continue with same Epoch<br/>Seq continuity preserved<br/>Consumers resume normally"]

    CHECK -->|"No — replication lag"| LAG{"How much data lost?"}

    LAG -->|"Gap is small<br/>(within replication window)"| SMALL["Increment Epoch<br/>Resume from last confirmed Seq<br/>Alert consumers to reconcile"]

    LAG -->|"Gap is large<br/>(node was partitioned)"| LARGE["Increment Epoch<br/>New Leader starts fresh Seq from 0<br/>Consumers must full-resync"]

    CLEAN --> NOTIFY_NONE["No client action needed"]
    SMALL --> NOTIFY_EPOCH["Send new Epoch in CONNACK<br/>Clients clear idempotency window"]
    LARGE --> NOTIFY_FULL["Send new Epoch in CONNACK<br/>Clients perform S1F13-style reset"]

    style CLEAN fill:#9f9,stroke:#333
    style NOTIFY_NONE fill:#9f9,stroke:#333
    style SMALL fill:#ff9,stroke:#333
    style NOTIFY_EPOCH fill:#ff9,stroke:#333
    style LARGE fill:#f99,stroke:#333
    style NOTIFY_FULL fill:#f99,stroke:#333
```

---

## 5. Client Reconnect Decision Tree

```mermaid
flowchart TD
    RECONNECT["Client reconnects<br/>Sends: last-seq=N, epoch=E"] --> BROKER{"Broker checks<br/>queue state"}

    BROKER --> MATCH{"Epoch matches<br/>AND Seq N exists?"}

    MATCH -->|"Yes"| RESUME["Resume delivery<br/>from Seq N+1<br/>No disruption"]

    MATCH -->|"Epoch matches<br/>but Seq N missing"| GAP["Gap detected!<br/>Deliver from earliest available<br/>Flag missing range to client<br/>Same epoch"]

    MATCH -->|"Epoch changed"| RESET["Send new Epoch in CONNACK<br/>Client clears idempotency state<br/>Client sends FETCH from Seq=0"]

    RESET --> RESYNC["Full Resync<br/>Comparable to SECS/GEM S1F13"]

    style RESUME fill:#9f9,stroke:#333
    style GAP fill:#ff9,stroke:#333
    style RESET fill:#f99,stroke:#333
    style RESYNC fill:#f99,stroke:#333
```

---

## 6. Tiered Storage Model for Persistent Queues

```mermaid
graph LR
    subgraph Broker["Broker Node"]
        direction TB
        RAM["Hot Tier<br/>(RAM Buffer)<br/>Last ~1,000 messages<br/>Sub-ms access"]
        NVME["Warm Tier<br/>(NVMe SSD)<br/>Last ~1M messages<br/>~1ms access"]
    end

    subgraph Cold["Cold Tier (Object Storage)"]
        S3["S3 / GCS / Azure Blob<br/>Unlimited retention<br/>~100ms access"]
    end

    PUB["Publisher"] -->|"Write path"| RAM
    RAM -->|"Evict old (async)"| NVME
    NVME -->|"Evict old (async)"| S3

    CON["Consumer<br/>(FETCH recent)"] -->|"Hot read path"| RAM
    CON2["Consumer<br/>(FETCH backlog)"] -->|"Warm read path"| NVME
    AUDIT["Audit / Replay<br/>(deep history)"] -->|"Cold read path"| S3

    style RAM fill:#9ff,stroke:#333
    style NVME fill:#9f9,stroke:#333
    style S3 fill:#ff9,stroke:#333
```

---

## 7. Epoch Timeline

```mermaid
timeline
    title Queue Epoch History: $queue/production_line
    section Epoch 1
        Seq 1-5000 : Normal operation<br/>Node 1 is Leader
        Seq 5001 : Node 1 crashes<br/>Replication lag: up to Seq 4998
    section Epoch 2
        Seq 0-2000 : Node 2 becomes Leader<br/>Epoch incremented to 2<br/>All clients resync
        Seq 2001-8500 : Stable operation<br/>Node 2 is Leader
        Seq 8500 : Planned maintenance<br/>Clean handoff to Node 3
    section Epoch 3 (optional increment)
        Seq 8501+ : Node 3 takes over<br/>Epoch may stay at 2<br/>(if clean handoff)
```
