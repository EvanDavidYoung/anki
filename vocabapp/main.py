from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_app_settings
from .db import init_schema
from .routers import anki, cards, quiz, sessions, study


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_schema()
    yield


app = FastAPI(title="Chinese Vocab Quiz", lifespan=lifespan)

# Vite dev server runs on 5173 and proxies /api, but keep CORS open for the
# case where the frontend is opened directly against a remote backend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (sessions, cards, quiz, study, anki):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    return {"ok": True}


def _mount_frontend() -> None:
    dist = get_app_settings().frontend_dist
    if not dist.is_dir():
        return  # dev mode: Vite serves the UI

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        candidate = dist / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


_mount_frontend()
