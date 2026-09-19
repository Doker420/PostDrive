from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "FlowPay API"
    environment: str = "development"
    database_url: str = "sqlite:///./flowpay.db"
    redis_url: str = "redis://localhost:6379"
    token_secret: str = "change-me-in-production"
    api_key_prefix: str = "fp_live_"
    token_ttl_hours: int = 24
    admin_bootstrap_token: str = "change-me-admin-bootstrap"
    platform_fee_percent: Decimal = Decimal("1.00")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
