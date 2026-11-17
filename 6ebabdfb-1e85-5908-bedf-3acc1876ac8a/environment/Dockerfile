FROM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530
SHELL ["bash", "-o", "pipefail", "-c"]
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WARDD_URL=http://wardd:8080

# The agent runs as uid 1000 (task.toml [agent] user), so it needs an account with a
# home of its own and a writable out/ for its findings.
RUN groupadd --gid 1000 ward && useradd --uid 1000 --gid 1000 --create-home ward

# Every path here is relative to the working directory: the image root until WORKDIR
# names the agent's directory. The client goes on the command path first. The agent
# container holds the client, the specification and a sample world. It never holds the
# engine: .dockerignore keeps wardd/ out of this build context.
COPY client/ward-cli usr/local/bin/ward-cli
RUN chmod 0755 usr/local/bin/ward-cli
WORKDIR app
COPY --chown=1000:1000 docs docs
COPY --chown=1000:1000 sample sample
RUN mkdir -p out && chown 1000:1000 . out
USER root
CMD ["sleep", "infinity"]
