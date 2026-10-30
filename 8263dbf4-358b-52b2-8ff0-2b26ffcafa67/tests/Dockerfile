# syntax=docker/dockerfile:1.11.1@sha256:10c699f1b6c8bdc8f6b4ce8974855dd8542f1768c26eb240237b8f1c9c6c9976
FROM --platform=$BUILDPLATFORM python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS build
ARG TARGETOS
ARG TARGETARCH
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir "harbor-rewardkit==0.2.3"

FROM --platform=$BUILDPLATFORM python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS codex
ARG TARGETOS
ARG TARGETARCH
ARG CODEX_VERSION=0.164.0
ARG CODEX_SHA256_ARM64=29a507a2a3fd8f6cd94b96b762d281d299d15d7902dee6132d314b78cf9108eb
ARG CODEX_SHA256_AMD64=90dd0b03b28afcb7fa733a4f73b413db2916a47347efd43fb669cc1c774ee8e4
ARG CODEX_HOST_SHA256_ARM64=0e0bdde24d5b31b05519693635baa9c4f2dc4fe7eee31c67b92155f190dd32d2
ARG CODEX_HOST_SHA256_AMD64=feade7026436baa4e82e898050c7ef82a8adbd98163dc504771275b5ef224f2f
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
WORKDIR /build
RUN case "$TARGETARCH" in \
      arm64) triple=aarch64-unknown-linux-musl; sum="$CODEX_SHA256_ARM64"; hsum="$CODEX_HOST_SHA256_ARM64" ;; \
      amd64) triple=x86_64-unknown-linux-musl; sum="$CODEX_SHA256_AMD64"; hsum="$CODEX_HOST_SHA256_AMD64" ;; \
      *) echo "unsupported arch $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && python3 -c "import sys,urllib.request; urllib.request.urlretrieve(sys.argv[1], 'codex.tar.gz')" \
         "https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-${triple}.tar.gz" \
    && echo "${sum}  codex.tar.gz" | sha256sum -c - \
    && tar -xzf codex.tar.gz && mv "codex-${triple}" codex && chmod 0755 codex \
    && python3 -c "import sys,urllib.request; urllib.request.urlretrieve(sys.argv[1], 'host.tar.gz')" \
         "https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-code-mode-host-${triple}.tar.gz" \
    && echo "${hsum}  host.tar.gz" | sha256sum -c - \
    && tar -xzf host.tar.gz && mv "codex-code-mode-host-${triple}" codex-code-mode-host && chmod 0755 codex-code-mode-host

FROM python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS runtime
LABEL org.opencontainers.image.source="https://github.com/EtharaOrion/nexus" \
      org.opencontainers.image.revision="forge-dhawal-bathre-ethara-ai-20261029t084806z-c525f3" \
      org.opencontainers.image.licenses="proprietary" \
      org.opencontainers.image.base.name="docker.io/library/python:3.13-slim-bookworm"
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
COPY --from=build /opt/venv /opt/venv
COPY --from=codex /build/codex /usr/local/bin/codex
COPY --from=codex /build/codex-code-mode-host /usr/local/bin/codex-code-mode-host
ENV PATH="/opt/venv/bin:${PATH}"
RUN groupadd --gid 1000 verifier \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin verifier \
    && install -d -m 0755 /logs /logs/verifier /app/data \
    && printf '{"session_gap_ms": 30, "allowed_lateness_ms": 60, "checkpoint_interval": 7}\n' > /app/data/config.json
COPY --chown=0:0 . /tests
WORKDIR /tests
USER 0:0
CMD ["/bin/bash", "/tests/test.sh"]
