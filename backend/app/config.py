from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Project Helper"
    database_url: str = "sqlite:///./storage/project_helper.db"
    repo_storage_dir: Path = Path("./storage/repos")
    git_clone_timeout_seconds: int = 120
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    model_provider: str = "deepseek"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_temperature: float = Field(default=0.2, ge=0, le=2)

    mimo_api_key: str = ""
    mimo_base_url: str = "https://api.xiaomimimo.com/v1"
    mimo_model: str = "mimo-v2.5-pro"
    mimo_temperature: float = Field(default=0.2, ge=0, le=2)
    mimo_top_p: float = Field(default=0.95, ge=0, le=1)
    mimo_max_completion_tokens: int = Field(default=4096, ge=1)
    mimo_disable_thinking: bool = True

    ark_api_key: str = ""
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3/responses"
    ark_model: str = "deepseek-v3-2-251201"
    ark_temperature: float = Field(default=0.2, ge=0, le=2)
    ark_enable_web_search: bool = False
    ark_web_search_max_keyword: int = 3
    ark_timeout_seconds: int = 120

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
