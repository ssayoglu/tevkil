from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    bot_token: str = Field("123456789:TEST_BOT_TOKEN_DUMMY", alias="BOT_TOKEN")
    admin_chat_id: int = Field(0, alias="ADMIN_CHAT_ID")

    postgres_user: str = Field("tevkil_user", alias="POSTGRES_USER")
    postgres_password: str = Field("tevkil_secret_pass", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field("tevkil_db", alias="POSTGRES_DB")
    postgres_host: str = Field("localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, alias="POSTGRES_PORT")

    redis_host: str = Field("localhost", alias="REDIS_HOST")
    redis_port: int = Field(6379, alias="REDIS_PORT")

    timeout_minutes: int = Field(30, alias="TIMEOUT_MINUTES")
    ban_duration_days: int = Field(5, alias="BAN_DURATION_DAYS")
    tariff_ban_duration_days: int = Field(15, alias="TARIFF_BAN_DURATION_DAYS")  # Tarife altı teklif doğrudan ban süresi (gün)
    timezone: str = Field("Europe/Istanbul", alias="TIMEZONE")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"


settings = Settings()
