package com.anpr.operations.messaging;

import lombok.NoArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import software.amazon.awssdk.services.sqs.model.Message;
import software.amazon.awssdk.services.sqs.model.MessageAttributeValue;

import static lombok.AccessLevel.PRIVATE;

/** Reading the message attributes shared by every queue of this service. */
@Slf4j
@NoArgsConstructor(access = PRIVATE)
public final class SqsMessages {

    /** The string value of an attribute, or null when the message does not carry it. */
    public static String attribute(Message message, String name) {
        MessageAttributeValue value = message.messageAttributes().get(name);
        return value == null ? null : value.stringValue();
    }

    /** The traceId attribute; without it the message id, so every log line still carries a trace id. */
    public static String traceIdOf(Message message) {
        String traceId = attribute(message, "traceId");
        if (traceId != null) {
            return traceId;
        }
        log.warn("Message {} has no traceId attribute, using the message id", message.messageId());
        return message.messageId();
    }
}
