from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central app config, loaded from environment variables / .env.

    See .env.example for the full list of variables and what each does.
    """

    database_url: str
    redis_url: str

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    kindling_shield_hours: int = 48
    fade_recovery_margin: float = 0.05

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
