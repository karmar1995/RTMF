import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from services.system_discovery.app.api.routes import training, simulation
from services.system_discovery.app.services.cleanup_service import start_periodic_cleanup

app = FastAPI(
    title="RTMF System Discovery Service",
    description="API for System Discovery model training and simulation",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    # Start periodic storage cleanup in the background (every 24 hours)
    asyncio.create_task(start_periodic_cleanup())

app.include_router(training.router, prefix="/api/v1")
app.include_router(simulation.router, prefix="/api/v1")

