# syntax=docker/dockerfile:1
#
# Executor-only base image.
# - Executor venv: /opt/job-executor/.venv (Python 3.12)
# - Workspace: ./workspace under /app
# - Base for all addon images

FROM python:3.12-slim

ENV EXECUTOR_VENV=/opt/job-executor/.venv
ENV PATH="${EXECUTOR_VENV}/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency descriptors first for better caching
COPY pyproject.toml README.md /app/
COPY src /app/src

RUN python -m venv "${EXECUTOR_VENV}" \
    && "${EXECUTOR_VENV}/bin/python" -m pip install --upgrade pip \
    && "${EXECUTOR_VENV}/bin/pip" install --no-cache-dir .

# Ensure relative workspace exists under /app
RUN mkdir -p /app/workspace \
    && chmod 777 /app/workspace

# Default to Job Executor CLI
ENTRYPOINT ["/opt/job-executor/.venv/bin/python", "-m", "composition.entrypoints.cli"]
