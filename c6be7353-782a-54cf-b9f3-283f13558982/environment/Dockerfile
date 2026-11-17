FROM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530
LABEL org.opencontainers.image.source="https://github.com/ethara-ai/nexus"
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TARND_URL=http://tarnd:8080

RUN groupadd --gid 1000 tarn && useradd --uid 1000 --gid 1000 --create-home tarn

# The agent's container holds the client, the specification and the sample data.
# It never holds the engine: environment/.dockerignore keeps tarnd/ out of this
# build context, so there is nothing here to copy even by accident.
WORKDIR /app
COPY --chown=1000:1000 docs /app/docs
COPY --chown=1000:1000 sample /app/sample
COPY --chown=1000:1000 client/tarn-cli /usr/local/bin/tarn-cli
RUN chmod 0755 /usr/local/bin/tarn-cli && mkdir -p /app/out && chown 1000:1000 /app/out
USER root
CMD ["sleep", "infinity"]
