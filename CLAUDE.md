# Cloud-Edge ANPR Platform - Project Standards and Architecture

This document defines the core architectural principles, conventions, and monorepo structure for the distributed Cloud-Edge ANPR system. All new features, pull requests, and code modifications must strictly comply with these guidelines.

## 1. Monorepo Structure
The project relies on a monorepo architecture with a clear separation of domains and responsibilities:

* `/operations-service` - Business layer microservice (Spring Boot) handling views, alerts, and detection search queries (PostgreSQL/PostGIS).
* `/device-management-service` - Control plane microservice (Spring Boot) managing the IoT fleet, configurations, and generating PreSigned URLs for devices (DynamoDB).
* `/rpi-edge` - Edge node code running on Raspberry Pi 5 devices (Python).
* `/infrastructure` - Declarative cloud infrastructure configuration (Terraform) for the AWS platform.
* `/integration-tests` - External, cross-service tests (E2E, API) triggered by CI/CD pipelines.

## 2. Tech Stack and Backend Conventions (Spring Boot)
Both cloud microservices are built on the **Spring Boot** (Java) ecosystem.

* **Contract-First Approach:** The single source of truth for API communication interfaces are OpenAPI specification files (`.yaml` / `.json`). REST controllers and DTO models must be auto-generated from the OpenAPI definition during the build process using tools like Maven.
* **Event-Driven Architecture (EDA):** Each microservice exclusively manages its own database. State changes in the system are propagated asynchronously using Amazon SNS (Fan-Out pattern) and Amazon SQS. The target architecture includes implementing Dead Letter Queues (DLQ) for every queue to handle unprocessed events.
* **Database Schema Management:** Relational schema evolution (PostgreSQL) is managed exclusively via **Flyway**. Migration scripts (e.g., `V1__init.sql`) are an integral part of each service's repository. Using code-driven auto-generation mechanisms (like Hibernate `ddl-auto`) in runtime environments is strictly prohibited.

## 3. Edge MLOps Standards
The IoT application running on the Raspberry Pi 5 is implemented in **Python**.

* **ML Model Distribution:** Model weight files (e.g., `.onnx`) are **not** stored in the code repository. The edge script downloads the latest model version directly from a dedicated AWS S3 bucket during system startup.
* **Store-and-Forward:** Edge scripts must be resilient to temporary cloud connectivity loss. Detection results are buffered on the device using local, persistent databases and are sent asynchronously once the connection is restored.

## 4. Local Developer Environment
The development environment setup relies on a hybrid approach designed to maximize debugging speed:
* Application code (Spring Boot / Python) is run natively, directly from the developer's IDE (IntelliJ, PyCharm).
* Infrastructure dependencies (PostgreSQL, local DynamoDB Local instance) are launched using a `docker-compose.yml` file.
* The system supports a *Cloud-Dev* mode, allowing (via configuration flags) the locally running application to connect directly to databases and SQS/SNS queues from the deployed `dev` cloud environment on AWS.

## 5. Infrastructure (IaC), Security, and FinOps
AWS configuration is managed declaratively from the `/infrastructure` directory.

* **Infrastructure as Code (Terraform):** Creating and modifying resources manually in the AWS web console (ClickOps) is prohibited. All infrastructure must be defined in Terraform scripts.
* **No Secrets in the Repository:** No sensitive data (database passwords, keys) can be hardcoded or stored in local repository files. Microservices dynamically fetch hidden configurations from **AWS SSM Parameter Store** during startup.
* **Authorization Management (JWT):** Validation of tokens issued by AWS Cognito happens at the entry layer – in **Amazon API Gateway**. Spring Boot (ECS) microservices base their authorization on headers injected by the API Gateway layer.
* **FinOps:** The repository provides scripts and GitHub Actions to reduce costs (scaling down ECS tasks, pausing RDS instances), which are used to shut down environments outside of developer working hours.

## 6. Git Workflow, CI/CD, Testing, and Telemetry
* **Branching Strategy (GitHub Flow):** The project uses a single, primary `main` branch, which directly reflects the deployment state for the `dev` environment. New code is developed on short-lived branches like `feature/` or `fix/` and integrated into `main` exclusively via Pull Requests.
* **Commit Convention:** Strict adherence to the **Conventional Commits** standard (e.g., `feat:`, `fix:`, `chore:`, `refactor:`) is mandatory to generate automated changelogs.
* **Testing Architecture:** There is a strict division between internal and global tests:
    * **Internal integration tests (within a given microservice):** These verify logic in isolation (from API to the database). Relational database operations (PostgreSQL/PostGIS) and Flyway migrations must be tested using **Testcontainers**. Any communication with external AWS services (Cognito, SNS/SQS) must be mocked.
    * **Global E2E tests (in the `/integration-tests` directory):** These verify actual integration, IAM permissions, and routing in the AWS cloud. They run in the CI/CD pipeline **only after deploying** containers to the target environment and check the real, asynchronous data flow (e.g., SNS $\rightarrow$ SQS $\rightarrow$ Database) without using mocks.
* **GitHub Actions:** Every merge to the `main` branch triggers fully automated CI/CD pipelines (linting, building containers, internal testing, deploying Terraform infrastructure, updating ECS, running E2E tests, and publishing to Amazon ECR).
* **Telemetry (Structured Logging):** All system components (including RPi scripts) must generate logs exclusively in a structured **JSON** format. Every log in the business flow must contain a `Trace ID` passed through queues and APIs, enabling distributed request tracing in Amazon CloudWatch.