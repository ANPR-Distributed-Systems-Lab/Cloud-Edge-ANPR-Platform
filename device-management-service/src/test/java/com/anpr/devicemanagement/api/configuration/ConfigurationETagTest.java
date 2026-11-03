package com.anpr.devicemanagement.api.configuration;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ConfigurationETagTest {

    private final String etag = ConfigurationETag.of(3);

    @Test
    void isTheQuotedVersion() {
        assertThat(etag).isEqualTo("\"3\"");
    }

    @Test
    void matchesTheSameTagAlsoWhenWeakOrInAList() {
        assertThat(ConfigurationETag.matches("\"3\"", etag)).isTrue();
        assertThat(ConfigurationETag.matches("W/\"3\"", etag)).isTrue();
        assertThat(ConfigurationETag.matches("\"1\", \"3\"", etag)).isTrue();
        assertThat(ConfigurationETag.matches("*", etag)).isTrue();
    }

    @Test
    void doesNotMatchAnotherVersionOrNothing() {
        assertThat(ConfigurationETag.matches("\"2\"", etag)).isFalse();
        assertThat(ConfigurationETag.matches("3", etag)).isFalse();
        assertThat(ConfigurationETag.matches(null, etag)).isFalse();
    }
}
