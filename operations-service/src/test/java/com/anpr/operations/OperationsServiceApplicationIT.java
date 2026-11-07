package com.anpr.operations;

import com.anpr.operations.messaging.SqsQueueListener;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.ActiveProfiles;

import static org.assertj.core.api.Assertions.assertThat;

@Import(TestcontainersConfiguration.class)
@SpringBootTest
@ActiveProfiles("test")
class OperationsServiceApplicationIT {

	@Autowired
	private ApplicationContext context;

	@Test
	void contextLoads() {
	}

	@Test
	void queueListenersAreOffInTheTestProfile() {
		// A listener here would poll real AWS queues from every integration test.
		assertThat(context.getBeansOfType(SqsQueueListener.class)).isEmpty();
	}

}
