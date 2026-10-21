from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (or a local .env file).

    DATABASE_URL and SECRET_KEY have no defaults on purpose: the app refuses to
    start without them rather than silently running with insecure values.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    sql_echo: bool = False

    # Development helper: create demo users on first start. Off by default.
    seed_demo_users: bool = False
    seed_password: str | None = None

    # Failed logins allowed per client IP within the window before a 429.
    login_max_failures: int = 10
    login_window_seconds: int = 60

    @field_validator("secret_key")
    @classmethod
    def _secret_long_enough(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return value


settings = Settings()
