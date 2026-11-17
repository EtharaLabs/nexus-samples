# syntax=docker/dockerfile:1.12@sha256:93bfd3b68c109427185cd78b4779fc82b484b0b7618e36d0f104d4d801e66d25
# The EMS simulator sidecar: the shared plantops server and collect step, the island microgrid
# simulator (plantsim), and the pre-admitted seed pool. Standard library only.
FROM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530
LABEL org.opencontainers.image.source="https://github.com/ethara-ai/nexus" \
      org.opencontainers.image.revision="draft" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="docker.io/library/python:3.13-slim-bookworm" \
      org.opencontainers.image.base.digest="sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530"
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/ems
RUN groupadd --gid 1500 ems && useradd --uid 1500 --gid 1500 --no-create-home ems \
    && mkdir -p /opt/ems /var/ems/private /var/ems/export \
    && chown -R 1500:1500 /var/ems && chmod 0700 /var/ems/private
COPY plantops /opt/ems/plantops
COPY plantsim /opt/ems/plantsim
COPY seeds.json /opt/ems/seeds.json
RUN chmod -R a-w /opt/ems
WORKDIR /opt/ems
USER 1500:1500
EXPOSE 8080
CMD ["python3", "-m", "plantops.server"]
