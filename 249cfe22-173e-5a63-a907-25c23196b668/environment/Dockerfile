# syntax=docker/dockerfile:1.12@sha256:93bfd3b68c109427185cd78b4779fc82b484b0b7618e36d0f104d4d801e66d25
# Operator workstation for the Ridgeway island grid. The shipped plant documents are read-only
# under /app/plant and /app/out is writable. Nothing from ems-sim/ is ever built into this image:
# that directory is outside this build's context (see .dockerignore).
FROM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530
LABEL org.opencontainers.image.source="https://github.com/ethara-ai/nexus" \
      org.opencontainers.image.revision="draft" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="docker.io/library/python:3.13-slim-bookworm" \
      org.opencontainers.image.base.digest="sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530"
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN groupadd --gid 1000 plantop && useradd --uid 1000 --gid 1000 --create-home plantop \
    && install -d -m 0755 /app/plant \
    && install -d -m 0775 -o 1000 -g 1000 /app/out
COPY plant/ /app/plant/
RUN chmod -R a=rX /app/plant
WORKDIR /app
USER root
CMD ["/bin/bash"]
