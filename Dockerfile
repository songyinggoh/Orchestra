FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for common Phase 4 features
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY README.md .
COPY src/ src/

# Install the package with all Phase 4 features
RUN pip install --no-cache-dir -e ".[server,telemetry,cache,storage,postgres,nats,ray,security]"

# Default environment variables
ENV ORCHESTRA_PORT=8080
ENV NATS_URL="nats://nats:4222"

EXPOSE 8080

ENTRYPOINT ["orchestra"]
CMD ["run"]
