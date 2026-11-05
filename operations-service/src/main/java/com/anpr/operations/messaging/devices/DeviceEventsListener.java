package com.anpr.operations.messaging.devices;

import com.anpr.operations.config.AwsProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import software.amazon.awssdk.services.sqs.model.DeleteMessageRequest;
import software.amazon.awssdk.services.sqs.model.Message;
import org.springframework.context.SmartLifecycle;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sqs.model.ReceiveMessageRequest;

import java.time.Duration;
import java.util.List;

@Slf4j
@Component
@Profile("!local & !test")
@RequiredArgsConstructor
public class DeviceEventsListener implements SmartLifecycle {
    private static final int MAX_MESSAGES = 10;
    private static final int WAIT_SECONDS = 20;
    private static final Duration RETRY_DELAY = Duration.ofSeconds(5);

    private final SqsClient sqs;
    private final AwsProperties aws;
    private final DeviceEventHandler handler;

    private volatile boolean running;
    private Thread worker;

    @Override
    public void start() {
        running = true;
        worker = Thread.ofPlatform().name("device-events-listener").start(this::run);
        log.info("Listening to device events on {}", queueUrl());
    }

    @Override
    public void stop(){
        running = false;
        worker.interrupt();
    }

    @Override
    public boolean isRunning() {
        return running;
    }

    private void run(){
        while (running) {
            try {
                pollOnce();
            } catch (RuntimeException e) {
                if (!running){
                    return;
                }
                log.error("Receiving device events failed, retrying in {}", RETRY_DELAY, e);
                sleep(RETRY_DELAY);
            }
        }
    }

    void pollOnce() {
        List<Message> messages = sqs.receiveMessage(ReceiveMessageRequest.builder()
                .queueUrl(queueUrl())
                .maxNumberOfMessages(MAX_MESSAGES)
                .waitTimeSeconds(WAIT_SECONDS)
                .messageAttributeNames("All")
                .build()).messages();
        for (Message message : messages){
            process(message);
        }
    }

    private void process(Message message){
        try{
            handler.handle(message);
        } catch (RuntimeException e){
            log.warn("Device event {} failed and stays on the queue", message.messageId(), e);
            return;
        }
        sqs.deleteMessage(DeleteMessageRequest.builder()
                .queueUrl(queueUrl())
                .receiptHandle(message.receiptHandle())
                .build());
    }

    private String queueUrl(){
        return aws.sqs().deviceEventsQueueUrl();
    }

    private static void sleep(Duration delay) {
        try {
            Thread.sleep(delay);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
