ARG BUILDKIT_VERSION=v0.31.2
FROM moby/buildkit:${BUILDKIT_VERSION}-rootless AS buildkit

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --shell /bin/bash rtmf
COPY --from=buildkit /usr/bin/buildctl /usr/local/bin/buildctl

COPY docker/simulators_repository/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/configuration ./src/configuration
COPY src/services/__init__.py ./src/services/__init__.py
COPY src/services/simulators_repository ./src/services/simulators_repository
COPY src/use_case_contracts ./src/use_case_contracts

ENV PYTHONPATH=/app/src

USER rtmf

CMD ["python", "-m", "services.simulators_repository"]
