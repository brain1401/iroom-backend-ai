"""
CORS Middleware Configuration

Handles Cross-Origin Resource Sharing for browser-based clients.
Essential for LangServe playground and frontend integrations.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config.settings import Settings


def setup_cors(app: FastAPI, settings: Settings) -> None:
    """
    Configure CORS middleware for the FastAPI application.

    Args:
        app: FastAPI application instance
        settings: Application settings
    """
    # 디버그: 실제 CORS 설정값 확인
    import structlog
    logger = structlog.get_logger("cors")
    logger.info(
        "CORS 설정 적용",
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        origins_count=len(settings.cors_origins)
    )
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
