FROM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PYTHONDONTWRITEBYTECODE=1 TARND_PORT=8080 TARND_BUDGET=250 TARND_LOG=/results/calls.jsonl
WORKDIR /srv
COPY engine /srv/engine
COPY server.py dbshape.py /srv/
RUN mkdir -p /results && chmod 0755 /results
EXPOSE 8080
CMD ["python3", "/srv/server.py"]
