import uvicorn
from services.parser.composition.build_app import create_container

def main() -> None:
    container = create_container()
    
    # We load app dynamically from build_app but here we can just use create_app 
    from services.parser.rest_api.app import create_app
    app = create_app(parser_service=container.parser_service())
    
    uvicorn.run(
        app,
        host=container.config.rest.host(),
        port=container.config.rest.port.as_int()(),
    )
