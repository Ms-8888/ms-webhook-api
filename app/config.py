from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    redis_url: str = "redis://localhost:6379"
    secret_key: str = "change-me-in-production"

    class Config:
        env_file = ".env"


settings = Settings()
