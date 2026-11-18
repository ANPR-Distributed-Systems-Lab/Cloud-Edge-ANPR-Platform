package com.anpr.operations.messaging;

import com.anpr.operations.shared.tracing.TraceId;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.slf4j.MDC;
import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sqs.model.DeleteMessageRequest;
import software.amazon.awssdk.services.sqs.model.Message;
import software.amazon.awssdk.services.sqs.model.MessageAttributeValue;
import software.amazon.awssdk.services.sqs.model.ReceiveMessageRequest;
import software.amazon.awssdk.services.sqs.model.ReceiveMessageResponse;

import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class SqsQueueListenerTest {
    private static final String QUEUE_URL = "https://sqs.eu-central-1.amazonaws.com/000000000000/some-queue";

    private final SqsClient sqs = mock(SqsClient.class);
    @SuppressWarnings("unchecked")
    private final Consumer<Message> handler = mock(Consumer.class);
    private final SqsQueueListener listener = new SqsQueueListener("test-listener", sqs, QUEUE_URL, handler);

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

        verify(handler).accept(message);
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
        doThrow(new IllegalArgumentException("bad event")).when(handler).accept(failing);

        listener.pollOnce();

        verify(handler).accept(next);
        ArgumentCaptor<DeleteMessageRequest> delete = ArgumentCaptor.forClass(DeleteMessageRequest.class);
        verify(sqs).deleteMessage(delete.capture());
        assertThat(delete.getValue().receiptHandle()).isEqualTo("receipt-2");
    }

    @Test
    void traceIdOfTheMessageIsInTheMdcWhileHandlingAndClearedAfterwards() {
        AtomicReference<String> seen = new AtomicReference<>();
        doAnswer(invocation -> {
            seen.set(MDC.get(TraceId.MDC_KEY));
            return null;
        }).when(handler).accept(any());
        receive(message("receipt-1"));

        listener.pollOnce();

        assertThat(seen.get()).isEqualTo("trace-1");
        assertThat(MDC.get(TraceId.MDC_KEY)).isNull();
    }

    @Test
    void traceIdIsClearedAlsoWhenTheHandlerFails() {
        receive(message("receipt-1"));
        doThrow(new IllegalArgumentException("bad event")).when(handler).accept(any());

        listener.pollOnce();

        assertThat(MDC.get(TraceId.MDC_KEY)).isNull();
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
        return Message.builder()
                .messageId("id-" + receiptHandle)
                .receiptHandle(receiptHandle)
                .body("{}")
                .messageAttributes(Map.of("traceId",
                        MessageAttributeValue.builder().dataType("String").stringValue("trace-1").build()))
                .build();
    }
}
