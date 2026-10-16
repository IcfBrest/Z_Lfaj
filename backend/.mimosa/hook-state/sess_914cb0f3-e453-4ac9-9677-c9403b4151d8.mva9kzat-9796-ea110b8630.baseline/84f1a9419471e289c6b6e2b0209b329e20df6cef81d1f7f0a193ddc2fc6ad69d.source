from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    secret_key: str = "dev-secret-change-me"
    encryption_key: str = ""
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    default_parse_model: str = "deepseek-chat"
    default_score_model: str = "deepseek-chat"
    default_suggest_model: str = "deepseek-chat"

    # 出站解析类请求的最大尺寸与任务等待
    upload_max_bytes: int = 10 * 1024 * 1024
    llm_max_retries: int = 2  # 校验失败后的追加重试次数（不含首次）


@lru_cache
def get_settings() -> Settings:
    return Settings()
