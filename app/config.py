from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    redis_url: str = "redis://localhost:6379"

    @field_validator("database_url")
    @classmethod
    def ensure_async_driver(cls, v: str) -> str:
        # Most providers give postgresql:// — asyncpg needs postgresql+asyncpg://
        # Strip ?sslmode=require — asyncpg negotiates SSL automatically
        v = v.split("?")[0]
        if v.startswith("postgresql://") or v.startswith("postgres://"):
            return v.replace("://", "+asyncpg://", 1)
        return v

    class Config:
        env_file = ".env"


settings = Settings()
