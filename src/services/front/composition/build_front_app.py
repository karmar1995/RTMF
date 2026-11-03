from __future__ import annotations

from dependency_injector import providers

from configuration import load_service_config_into_provider
from services.front import main as front_main
from flask import request

from services.front.auth import RequestBoundUseCases
from services.use_case.composition.build_usecases import build_request_usecase_api_provider


def load_front_config() -> providers.Configuration:
    config = providers.Configuration(strict=True)
    load_service_config_into_provider(config, service_name="front")
    return config


def build_front_app(front_config=None):
    front_config = front_config or load_front_config()
    app = front_main.app
    _apply_flask_config(app, front_config)
    provider = build_request_usecase_api_provider()
    app.extensions["usecases_provider"] = provider
    app.extensions["usecases"] = RequestBoundUseCases(
        provider=provider,
        request=request,
        cookie_name=front_config.authentication.session.cookie_name(),
    )
    return app


def _apply_flask_config(app, config) -> None:
    cookie_name = config.authentication.session.cookie_name()
    secure_cookie = config.authentication.session.secure_cookie.as_(bool)()
    if cookie_name.startswith("__Host-") and not secure_cookie:
        raise RuntimeError(
            "Invalid authentication cookie configuration: __Host- cookies require "
            "secure_cookie=true. Use HTTPS locally or configure a non-prefixed "
            "development cookie name such as 'rtmf_session'."
        )
    app.config["SECRET_KEY"] = config.flask.secret_key()
    app.config["SIM_MODELS_FOLDER"] = config.flask.simulation_models()
    app.config["SIM_RUNS_FOLDER"] = config.flask.simulation_runs()
    app.config["AUTH_SESSION_COOKIE_NAME"] = cookie_name
    app.config["AUTH_SESSION_COOKIE_SECURE"] = secure_cookie
    app.config["AUTH_SESSION_COOKIE_MAX_AGE"] = config.authentication.session.absolute_timeout_seconds.as_int()()
    app.config["AUTH_CALLBACK_URL"] = config.authentication.callback_url()
    app.config["AUTH_ENFORCED"] = True
