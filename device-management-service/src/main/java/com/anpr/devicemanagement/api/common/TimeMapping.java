package com.anpr.devicemanagement.api.common;

import org.mapstruct.Mapper;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;

/** The contract uses OffsetDateTime (always sent in UTC), the domain Instant. Used by the API mappers. */
@Mapper(componentModel = "spring")
public interface TimeMapping {

    default OffsetDateTime toOffsetDateTime(Instant instant) {
        return instant == null ? null : instant.atOffset(ZoneOffset.UTC);
    }

    default Instant toInstant(OffsetDateTime dateTime) {
        return dateTime == null ? null : dateTime.toInstant();
    }
}
