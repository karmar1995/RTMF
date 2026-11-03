FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --shell /bin/bash rtmf



COPY docker/parser/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/configuration ./src/configuration
COPY src/use_case_contracts ./src/use_case_contracts
COPY src/services/__init__.py ./src/services/__init__.py
COPY src/services/parser ./src/services/parser

ENV PYTHONPATH=/app/src
RUN chown -R rtmf:rtmf /app
USER rtmf
CMD ["python", "-m", "services.parser"]
