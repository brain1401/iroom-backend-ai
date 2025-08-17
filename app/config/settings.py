"""
Application Configuration Module

Centralized configuration management using Pydantic Settings.
Supports environment variables and .env file loading.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import ClassVar


class Settings(BaseSettings):
    """Application settings with validation and type safety."""

    # pydantic-settings v2 설정 로딩 구성
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App Configuration
    app_name: str = Field(default="Gemini AI Backend", description="Application name")
    app_version: str = Field(default="1.0.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    
    # Server Configuration
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    workers: int = Field(default=1, description="Number of workers")
    
    # Gemini API Configuration
    gemini_api_key: str | None = Field(default=None, description="Google Gemini API Key")
    gemini_model: str = Field(default="gemini-2.5-pro", description="Gemini model name")
    gemini_max_tokens: int = Field(default=32000, description="Max tokens per request")
    gemini_temperature: float = Field(default=0.7, description="Model temperature")
    
    # Rate Limiting Configuration (Gemini 2.5 Pro Limits)
    rate_limit_requests_per_minute: int = Field(
        default=15, 
        description="Requests per minute (Free tier: 15, Paid: 60)"
    )
    rate_limit_tokens_per_day: int = Field(
        default=1000000, 
        description="Tokens per day (Free tier: 1M, Paid: 10M)"
    )
    rate_limit_enabled: bool = Field(default=True, description="Enable rate limiting")
    
    # Redis Configuration (for distributed rate limiting)
    redis_url: str = Field(default="redis://localhost:6379", description="Redis connection URL")
    redis_enabled: bool = Field(default=False, description="Enable Redis for rate limiting")
    
    # CORS Configuration
    cors_origins: list[str] = Field(
        default=["*"], 
        description="Allowed CORS origins"
    )
    cors_allow_credentials: bool = Field(default=True, description="Allow credentials in CORS")
    
    # Authentication Configuration
    api_key_header: str = Field(default="x-api-key", description="API key header name")
    require_api_key: bool = Field(default=False, description="Require API key authentication")
    valid_api_keys: list[str] = Field(default=[], description="List of valid API keys")
    
    # Logging Configuration
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format: json or text")
    
    # Health Check Configuration
    health_check_enabled: bool = Field(default=True, description="Enable health check endpoints")
    
    # v2에서는 model_config로 대체함


# Global settings instance
def get_settings() -> Settings:
    """Get settings instance (can be cached for production)."""
    return Settings()