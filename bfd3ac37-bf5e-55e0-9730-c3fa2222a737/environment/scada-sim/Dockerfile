# syntax=docker/dockerfile:1.12@sha256:93bfd3b68c109427185cd78b4779fc82b484b0b7618e36d0f104d4d801e66d25
# The SCADA sidecar: the deterministic simulator, the pre-admitted seed pool, the API server, and
# the collect step that replays and scores the run. Standard library only. The sim stage gathers
# the runtime files; the runtime stage copies them in, so /opt/scada holds the same bytes and modes.
FROM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530 AS sim
COPY plantsim /build/scada/plantsim
COPY server.py finalize.py seeds.json /build/scada/

FROM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530
LABEL org.opencontainers.image.source="https://github.com/ethara-ai/nexus" \
      org.opencontainers.image.revision="draft" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="docker.io/library/python:3.13-slim-bookworm" \
      org.opencontainers.image.base.digest="sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530"
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PYTHONDONTWRITEBYTECODE=1
RUN groupadd --gid 1500 scada && useradd --uid 1500 --gid 1500 --no-create-home scada \
    && mkdir -p /var/scada/private /var/scada/export \
    && chown -R 1500:1500 /var/scada && chmod 0700 /var/scada/private
COPY --from=sim /build/scada /opt/scada
RUN chmod -R a-w /opt/scada
USER 1500:1500
EXPOSE 8080
CMD ["python3", "/opt/scada/server.py"]
