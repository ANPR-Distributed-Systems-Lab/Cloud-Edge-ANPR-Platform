# syntax=docker/dockerfile:1

# ---------------------------------------------------------------- build stage
# Full JDK + Maven. Nothing from this stage ends up in the final image except
# the extracted application files.
FROM eclipse-temurin:21-jdk-alpine AS build
WORKDIR /workspace

# Copy only what Maven needs to resolve dependencies first. As long as pom.xml
# is unchanged, Docker reuses this layer and the dependency download is skipped.
COPY mvnw pom.xml ./
COPY .mvn .mvn
RUN --mount=type=cache,target=/root/.m2 sh mvnw -B -q dependency:go-offline

# Tests run in a separate CI job (they need Docker for Testcontainers, which
# is not available inside `docker build`), so they are skipped here.
COPY operations-api.yaml ./
COPY src src
RUN --mount=type=cache,target=/root/.m2 sh mvnw -B -q -DskipTests package \
    && java -Djarmode=tools -jar target/operations-service-*.jar extract --destination /workspace/extracted

# ---------------------------------------------------------------- runtime stage
# JRE only (smaller, less attack surface). Alpine ships busybox wget, which the
# ECS container health check uses.
FROM eclipse-temurin:21-jre-alpine

# Never run the application as root.
RUN addgroup -S app && adduser -S app -G app
USER app
WORKDIR /app

# Dependencies change rarely, the application jar on every commit. Separate
# layers mean only the small application layer is rebuilt and pushed to ECR.
COPY --from=build --chown=app:app /workspace/extracted/lib ./lib
COPY --from=build --chown=app:app /workspace/extracted/operations-service-*.jar ./app.jar

EXPOSE 8080

# MaxRAMPercentage: size the heap from the container memory limit (ECS task memory).
# ExitOnOutOfMemoryError: crash fast on OOM so ECS replaces the task instead of leaving it half-dead.
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-XX:+ExitOnOutOfMemoryError", "-jar", "app.jar"]
