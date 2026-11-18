package com.anpr.operations.messaging;

import org.junit.jupiter.api.Test;
import software.amazon.awssdk.services.sqs.model.Message;
import software.amazon.awssdk.services.sqs.model.MessageAttributeValue;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SqsMessagesTest {

    @Test
    void requiredAttributeReturnsItsValue() {
        Message message = Message.builder()
                .messageAttributes(Map.of("eventType",
                        MessageAttributeValue.builder().dataType("String").stringValue("detection").build()))
                .build();

        assertThat(SqsMessages.requiredAttribute(message, "eventType")).isEqualTo("detection");
    }

    @Test
    void missingRequiredAttributeIsRejectedWithItsName() {
        Message message = Message.builder().messageAttributes(Map.of()).build();

        assertThatThrownBy(() -> SqsMessages.requiredAttribute(message, "eventType"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("eventType");
    }
}
