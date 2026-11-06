package com.anpr.operations;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan
public class OperationsServiceApplication {

	public static void main(String[] args) {
		SpringApplication.run(OperationsServiceApplication.class, args);
	}

}
