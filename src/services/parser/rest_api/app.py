from fastapi import FastAPI
from services.parser.rest_api.routers import create_router
from services.parser.core.service import ParserService

def create_app(parser_service: ParserService) -> FastAPI:
    app = FastAPI(title="RTMF Parser Service")
    app.include_router(create_router(parser_service))
    return app
