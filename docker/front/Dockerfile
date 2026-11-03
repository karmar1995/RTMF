FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --shell /bin/bash rtmf

COPY docker/front/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/configuration ./src/configuration
COPY src/services ./src/services
COPY src/adapters ./src/adapters
COPY src/use_case_contracts ./src/use_case_contracts

ENV PYTHONPATH=/app/src

RUN python -c "from adapters.keycloak_identity_adapter.composition import KeycloakIdentityAdapterContainer; import use_case_contracts; from services.use_case.composition.build_usecases import build_request_usecase_api_provider; import services.front.__main__; import services.front.composition.startup"

USER rtmf

CMD ["python", "-m", "services.front"]
