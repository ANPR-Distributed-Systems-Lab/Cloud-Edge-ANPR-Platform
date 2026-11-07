package com.anpr.operations.config;

import com.anpr.operations.messaging.SqsQueueListener;
import com.anpr.operations.messaging.devices.DeviceEventHandler;
import com.anpr.operations.messaging.edge.EdgeEventHandler;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import software.amazon.awssdk.services.sqs.SqsClient;

/** One listener per queue. Off in the local and test profiles: nothing local may consume the queues on AWS. */
@Configuration
@Profile("!local & !test")
public class QueueListenersConfig {

    @Bean
    SqsQueueListener deviceEventsListener(SqsClient sqs, AwsProperties aws, DeviceEventHandler handler) {
        return new SqsQueueListener("device-events-listener", sqs, aws.sqs().deviceEventsQueueUrl(), handler::handle);
    }

    @Bean
    SqsQueueListener edgeEventsListener(SqsClient sqs, AwsProperties aws, EdgeEventHandler handler) {
        return new SqsQueueListener("edge-events-listener", sqs, aws.sqs().eventsQueueUrl(), handler::handle);
    }
}
