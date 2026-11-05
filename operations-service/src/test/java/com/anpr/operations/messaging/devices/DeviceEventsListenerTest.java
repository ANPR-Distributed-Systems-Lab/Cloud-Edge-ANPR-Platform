package com.anpr.operations.messaging.devices;

import com.anpr.operations.config.AwsProperties;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sqs.model.DeleteMessageRequest;
import software.amazon.awssdk.services.sqs.model.Message;
import software.amazon.awssdk.services.sqs.model.ReceiveMessageRequest;
import software.amazon.awssdk.services.sqs.model.ReceiveMessageResponse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class DeviceEventsListenerTest {
    private static final String QUEUE_URL = "https://sqs.eu-central-1.amazonaws.com/000000000000/operations-device-events";

    private final SqsClient sqs = mock(SqsClient.class);
    private final DeviceEventHandler handler = mock(DeviceEventHandler.class);
    private final DeviceEventsListener listener = new DeviceEventsListener(
            sqs, new AwsProperties("eu-central-1", new AwsProperties.Sqs(QUEUE_URL)), handler);

    @Test
    void receivesWithLongPollingAndAllAttributes() {
        receive();

        listener.pollOnce();

        ArgumentCaptor<ReceiveMessageRequest> request = ArgumentCaptor.forClass(ReceiveMessageRequest.class);
        verify(sqs).receiveMessage(request.capture());
        assertThat(request.getValue().queueUrl()).isEqualTo(QUEUE_URL);
        assertThat(request.getValue().waitTimeSeconds()).isEqualTo(20);
        assertThat(request.getValue().messageAttributeNames()).containsExactly("All");
    }

    @Test
    void handledMessageIsDeleted() {
        Message message = message("receipt-1");
        receive(message);

        listener.pollOnce();

        verify(handler).handle(message);
        ArgumentCaptor<DeleteMessageRequest> delete = ArgumentCaptor.forClass(DeleteMessageRequest.class);
        verify(sqs).deleteMessage(delete.capture());
        assertThat(delete.getValue().queueUrl()).isEqualTo(QUEUE_URL);
        assertThat(delete.getValue().receiptHandle()).isEqualTo("receipt-1");
    }

    @Test
    void failedMessageStaysOnTheQueueAndTheNextOneIsStillHandled() {
        Message failing = message("receipt-1");
        Message next = message("receipt-2");
        receive(failing, next);
        doThrow(new IllegalArgumentException("bad event")).when(handler).handle(failing);

        listener.pollOnce();

        verify(handler).handle(next);
        ArgumentCaptor<DeleteMessageRequest> delete = ArgumentCaptor.forClass(DeleteMessageRequest.class);
        verify(sqs).deleteMessage(delete.capture());
        assertThat(delete.getValue().receiptHandle()).isEqualTo("receipt-2");
    }

    @Test
    void nothingIsDeletedWhenTheQueueIsEmpty() {
        receive();

        listener.pollOnce();

        verify(sqs, never()).deleteMessage(any(DeleteMessageRequest.class));
    }

    private void receive(Message... messages) {
        when(sqs.receiveMessage(any(ReceiveMessageRequest.class)))
                .thenReturn(ReceiveMessageResponse.builder().messages(messages).build());
    }

    private static Message message(String receiptHandle) {
        return Message.builder().messageId("id-" + receiptHandle).receiptHandle(receiptHandle).body("{}").build();
    }
}