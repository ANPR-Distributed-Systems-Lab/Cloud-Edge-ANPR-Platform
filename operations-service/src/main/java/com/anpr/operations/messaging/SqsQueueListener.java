package com.anpr.operations.messaging;

import com.anpr.operations.shared.tracing.TraceId;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.context.SmartLifecycle;
import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sqs.model.DeleteMessageRequest;
import software.amazon.awssdk.services.sqs.model.Message;
import software.amazon.awssdk.services.sqs.model.ReceiveMessageRequest;

import java.time.Duration;
import java.util.List;
import java.util.function.Consumer;

/**
 * Polls one queue on one background thread and passes every message to its handler. A message is deleted only after
 * the handler returned, so a failed one returns after the visibility timeout and moves to the DLQ after 5 receives.
 * The trace id of the message is in the MDC while it is handled. One instance per queue, created in
 * QueueListenersConfig.
 */
@Slf4j
public class SqsQueueListener implements SmartLifecycle {
    // Maximum values allowed by SQS: fewer calls, and an empty queue costs one call per 20 seconds.
    private static final int MAX_MESSAGES = 10;
    private static final int WAIT_SECONDS = 20;
    private static final Duration RETRY_DELAY = Duration.ofSeconds(5);

    private final String name;
    private final SqsClient sqs;
    private final String queueUrl;
    private final Consumer<Message> handler;

    private volatile boolean running;
    private Thread worker;

    public SqsQueueListener(String name, SqsClient sqs, String queueUrl, Consumer<Message> handler) {
        this.name = name;
        this.sqs = sqs;
        this.queueUrl = queueUrl;
        this.handler = handler;
    }

    @Override
    public void start() {
        running = true;
        worker = Thread.ofPlatform().name(name).start(this::run);
        log.info("{} listening on {}", name, queueUrl);
    }

    @Override
    public void stop() {
        running = false;
        // Ends a long poll in progress instead of waiting up to 20 seconds for it.
        worker.interrupt();
    }

    @Override
    public boolean isRunning() {
        return running;
    }

    private void run() {
        while (running) {
            try {
                pollOnce();
            } catch (RuntimeException e) {
                if (!running) {
                    return;
                }
                log.error("{} could not receive messages, retrying in {}", name, RETRY_DELAY, e);
                sleep(RETRY_DELAY);
            }
        }
    }

    void pollOnce() {
        List<Message> messages = sqs.receiveMessage(ReceiveMessageRequest.builder()
                .queueUrl(queueUrl)
                .maxNumberOfMessages(MAX_MESSAGES)
                .waitTimeSeconds(WAIT_SECONDS)
                .messageAttributeNames("All")
                .build()).messages();
        for (Message message : messages) {
            process(message);
        }
    }

    private void process(Message message) {
        // Set here and not in the handler, so the warning about a failed message carries the trace id too.
        MDC.put(TraceId.MDC_KEY, SqsMessages.traceIdOf(message));
        try {
            try {
                handler.accept(message);
            } catch (RuntimeException e) {
                // Not an outage yet: the message is retried, and the DLQ catches it if it keeps failing.
                log.warn("{}: message {} failed and stays on the queue", name, message.messageId(), e);
                return;
            }
            sqs.deleteMessage(DeleteMessageRequest.builder()
                    .queueUrl(queueUrl)
                    .receiptHandle(message.receiptHandle())
                    .build());
        } finally {
            // The thread handles the next message right after this one.
            MDC.remove(TraceId.MDC_KEY);
        }
    }

    private static void sleep(Duration delay) {
        try {
            Thread.sleep(delay);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
