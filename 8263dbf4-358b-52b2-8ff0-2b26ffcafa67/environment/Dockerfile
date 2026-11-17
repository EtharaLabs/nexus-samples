# syntax=docker/dockerfile:1.11.1@sha256:10c699f1b6c8bdc8f6b4ce8974855dd8542f1768c26eb240237b8f1c9c6c9976
FROM --platform=$BUILDPLATFORM python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS build
ARG TARGETOS
ARG TARGETARCH
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
WORKDIR /stage
COPY stream.py /stage/app/stream
COPY data/config.json /stage/app/data/config.json
RUN chmod 0755 /stage/app/stream

FROM python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS runtime
LABEL org.opencontainers.image.source="https://github.com/EtharaOrion/nexus" \
      org.opencontainers.image.revision="forge-dhawal-bathre-ethara-ai-20261029t084806z-c525f3" \
      org.opencontainers.image.licenses="proprietary" \
      org.opencontainers.image.base.name="docker.io/library/python:3.13-slim-bookworm"
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN groupadd --gid 1000 agent \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin agent
COPY --from=build --chown=1000:1000 /stage/app /app
WORKDIR /app
# Keep root as the image default: a non-root final USER triggers an Oracle
# startup hang. The agent still runs unprivileged via [agent].user in task.toml.
USER root
CMD ["sleep", "infinity"]
