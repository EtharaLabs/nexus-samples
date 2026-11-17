# syntax=docker/dockerfile:1.12@sha256:93bfd3b68c109427185cd78b4779fc82b484b0b7618e36d0f104d4d801e66d25
# The agent's container: the operator documents read-only under /app/plant and a writable /app/out.
# No simulator code, seed, parameter, or log is ever copied here; scada-sim/ is outside this
# build's context (.dockerignore). The docs stage prepares the read-only documents; the runtime
# stage copies them in, so the runtime image holds the same files with the same modes.
FROM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530 AS docs
COPY plant /build/plant
RUN chmod 0555 /build/plant && chmod 0444 /build/plant/*

FROM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530
LABEL org.opencontainers.image.source="https://github.com/ethara-ai/nexus" \
      org.opencontainers.image.revision="draft" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="docker.io/library/python:3.13-slim-bookworm" \
      org.opencontainers.image.base.digest="sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530"
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN groupadd --gid 1000 plantop && useradd --uid 1000 --gid 1000 --create-home plantop \
    && mkdir -p /app/out && chown 1000:1000 /app/out
COPY --from=docs /build/plant /app/plant
RUN chmod 0555 /app/plant
WORKDIR /app
USER root
CMD ["/bin/bash"]
