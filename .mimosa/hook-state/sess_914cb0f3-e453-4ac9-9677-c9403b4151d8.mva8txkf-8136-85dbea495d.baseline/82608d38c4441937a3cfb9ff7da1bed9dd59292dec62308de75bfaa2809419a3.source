from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import admin, auth, companies, costs, jobs, providers, resumes, tasks
from .config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="AI 求职助手平台", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(providers.router)
    app.include_router(companies.router)
    app.include_router(jobs.router)
    app.include_router(resumes.router)
    app.include_router(tasks.router)
    app.include_router(costs.router)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
