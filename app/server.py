"""
Gemini AI Backend Server

Production-ready FastAPI server for Google Gemini 2.5 Pro API.
Features:
- Modular architecture with separation of concerns
- Rate limiting tailored to Gemini API limits
- Authentication and CORS support
- Structured logging and monitoring
- Health checks for Kubernetes deployments
- Error handling and circuit breaker patterns
"""

import uvicorn
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from dotenv import load_dotenv

# Load environment variables early
load_dotenv()

from app.config.settings import Settings, get_settings
from app.middleware.cors import setup_cors
from app.middleware.rate_limit import setup_rate_limiting
from app.middleware.auth import setup_authentication
from app.middleware.logging import setup_logging
from app.routes.health import setup_health_routes
from app.routes.gemini import setup_gemini_routes
from app.utils.errors import setup_error_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Application factory for creating FastAPI instance with all middleware and routes.
    
    Args:
        settings: Application settings (optional, will load from environment if not provided)
        
    Returns:
        FastAPI: Configured application instance
    """
    if settings is None:
        settings = get_settings()
    
    # Create FastAPI app with metadata
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Production-ready API for Google Gemini 2.5 Pro with LangServe integration",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    
    # Setup middleware (order matters!)
    setup_logging(app, settings)  # Should be first for request/response logging
    setup_cors(app, settings)
    setup_authentication(app, settings)
    setup_rate_limiting(app, settings)
    
    # Setup routes
    setup_health_routes(app, settings)
    setup_gemini_routes(app, settings)
    
    # Setup error handlers (should be last)
    setup_error_handlers(app, settings)
    
    return app


# Create the app instance
app = create_app()


def main():
    """
    Main server entry point for production deployment.
    
    Basic production configuration with single worker.
    For high-traffic deployments, consider using Gunicorn or similar WSGI server.
    """
    settings = get_settings()
    
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        log_level=settings.log_level.lower()
    )


def dev_server():
    """
    Development server with hot reload and debugging features.
    
    Enables:
    - Hot reload on code changes
    - Debug mode with detailed error messages
    - API documentation endpoints
    """
    settings = get_settings()
    
    uvicorn.run(
        "app.server:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        reload_dirs=["app"],
        log_level="debug",
        access_log=True
    )


def prod_server():
    """
    Production server with optimized settings.
    
    Features:
    - Multiple workers for better concurrency
    - Production logging configuration
    - Optimized for containerized deployments
    """
    settings = get_settings()
    
    # Determine optimal worker count
    # For I/O bound applications like LLM APIs, we can use more workers
    worker_count = max(1, settings.workers)
    
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        workers=worker_count,
        log_level=settings.log_level.lower(),
        access_log=False,  # Disable access log in production (we have custom logging)
        server_header=False,  # Security: don't expose server info
        date_header=False,  # Security: don't expose date info
    )


if __name__ == "__main__":
    main()
