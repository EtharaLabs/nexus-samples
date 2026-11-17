# syntax=docker/dockerfile:1.12@sha256:93bfd3b68c109427185cd78b4779fc82b484b0b7618e36d0f104d4d801e66d25
FROM --platform=$BUILDPLATFORM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530 AS wheels
ARG TARGETOS
ARG TARGETARCH
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
WORKDIR /build
COPY requirements.txt ./
RUN for req in requirements.txt; do \
      pip download --no-deps --require-hashes --only-binary=:all: \
        --platform "manylinux2014_$( [ "$TARGETARCH" = arm64 ] && echo aarch64 || echo x86_64 )" \
        --platform "manylinux_2_28_$( [ "$TARGETARCH" = arm64 ] && echo aarch64 || echo x86_64 )" \
        --python-version 3.13 --implementation cp -d /build/wheels -r "$req" || exit 1; \
    done

FROM --platform=$BUILDPLATFORM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530 AS rewardkit
ARG HARBOR_COMMIT=fdba28fc411e47e8765420a1a063b4918fce3def
ARG HARBOR_ARCHIVE_SHA256=2a2e7fd5a87e533b8ecc014836dd78c160a7dd445629ee9795b682d3be5004f9
ARG REWARDKIT_PYPROJECT_SHA256=df84f9a3205e40cb44f0683bf590813b7beafefa2b76dc11aa4e3431c3cc789e
ARG REWARDKIT_VERSION=0.2.4
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
WORKDIR /build
RUN printf '%s\n' 'uv_build==0.10.12 --hash=sha256:7ab118c31728f7e5192781e58eb7bf18b33f4e6b46675baaa31f266c3c33248f --hash=sha256:bb1122894d134ead39b772eb8ec4b9931dea7f6d2c90235b6c323d322d2f61ad' >build-requirements.txt \
    && pip install --no-cache-dir --only-binary=:all: --require-hashes -r build-requirements.txt \
    && python3 -c "import sys,urllib.request; urllib.request.urlretrieve(sys.argv[1], 'harbor.tar.gz')" \
         "https://codeload.github.com/harbor-framework/harbor/tar.gz/${HARBOR_COMMIT}" \
    && echo "${HARBOR_ARCHIVE_SHA256}  harbor.tar.gz" | sha256sum -c - \
    && tar -xzf harbor.tar.gz "harbor-${HARBOR_COMMIT}/packages/rewardkit" \
    && src="harbor-${HARBOR_COMMIT}/packages/rewardkit" \
    && echo "${REWARDKIT_PYPROJECT_SHA256}  ${src}/pyproject.toml" | sha256sum -c - \
    && grep -qx "version = \"${REWARDKIT_VERSION}\"" "${src}/pyproject.toml" \
    && pip wheel --no-cache-dir --no-deps --no-build-isolation -w /build/rewardkit "${src}" \
    && test -f "/build/rewardkit/harbor_rewardkit-${REWARDKIT_VERSION}-py3-none-any.whl"

FROM --platform=$BUILDPLATFORM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530 AS codex
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

FROM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
COPY --from=wheels /build/wheels /tmp/wheels
COPY --from=rewardkit /build/rewardkit /tmp/rewardkit
COPY --from=codex --chown=0:0 /build/codex /usr/local/bin/codex
COPY --from=codex --chown=0:0 /build/codex-code-mode-host /usr/local/bin/codex-code-mode-host
COPY requirements.txt /tmp/
# The grader's packages go into the system Python. The simulator is standard library only.
RUN pip install --no-cache-dir --no-index --require-hashes --find-links /tmp/wheels -r /tmp/requirements.txt \
    && pip install --no-cache-dir --no-index --no-deps /tmp/rewardkit/harbor_rewardkit-0.2.4-py3-none-any.whl \
    && python3 -c "import importlib.metadata as m; assert m.version('harbor-rewardkit') == '0.2.4'" \
    && pip check \
    && rm -rf /tmp/wheels /tmp/rewardkit /tmp/requirements.txt /root/.cache \
    && mkdir -p /workspace /logs/verifier
# No simulator here: the scada-sim collect step replays and scores O1-O4; grade.py reads its export.
COPY test.sh reward.toml judge.toml test_output.py grade.py /tests/
RUN chmod 0755 /tests/test.sh && chmod 0444 /tests/*.py /tests/*.toml
ENV PYTHONPATH=/tests PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace
CMD ["/bin/bash"]
