import sys
import os
from pathlib import Path

# Dodajemy folder 'src' do ścieżki Pythona, żeby poprawnie importował 'services.parser'
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))

import uvicorn

from services.parser.core.service import ParserService
from services.parser.rest_api.app import create_app

def main() -> None:
    # W testowym środowisku tworzymy lokalny katalog wewnątrz modułu parser
    test_jobs_dir = Path(__file__).resolve().parent.parent.parent / "workspace"
    
    # Inicjalizujemy serwis parsera z "twardą" zależnością do testowego katalogu
    parser_service = ParserService(tasks_dir=str(test_jobs_dir))

    # Tworzymy aplikację FastAPI
    app = create_app(parser_service)
    
    # Uruchamiamy serwer (port 8005 jako domyślny port dla parsera w testach)
    uvicorn.run(app, host="0.0.0.0", port=8005)

if __name__ == "__main__":
    main()
