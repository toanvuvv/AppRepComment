import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.routers.knowledge import router as knowledge_router
from app.routers.nick_live import router as nick_live_router
from app.routers.settings import router as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Load persisted moderator configs into memory cache
    from app.services.live_moderator import moderator
    moderator.load_all_from_db()
    yield


is_dev = os.getenv("ENV", "development") == "development"

app = FastAPI(
    title="App Rep Comment",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if is_dev else None,
    redoc_url="/redoc" if is_dev else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-API-Key"],
)

app.include_router(nick_live_router)
app.include_router(settings_router)
app.include_router(knowledge_router)


@app.get("/api/health")
@app.get("/health")
def health_check():
    return {"status": "ok"}
