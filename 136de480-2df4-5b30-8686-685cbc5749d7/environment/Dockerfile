# syntax=docker/dockerfile:1.12@sha256:93bfd3b68c109427185cd78b4779fc82b484b0b7618e36d0f104d4d801e66d25
FROM --platform=$BUILDPLATFORM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530 AS design
ARG TARGETOS
ARG TARGETARCH
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
WORKDIR /build
COPY SHA256SUMS ./
COPY design ./design
RUN sha256sum -c SHA256SUMS

FROM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530
LABEL org.opencontainers.image.source="https://github.com/ethara-ai/nexus" \
      org.opencontainers.image.revision="draft" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="docker.io/library/python:3.13-slim-bookworm" \
      org.opencontainers.image.base.digest="sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530"
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN groupadd --gid 1000 eda && useradd --uid 1000 --gid 1000 --create-home eda \
    && mkdir -p /app/out && chown 1000:1000 /app/out
COPY --from=design /build/design /app/design
RUN chmod -R a-w /app/design
WORKDIR /app
USER 1000:1000
CMD ["/bin/bash"]
