package com.anpr.operations;

import org.springframework.boot.SpringApplication;

public class TestOperationsServiceApplication {

	public static void main(String[] args) {
		SpringApplication.from(OperationsServiceApplication::main).with(TestcontainersConfiguration.class).run(args);
	}

}
