FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --shell /bin/bash rtmf

COPY docker/matrix_generation/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/configuration ./src/configuration
COPY src/services/__init__.py ./src/services/__init__.py
COPY src/services/matrix_generation ./src/services/matrix_generation
COPY src/adapters/__init__.py ./src/adapters/__init__.py
COPY src/adapters/aistor_matrix_uploader ./src/adapters/aistor_matrix_uploader
COPY src/use_case_contracts ./src/use_case_contracts

ENV PYTHONPATH=/app/src

USER rtmf

CMD ["python", "-m", "services.matrix_generation"]
