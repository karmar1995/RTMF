FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

ARG RTMF_UID=1013
ARG RTMF_GID=1013

RUN groupadd --gid "${RTMF_GID}" rtmf \
    && useradd \
        --uid "${RTMF_UID}" \
        --gid "${RTMF_GID}" \
        --create-home \
        --shell /bin/bash \
        --no-log-init \
        rtmf

COPY docker/jobs_scheduler/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/configuration ./src/configuration
COPY src/services/__init__.py ./src/services/__init__.py
COPY src/services/jobs_scheduler ./src/services/jobs_scheduler
RUN mkdir -p ./src/services/use_case
COPY src/services/use_case/__init__.py ./src/services/use_case/__init__.py
COPY src/services/use_case/infra ./src/services/use_case/infra
COPY src/services/use_case/utils ./src/services/use_case/utils
COPY src/adapters/__init__.py ./src/adapters/__init__.py
COPY src/adapters/slurm_adapter ./src/adapters/slurm_adapter
COPY src/adapters/postgres_jobs_repository ./src/adapters/postgres_jobs_repository
COPY src/adapters/postgres_evaluations_store ./src/adapters/postgres_evaluations_store
COPY src/use_case_contracts ./src/use_case_contracts

ENV PYTHONPATH=/app/src

ARG SLURM_UID=995
ARG SLURM_GID=995

RUN groupadd --system --gid "${SLURM_GID}" slurm \
    && useradd \
        --system \
        --uid "${SLURM_UID}" \
        --gid "${SLURM_GID}" \
        --no-create-home \
        --home-dir /nonexistent \
        --shell /usr/sbin/nologin \
        slurm

USER rtmf

CMD ["python", "-m", "services.jobs_scheduler"]
