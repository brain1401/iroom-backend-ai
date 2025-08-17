"""
Structured Logging Middleware

Provides comprehensive logging for API requests, responses, and errors.
Supports both JSON and text formats for different deployment environments.
"""

import time
import logging
from datetime import datetime, timezone
from collections.abc import Callable, Awaitable

from fastapi import FastAPI, Request, Response
import structlog

from app.config.settings import Settings


class RequestLoggingMiddleware:
    """Middleware for logging API requests and responses."""
    
    settings: Settings
    logger: structlog.BoundLogger
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = structlog.get_logger("gemini_api")
    
    async def log_request_response(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """
        Log request and response details.
        
        Args:
            request: FastAPI request object
            call_next: Next middleware/handler in chain
            
        Returns:
            Response: FastAPI response object
        """
        start_time = time.time()
        
        # Extract request details
        request_data: dict[str, str | int | dict[str, str] | None] = {
            "method": request.method,
            "url": str(request.url),
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "headers": {
                key: value for key, value in request.headers.items()
                if key.lower() not in ["authorization", self.settings.api_key_header.lower()]
            },
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Try to get request body for POST requests (be careful with large bodies)
        if request.method == "POST":
            try:
                body = await request.body()
                if body and len(body) < 10000:  # Only log small bodies
                    request_data["body_size"] = len(body)
                    # Don't log actual body content for security
                else:
                    request_data["body_size"] = len(body) if body else 0
                
                # Re-create request for downstream processing
                async def receive():
                    return {"type": "http.request", "body": body}
                
                request._receive = receive
            except Exception as e:
                self.logger.warning("Failed to read request body", error=str(e))
        
        # Process request
        response: Response | None = None
        error: Exception | None = None
        
        try:
            response = await call_next(request)
        except Exception as e:
            error = e
            # Create error response for logging and return
            response = Response(
                content="Internal Server Error",
                status_code=500,
                media_type="text/plain"
            )
        finally:
            # Calculate processing time
            process_time = time.time() - start_time
            
            # Prepare response data
            response_data = {
                "status_code": response.status_code if response else 500,
                "process_time_seconds": round(process_time, 4),
                "response_headers": {
                    key: value for key, value in (response.headers.items() if response else [])
                    if key.lower() not in ["set-cookie"]
                }
            }
            
            # Combine request and response data
            log_data = {
                **request_data,
                **response_data,
                "type": "api_request"
            }
            
            # Add error information if present
            if error:
                log_data["error"] = {
                    "type": type(error).__name__,
                    "message": str(error)
                }
            
            # Log with appropriate level
            if error or (response and response.status_code >= 500):
                self.logger.error("API request failed", **log_data)
            elif response and response.status_code >= 400:
                self.logger.warning("API request client error", **log_data)
            else:
                self.logger.info("API request completed", **log_data)
        
        # response가 None인 경우는 있을 수 없지만 타입 체커를 위해 assert 추가
        assert response is not None, "Response should never be None at this point"
        return response


def configure_logging(settings: Settings) -> None:
    """
    Configure structured logging for the application.
    
    Args:
        settings: Application settings
    """
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="ISO"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer() if settings.log_format == "text" else structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.WriteLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(message)s" if settings.log_format == "json" else "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    # Reduce noise from some libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def setup_logging(app: FastAPI, settings: Settings) -> None:
    """
    Setup logging middleware and configuration.
    
    Args:
        app: FastAPI application instance
        settings: Application settings
    """
    # Configure logging
    configure_logging(settings)
    
    # Add request logging middleware
    request_logger = RequestLoggingMiddleware(settings)
    app.middleware("http")(request_logger.log_request_response)
    
    # Log application startup
    logger = structlog.get_logger("app")
    logger.info(
        "Application starting up",
        app_name=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        rate_limiting_enabled=settings.rate_limit_enabled,
        authentication_required=settings.require_api_key
    )