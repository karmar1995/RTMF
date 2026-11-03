FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --shell /bin/bash rtmf
COPY docker/evaluator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/configuration ./src/configuration
COPY src/use_case_contracts ./src/use_case_contracts
COPY src/services/__init__.py ./src/services/__init__.py
COPY src/services/evaluator ./src/services/evaluator
RUN mkdir -p ./src/services/use_case
COPY src/services/use_case/__init__.py ./src/services/use_case/__init__.py
COPY src/services/use_case/infra ./src/services/use_case/infra
COPY src/services/use_case/utils ./src/services/use_case/utils
COPY src/adapters ./src/adapters
ENV PYTHONPATH=/app/src
USER rtmf
CMD ["python", "-m", "services.evaluator"]
