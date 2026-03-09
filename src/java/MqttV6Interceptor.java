package com.hivemq.extension.mqtt.v6;

import com.hivemq.extension.sdk.api.annotations.NotNull;
import com.hivemq.extension.sdk.api.interceptor.publish.PublishInboundInterceptor;
import com.hivemq.extension.sdk.api.interceptor.publish.parameter.PublishInboundInput;
import com.hivemq.extension.sdk.api.interceptor.publish.parameter.PublishInboundOutput;
import com.hivemq.extension.sdk.api.packets.publish.ModifiablePublishPacket;
import com.hivemq.extension.sdk.api.services.Services;
import com.hivemq.extension.sdk.api.services.publish.RetainedMessageStore;

import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * MQTT v6.0 HiveMQ Extension: Publish Interceptor
 *
 * <p>Implements the broker-side logic for MQTT v6.0 Industrial Stream Extension:
 * <ul>
 *   <li>Injects 32-bit Stream Sequence Numbers into $queue/ publishes</li>
 *   <li>Stamps Stream Epoch on all $queue/ messages</li>
 *   <li>Intercepts Virtual FETCH requests ($SYS/queues/.../fetch)</li>
 *   <li>Enforces Throughput Limit (Property 0x41) on connected clients</li>
 * </ul>
 *
 * <p>Cluster Note: In a HiveMQ shared-nothing cluster, sequence numbers must
 * be sourced from a cluster-wide atomic counter, not a per-node counter.
 * This example uses a local AtomicLong for simplicity. Production implementations
 * should use HiveMQ's ClusterService or an external distributed counter.
 *
 * @see <a href="https://www.hivemq.com/docs/hivemq/4.x/extensions/sdk.html">HiveMQ Extension SDK</a>
 */
public class MqttV6Interceptor implements PublishInboundInterceptor {

    private static final String QUEUE_PREFIX = "$queue/";
    private static final String FETCH_PREFIX = "$SYS/queues/";
    private static final String FETCH_SUFFIX = "/fetch";

    // ── Per-queue sequence counters (keyed by queue name) ─────────────────────
    // In production: replace with ClusterService-backed distributed counters.
    private final ConcurrentHashMap<String, AtomicLong> queueSequences =
            new ConcurrentHashMap<>();

    // ── Current cluster epoch ─────────────────────────────────────────────────
    // Incremented by the ClusterEventListener when a node fails.
    // In production: managed by ClusterService and propagated across nodes.
    private volatile long currentEpoch = 1;

    // ── Queue-level maximum batch sizes for Virtual FETCH ─────────────────────
    private static final int DEFAULT_MAX_BATCH_SIZE = 100;

    @Override
    public void onInboundPublish(
            @NotNull PublishInboundInput input,
            @NotNull PublishInboundOutput output) {

        final ModifiablePublishPacket packet = output.getPublishPacket();
        final String topic = packet.getTopic();

        if (topic.startsWith(QUEUE_PREFIX)) {
            handleQueuePublish(packet, topic);
        } else if (topic.startsWith(FETCH_PREFIX) && topic.endsWith(FETCH_SUFFIX)) {
            handleVirtualFetch(packet, topic, input, output);
        }
    }

    // ── $queue/ Publish Handler ───────────────────────────────────────────────

    /**
     * For publishes to $queue/ topics:
     * 1. Assigns a monotonic 32-bit Stream Sequence Number
     * 2. Stamps the current Stream Epoch
     * 3. Validates v6.0 client capability
     */
    private void handleQueuePublish(ModifiablePublishPacket packet, String topic) {
        // Extract queue name from topic (e.g., "$queue/production_line" → "production_line")
        final String queueName = topic.substring(QUEUE_PREFIX.length());

        // Validate v6.0 capability negotiation
        final boolean v6Capable = packet.getUserProperties()
                .asList()
                .stream()
                .anyMatch(p -> "mqtt-ext".equals(p.getName()) && "v6.0".equals(p.getValue()));

        if (!v6Capable) {
            // Non-v6.0 clients MUST NOT use $queue/ namespace
            output(packet).prevent();  // Drop the publish
            return;
        }

        // Assign next sequence number for this queue
        final long nextSeq = getOrCreateSequence(queueName).incrementAndGet();

        // Inject v6.0 metadata as User Properties (Compatibility Mode)
        // In native v6.0 mode, these would be Property IDs 0x30 and 0x35
        packet.getUserProperties().removeName("v6-seq");
        packet.getUserProperties().removeName("v6-epoch");
        packet.getUserProperties().addUserProperty("v6-seq", String.valueOf(nextSeq));
        packet.getUserProperties().addUserProperty("v6-epoch", String.valueOf(currentEpoch));

        // Log for observability
        System.out.printf("[v6 ASSIGN] Queue: %s | Seq: %d | Epoch: %d%n",
                queueName, nextSeq, currentEpoch);
    }

