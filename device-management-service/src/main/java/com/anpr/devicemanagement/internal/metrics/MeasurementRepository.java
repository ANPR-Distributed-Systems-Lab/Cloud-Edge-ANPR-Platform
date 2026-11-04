package com.anpr.devicemanagement.internal.metrics;

import com.anpr.devicemanagement.shared.error.TechnicalException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Repository;
import software.amazon.awssdk.enhanced.dynamodb.DynamoDbEnhancedClient;
import software.amazon.awssdk.enhanced.dynamodb.DynamoDbTable;
import software.amazon.awssdk.enhanced.dynamodb.Key;
import software.amazon.awssdk.enhanced.dynamodb.model.BatchWriteItemEnhancedRequest;
import software.amazon.awssdk.enhanced.dynamodb.model.BatchWriteResult;
import software.amazon.awssdk.enhanced.dynamodb.model.QueryConditional;
import software.amazon.awssdk.enhanced.dynamodb.model.QueryEnhancedRequest;
import software.amazon.awssdk.enhanced.dynamodb.model.WriteBatch;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

@Repository
@RequiredArgsConstructor
public class MeasurementRepository {
    /** The maximum of one BatchWriteItem call. */
    private static final int BATCH_SIZE = 25;
    private static final int MAX_ATTEMPTS = 5;
    private static final long FIRST_BACKOFF_MILLIS = 50;

    private final DynamoDbTable<Measurement> table;
    private final DynamoDbEnhancedClient client;

    /**
     * Stores the measurements, overwriting any with the same device and recordedAt (so a resent batch is harmless).
     * Items DynamoDB leaves unprocessed under load are retried with a growing pause.
     *
     * @throws TechnicalException when some items are still unprocessed after the last attempt; the device resends
     */
    public void saveAll(List<Measurement> measurements) {
        for (int start = 0; start < measurements.size(); start += BATCH_SIZE) {
            List<Measurement> pending = measurements.subList(start, Math.min(start + BATCH_SIZE, measurements.size()));
            for (int attempt = 1; !pending.isEmpty(); attempt++) {
                if (attempt > MAX_ATTEMPTS) {
                    throw new TechnicalException(pending.size() + " measurements left unprocessed by DynamoDB");
                }
                if (attempt > 1) {
                    pause(FIRST_BACKOFF_MILLIS << (attempt - 2));
                }
                pending = write(pending);
            }
        }
    }

    /**
     * The {@code limit} most recent measurements of a device recorded in [{@code from}, {@code to}), newest first.
     */
    public List<Measurement> findLatest(UUID deviceId, Instant from, Instant to, int limit) {
        if (!from.isBefore(to)) {
            return List.of(); // DynamoDB refuses a BETWEEN whose upper bound is below the lower one
        }
        String partition = deviceId.toString();
        QueryEnhancedRequest request = QueryEnhancedRequest.builder()
                .queryConditional(QueryConditional.sortBetween(
                        Key.builder().partitionValue(partition).sortValue(from.toEpochMilli()).build(),
                        Key.builder().partitionValue(partition).sortValue(to.toEpochMilli() - 1).build()))
                .scanIndexForward(false)
                .limit(limit)
                .build();
        return table.query(request).items().stream().limit(limit).toList();
    }

    private List<Measurement> write(List<Measurement> items) {
        WriteBatch.Builder<Measurement> batch = WriteBatch.builder(Measurement.class).mappedTableResource(table);
        items.forEach(batch::addPutItem);
        BatchWriteResult result = client.batchWriteItem(BatchWriteItemEnhancedRequest.builder()
                .writeBatches(batch.build())
                .build());
        return new ArrayList<>(result.unprocessedPutItemsForTable(table));
    }

    private static void pause(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new TechnicalException("Interrupted while retrying a DynamoDB batch write", e);
        }
    }
}
