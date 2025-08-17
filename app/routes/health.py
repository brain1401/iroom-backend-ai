"""
Health Check Routes

Provides comprehensive health monitoring endpoints for the application.
Includes basic health, readiness, and liveness probes for Kubernetes deployments.
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, FastAPI
from pydantic import BaseModel

from app.config.settings import Settings, get_settings


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    timestamp: str
    version: str
    uptime_seconds: float
    details: dict[str, object] = {}


class ReadinessResponse(BaseModel):
    """Readiness check response model."""
    ready: bool
    checks: dict[str, bool]
    timestamp: str


# Track application start time
_start_time = time.time()


def get_uptime() -> float:
    """Get application uptime in seconds."""
    return time.time() - _start_time


async def check_gemini_api_health(settings: Settings) -> bool:
    """
    Check if Gemini API is accessible.
    
    Args:
        settings: Application settings
        
    Returns:
        bool: True if API is healthy, False otherwise
    """
    try:
        # Simple check - just verify we have an API key
        # In production, you might want to make a lightweight API call
        return bool(settings.gemini_api_key)
    except Exception:
        return False


async def check_redis_health(settings: Settings) -> bool:
    """
    Check if Redis is accessible (if enabled).
    
    Args:
        settings: Application settings
        
    Returns:
        bool: True if Redis is healthy or disabled, False if enabled but unreachable
    """
    if not settings.redis_enabled:
        return True
    
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_timeout=1)
        r.ping()
        return True
    except Exception:
        return False


def create_health_router(settings: Settings) -> APIRouter:
    """
    Create health check router with all endpoints.
    
    Args:
        settings: Application settings
        
    Returns:
        APIRouter: Configured router with health endpoints
    """
    router = APIRouter(tags=["Health"])
    
    @router.get("/health", response_model=HealthResponse)
    async def health_check():
        """
        Basic health check endpoint.
        
        Returns basic application status and metadata.
        """
        return HealthResponse(
            status="healthy",
            timestamp=datetime.now(timezone.utc).isoformat(),
            version=settings.app_version,
            uptime_seconds=get_uptime(),
            details={
                "app_name": settings.app_name,
                "debug_mode": settings.debug,
                "rate_limiting_enabled": settings.rate_limit_enabled,
                "authentication_required": settings.require_api_key
            }
        )
    
    @router.get("/health/ready", response_model=ReadinessResponse)
    async def readiness_check():
        """
        Readiness probe for Kubernetes deployments.
        
        Checks if the application is ready to serve traffic.
        """
        checks = {
            "gemini_api": await check_gemini_api_health(settings),
            "redis": await check_redis_health(settings)
        }
        
        all_ready = all(checks.values())
        
        response = ReadinessResponse(
            ready=all_ready,
            checks=checks,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        if not all_ready:
            raise HTTPException(status_code=503, detail=response.dict())
        
        return response
    
    @router.get("/health/live")
    async def liveness_check():
        """
        Liveness probe for Kubernetes deployments.
        
        Simple check to verify the application is running.
        """
        return {
            "status": "alive",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": get_uptime()
        }
    
    @router.get("/health/metrics")
    async def metrics_endpoint():
        """
        Basic metrics endpoint.
        
        Provides operational metrics for monitoring.
        """
        # In production, you might integrate with Prometheus here
        return {
            "uptime_seconds": get_uptime(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": settings.app_version,
            "config": {
                "rate_limiting_enabled": settings.rate_limit_enabled,
                "authentication_required": settings.require_api_key,
                "debug_mode": settings.debug
            }
        }
    
    return router


def setup_health_routes(app: FastAPI, settings: Settings | None = None) -> None:
    """
    Setup health check routes for the FastAPI application.
    
    Args:
        app: FastAPI application instance
        settings: Application settings (optional, will get from dependency if not provided)
    """
    if settings is None:
        settings = get_settings()
    
    if settings.health_check_enabled:
        health_router = create_health_router(settings)
        app.include_router(health_router)