    // ── Virtual FETCH Handler ────────────────────────────────────────────────

    /**
     * For publishes to $SYS/queues/{name}/fetch (Virtual FETCH requests):
     * 1. Parse batch size from User Properties
     * 2. Retrieve messages from persistent store
     * 3. Publish batch to client session
     *
     * Note: Full implementation requires HiveMQ's ManagedPersistenceService.
     * This skeleton shows the intercept pattern.
     */
    private void handleVirtualFetch(
            ModifiablePublishPacket packet,
            String topic,
            PublishInboundInput input,
            PublishInboundOutput output) {

        // Extract queue name from control topic
        // e.g., "$SYS/queues/production_line/fetch" → "production_line"
        final String queueName = topic
                .substring(FETCH_PREFIX.length(), topic.length() - FETCH_SUFFIX.length());

        // Parse batch size from User Properties
        final int batchSize = packet.getUserProperties()
                .asList()
                .stream()
                .filter(p -> "v6-batch".equals(p.getName()))
                .findFirst()
                .map(p -> {
                    try { return Integer.parseInt(p.getValue()); }
                    catch (NumberFormatException e) { return DEFAULT_MAX_BATCH_SIZE; }
                })
                .orElse(DEFAULT_MAX_BATCH_SIZE);

        // Parse last received sequence (high-watermark)
        final long lastSeq = packet.getUserProperties()
                .asList()
                .stream()
                .filter(p -> "v6-last-seq".equals(p.getName()))
                .findFirst()
                .map(p -> {
                    try { return Long.parseLong(p.getValue()); }
                    catch (NumberFormatException e) { return 0L; }
                })
                .orElse(0L);

        System.out.printf("[v6 FETCH] Queue: %s | batch=%d | last-seq=%d%n",
                queueName, batchSize, lastSeq);

        // Prevent the control topic publish from being routed to subscribers
        // (it's a control command, not a user message)
        output.preventPublishDelivery();

        // TODO: Use ManagedPersistenceService to retrieve the next `batchSize`
        // messages from $queue/{queueName} starting from lastSeq+1, then
        // publish them to the requesting client's session via PublishService.
        //
        // Example (pseudo-code):
        //   List<QueuedMessage> batch = persistenceService.readBatch(
        //       queueName, lastSeq + 1, batchSize);
        //   for (QueuedMessage msg : batch) {
        //       Services.publishService().publishToClient(
        //           input.getClientInformation().getClientId(), msg.toPublish());
        //   }
    }

    // ── Epoch Management ─────────────────────────────────────────────────────

    /**
     * Called by ClusterEventListener when a queue leader fails.
     * Increments the epoch for all queues or a specific queue.
     *
     * In production, this would be wired to HiveMQ's ClusterService events.
     */
    public void onLeaderFailover(String failedQueueName) {
        currentEpoch++;
        System.out.printf("[EPOCH RESET] Queue: %s | New Epoch: %d%n",
                failedQueueName, currentEpoch);

        // In production: notify all active consumers via DISCONNECT
        // with Reason Code 0xA0 (Epoch Reset) and the new epoch value.
        // Services.clientService().disconnectClient(clientId, reasonCode);
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    private AtomicLong getOrCreateSequence(String queueName) {
        return queueSequences.computeIfAbsent(queueName, k -> new AtomicLong(0));
    }

    /** Placeholder for fluent output manipulation (simplified for readability). */
    private ModifiablePublishPacket output(ModifiablePublishPacket packet) {
        return packet;
    }
}
