"""
MQTT v6.0 Python Shim

Implements the MQTT v6.0 compatibility layer on top of gmqtt (MQTT v5.0).
Tunnels v6.0 semantics (32-bit sequences, epochs, competing consumers,
virtual FETCH) through MQTT v5.0 User Properties.

Dependencies: gmqtt, asyncio
"""

import asyncio
from gmqtt import Client as MQTTClient

# ──────────────────────────────────────────────────────────────────────────────
# Core Shim
# ──────────────────────────────────────────────────────────────────────────────

class MQTTv6Shim:
    """
    Wraps a gmqtt Client with MQTT v6.0 Compatibility Layer semantics.

    Sequence numbers and epochs are tunneled as User Properties since
    native Property IDs (0x30, 0x35) require Protocol Level 6.
    """

    def __init__(self, client_id: str, broker_host: str, broker_port: int = 1883):
        self.client = MQTTClient(client_id)
        self.host = broker_host
        self.port = broker_port

        # Local sequence and epoch state
        self._last_seq: int = 0
        self._current_epoch: int = 0

        # High-watermark for idempotency (last successfully processed seq)
        self._high_watermark: int = 0

        # Whether the broker confirmed v6.0 support
        self.v6_enabled: bool = False

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_raw_message

        # User-supplied message handler
        self.on_v6_message = None

    # ── Connection ─────────────────────────────────────────────────────────────

    async def connect(self, last_seq: int = 0, epoch: int = 0):
        """Connect with v6.0 negotiation and optional resync properties."""
        self._last_seq = last_seq
        self._current_epoch = epoch

        connect_properties = {
            'user_property': [
                ('mqtt-ext', 'v6.0'),
                ('v6-last-seq', str(last_seq)),
                ('v6-epoch', str(epoch)),
            ]
        }
        await self.client.connect(
            self.host,
            port=self.port,
            clean_session=False,
            properties=connect_properties,
        )

    def _on_connect(self, client, flags, rc, properties):
        props = dict(properties.get('user_property', []))
        if props.get('mqtt-ext') == 'v6.0':
            self.v6_enabled = True
            # Check for epoch change signaled by broker in CONNACK
            broker_epoch = int(props.get('v6-epoch', self._current_epoch))
            if broker_epoch > self._current_epoch:
                print(
                    f"[EPOCH RESET] Broker signaled new epoch "
                    f"{self._current_epoch} → {broker_epoch}. Clearing state."
                )
                self._current_epoch = broker_epoch
                self._high_watermark = 0  # Reset idempotency
        else:
            print("[WARN] Broker did not confirm v6.0 support. Falling back to v5.0.")

    # ── Publishing ─────────────────────────────────────────────────────────────

    async def publish_v6(
        self,
        queue_name: str,
        payload: bytes | str,
        priority: int = 0,
        qos: int = 1,
    ):
        """
        Publish to the $queue/ namespace with v6.0 sequence metadata.

        In compat mode, sequence/epoch are encoded as User Properties.
        In native v6.0 mode, they would be Property 0x30 and 0x35.
        """
        self._last_seq += 1

        if isinstance(payload, str):
            payload = payload.encode()

        topic = f"$queue/{queue_name}"
        pub_properties = {
            'user_property': [
                ('v6-seq', str(self._last_seq)),
                ('v6-epoch', str(self._current_epoch)),
                ('v6-priority', str(priority)),
            ]
        }

        self.client.publish(topic, payload, qos=qos, properties=pub_properties)
        print(
            f"[v6 PUB] {topic} | Seq: {self._last_seq} | "
            f"Epoch: {self._current_epoch} | Priority: {priority}"
        )

    # ── Subscribing ────────────────────────────────────────────────────────────

    async def subscribe_v6(
        self,
        queue_name: str,
        semantics: str = 'competing',
        group: str = 'default',
        qos: int = 1,
    ):
        """
        Subscribe to a $queue/ topic with v6.0 consumer semantics.

        semantics: 'competing' (round-robin) or 'exclusive' (hot-standby)
        """
        topic = f"$queue/{queue_name}"
        sub_properties = {
            'user_property': [
                ('v6-semantics', semantics),
                ('v6-group', group),
            ]
        }
        await self.client.subscribe(topic, qos=qos, subscription_identifier=1)
        print(f"[v6 SUB] {topic} | mode={semantics} group={group}")

    # ── Virtual FETCH ──────────────────────────────────────────────────────────

    async def fetch_v6(self, queue_name: str, batch_size: int = 10, wait_ms: int = 0):
        """
        Virtual FETCH — request a batch of messages from the broker.

        Publishes to $SYS/queues/{queue_name}/fetch, which a v6.0 Extension
        Plugin intercepts and uses to release messages from persistent storage.
        """
        control_topic = f"$SYS/queues/{queue_name}/fetch"
        fetch_properties = {
            'user_property': [
                ('v6-batch', str(batch_size)),
                ('v6-last-seq', str(self._high_watermark)),
                ('v6-wait-ms', str(wait_ms)),
            ]
        }
        self.client.publish(control_topic, b'', qos=1, properties=fetch_properties)
        print(
            f"[v6 FETCH] {queue_name} | batch={batch_size} | "
            f"last-seq={self._high_watermark}"
        )

    # ── Message Handling ───────────────────────────────────────────────────────

    def _on_raw_message(self, client, topic, payload, qos, properties):
        """Decode v6.0 metadata from incoming message and apply idempotency logic."""
        props = dict(properties.get('user_property', []))

        seq = int(props.get('v6-seq', 0))
        epoch = int(props.get('v6-epoch', 0))

        # ── Epoch Check ────────────────────────────────────────────────────────
        if epoch > self._current_epoch:
            print(
                f"[EPOCH RESET] Cluster era changed "
                f"{self._current_epoch} → {epoch}. Clearing idempotency state."
            )
            self._current_epoch = epoch
            self._high_watermark = 0

        # ── Gap Detection ──────────────────────────────────────────────────────
        if seq > 0 and self._high_watermark > 0:
            if seq != self._high_watermark + 1:
                print(
                    f"[GAP] Expected Seq {self._high_watermark + 1}, "
                    f"got {seq}. Missing messages: "
                    f"{self._high_watermark + 1} to {seq - 1}"
                )

        # ── Idempotency / Exactly-Once Check ───────────────────────────────────
        if seq > 0 and seq <= self._high_watermark:
            print(f"[DUPLICATE] Seq {seq} <= HWM {self._high_watermark}. Discarding.")
            return  # Acknowledge happens automatically by gmqtt for QoS 1

        # ── Process Message ────────────────────────────────────────────────────
        if self.on_v6_message:
            self.on_v6_message(topic=topic, payload=payload, seq=seq, epoch=epoch)

        if seq > 0:
            self._high_watermark = seq

    async def disconnect(self):
        await self.client.disconnect()


