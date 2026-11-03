package com.anpr.devicemanagement.internal.metrics;

import software.amazon.awssdk.enhanced.dynamodb.AttributeConverter;
import software.amazon.awssdk.enhanced.dynamodb.AttributeValueType;
import software.amazon.awssdk.enhanced.dynamodb.EnhancedType;
import software.amazon.awssdk.services.dynamodb.model.AttributeValue;

import java.time.Instant;

/** Stores an instant as epoch milliseconds (a number), so that a sort key orders chronologically. */
public class EpochMillisConverter implements AttributeConverter<Instant> {

    @Override
    public AttributeValue transformFrom(Instant input) {
        return AttributeValue.fromN(Long.toString(input.toEpochMilli()));
    }

    @Override
    public Instant transformTo(AttributeValue input) {
        return Instant.ofEpochMilli(Long.parseLong(input.n()));
    }

    @Override
    public EnhancedType<Instant> type() {
        return EnhancedType.of(Instant.class);
    }

    @Override
    public AttributeValueType attributeValueType() {
        return AttributeValueType.N;
    }
}
