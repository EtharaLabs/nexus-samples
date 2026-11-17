FROM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530
SHELL ["bash", "-o", "pipefail", "-c"]
ENV PYTHONDONTWRITEBYTECODE=1 WARDD_PORT=8080 WARDD_BUDGET=240
# The server finds the engine beside itself and writes the call log to results/ beside
# itself, the directory docker-compose.yaml mounts the call-log volume on.
WORKDIR srv
COPY engine engine
COPY server.py server.py
CMD ["python3", "server.py"]
