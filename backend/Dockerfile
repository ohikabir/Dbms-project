# --- Stage 1: build ------------------------------------------------------
# The build runs in a full JDK image with Maven; the finished jar is then
# copied into a much smaller runtime image. The JDK, the Maven cache and the
# source code never reach production this way.
FROM eclipse-temurin:21-jdk AS build

WORKDIR /build

# Copy the wrapper and pom first, then download dependencies as their own
# layer. Docker caches it, so changing a .java file does not re-download the
# entire Spring Boot dependency tree on every build.
COPY .mvn/ .mvn/
COPY mvnw pom.xml ./
RUN chmod +x mvnw && ./mvnw dependency:go-offline -B

COPY src/ src/
RUN ./mvnw clean package -DskipTests -B

# --- Stage 2: runtime ----------------------------------------------------
# JRE only (no compiler, no build tools) — smaller image, smaller attack surface.
FROM eclipse-temurin:21-jre

WORKDIR /app

# Non-root user: if the app is compromised, the attacker is unprivileged
# inside the container rather than root.
RUN useradd --create-home --uid 1000 spring
USER spring

COPY --from=build --chown=spring:spring /build/target/*.jar app.jar

EXPOSE 8080

# Tests are skipped in the image build on purpose — CI runs them (see
# .github/workflows/ci.yml). Running them twice just slows the build down.
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
