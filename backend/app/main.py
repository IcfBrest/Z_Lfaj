from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import llm_gateway
from .api import admin, auth, companies, costs, jobs, matches, providers, resumes, scrape, suggestions, tasks
from .config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动阶段预热 LLM SDK。

    首次 import litellm 要 4~7 秒且默认会联网拉价目表；这段时间若落在请求线程里
    会把事件循环一起卡住（首个打分请求超时）。放在 lifespan 里同步预热，此时端口
    已绑定但还没开始服务，用户感知到的只是启动慢几秒。
    """
    llm_gateway.prepare()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="AI 求职助手平台", version="0.1.0", lifespan=lifespan)

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
    app.include_router(matches.router)
    app.include_router(suggestions.router)
    app.include_router(tasks.router)
    app.include_router(costs.router)
    app.include_router(scrape.router)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