# ──────────────────────────────────────────────────────────────────────────────
# Reliable Consumer Example
# ──────────────────────────────────────────────────────────────────────────────

class ReliableConsumer:
    """Example consumer using the v6.0 shim with gap detection."""

    def __init__(self, client_id: str, broker: str):
        self.shim = MQTTv6Shim(client_id, broker)
        self.shim.on_v6_message = self._handle_message

    def _handle_message(self, topic: str, payload: bytes, seq: int, epoch: int):
        print(f"[PROCESS] Topic: {topic} | Seq: {seq} | Data: {payload.decode()}")

    async def run(self, queue_name: str):
        await self.shim.connect()
        await self.shim.subscribe_v6(queue_name, semantics='competing', group='workers')

        # Pull-based consumption loop
        while True:
            await self.shim.fetch_v6(queue_name, batch_size=10, wait_ms=1000)
            await asyncio.sleep(1)


# ──────────────────────────────────────────────────────────────────────────────
# SECS/GEM Equipment Client Example
# ──────────────────────────────────────────────────────────────────────────────

class SecsGemV6Equipment:
    """
    Simulates a SECS/GEM-compliant equipment client using MQTT v6.0 semantics.

    Maps:
      S2F21 (Remote Start) → $queue/secsgem/{device_id}/S2F21
      S6Fx (Event Reports)  → $queue/secsgem/{device_id}/events
    """

    def __init__(self, device_id: str, broker: str):
        self.device_id = device_id
        self.shim = MQTTv6Shim(f"equip_{device_id}", broker)
        self.shim.on_v6_message = self._handle_host_command
        self._last_processed_id: int = 0

    async def connect(self):
        await self.shim.connect()
        # Exclusive consumer: only this equipment reacts to its own commands
        await self.shim.subscribe_v6(
            f"secsgem/{self.device_id}/S2F21",
            semantics='exclusive',
        )
        await self.shim.subscribe_v6(
            f"secsgem/{self.device_id}/commands",
            semantics='exclusive',
        )

    def _handle_host_command(self, topic: str, payload: bytes, seq: int, epoch: int):
        """Process incoming SECS-II commands with idempotency."""
        # Idempotency: reject already-processed commands
        if seq <= self._last_processed_id:
            print(f"[ALREADY PROCESSED] Seq {seq}. Ignoring (idempotent).")
            return

        if 'S2F21' in topic:
            print(f"[WAFER START] Seq: {seq} | Epoch: {epoch} | Executing S2F21")
            self._start_process()

        self._last_processed_id = seq

    def _start_process(self):
        print("[TOOL] Starting wafer processing...")

    async def send_event(self, stream: int, function: int, data: bytes):
        """Publish a SECS/GEM event (e.g., FDC data) to the queue."""
        await self.shim.publish_v6(
            f"secsgem/{self.device_id}/events",
            data,
            priority=5,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Demo
# ──────────────────────────────────────────────────────────────────────────────

async def run_demo():
    shim = MQTTv6Shim("demo_factory_node", "broker.hivemq.com")

    def handle(topic, payload, seq, epoch):
        print(f"MSG topic={topic} seq={seq} data={payload.decode()}")

    shim.on_v6_message = handle
    await shim.connect()
    await shim.subscribe_v6("production_line", semantics='competing', group='workers')

    for i in range(5):
        await shim.publish_v6("production_line", f"Sensor_Reading_{i}", priority=10)
        await asyncio.sleep(0.5)

    # Pull-based consumption
    await shim.fetch_v6("production_line", batch_size=5)
    await asyncio.sleep(3)
    await shim.disconnect()


if __name__ == "__main__":
    asyncio.run(run_demo())
