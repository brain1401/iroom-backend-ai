"""
Global Error Handlers

Provides centralized error handling for the FastAPI application.
Includes custom exceptions and standardized error responses.
"""

import traceback
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import structlog

from app.config.settings import Settings


logger = structlog.get_logger("error_handler")


class GeminiAPIError(Exception):
    """Custom exception for Gemini API errors."""
    
    message: str
    status_code: int
    details: dict[str, object]
    
    def __init__(self, message: str, status_code: int = 503, details: dict[str, object] | None = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class RateLimitError(Exception):
    """Custom exception for rate limiting errors."""
    
    message: str
    retry_after: int | None
    
    def __init__(self, message: str, retry_after: int | None = None):
        self.message = message
        self.retry_after = retry_after
        super().__init__(self.message)


class AuthenticationError(Exception):
    """Custom exception for authentication errors."""
    
    message: str
    
    def __init__(self, message: str = "Authentication required"):
        self.message = message
        super().__init__(self.message)


def create_error_response(
    status_code: int,
    message: str,
    details: dict[str, object] | None = None,
    error_code: str | None = None
) -> dict[str, object]:
    """
    Create standardized error response.
    
    Args:
        status_code: HTTP status code
        message: Error message
        details: Additional error details
        error_code: Application-specific error code
        
    Returns:
        Dict: Standardized error response
    """
    error_response: dict[str, object] = {
        "error": {
            "message": message,
            "status_code": status_code,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    }
    
    if error_code:
        error_dict = error_response["error"]
        assert isinstance(error_dict, dict)
        error_dict["code"] = error_code
    
    if details:
        error_dict = error_response["error"] 
        assert isinstance(error_dict, dict)
        error_dict["details"] = details
    
    return error_response


def setup_error_handlers(app: FastAPI, settings: Settings | None = None) -> None:
    """
    Setup global error handlers for the FastAPI application.
    
    Args:
        app: FastAPI application instance
        settings: Application settings
    """
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """Handle standard HTTP exceptions."""
        logger.warning(
            "HTTP exception occurred",
            status_code=exc.status_code,
            detail=exc.detail,
            url=str(request.url),
            method=request.method
        )
        
        return JSONResponse(
            status_code=exc.status_code,
            content=create_error_response(
                status_code=exc.status_code,
                message=exc.detail,
                error_code="HTTP_ERROR"
            )
        )
    
    @app.exception_handler(StarletteHTTPException)
    async def starlette_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Handle Starlette HTTP exceptions."""
        logger.warning(
            "Starlette HTTP exception occurred",
            status_code=exc.status_code,
            detail=exc.detail,
            url=str(request.url),
            method=request.method
        )
        
        return JSONResponse(
            status_code=exc.status_code,
            content=create_error_response(
                status_code=exc.status_code,
                message=exc.detail,
                error_code="STARLETTE_ERROR"
            )
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Handle request validation errors."""
        logger.warning(
            "Request validation error",
            errors=exc.errors(),
            url=str(request.url),
            method=request.method
        )
        
        return JSONResponse(
            status_code=422,
            content=create_error_response(
                status_code=422,
                message="Request validation failed",
                details={"validation_errors": exc.errors()},
                error_code="VALIDATION_ERROR"
            )
        )
    
    @app.exception_handler(GeminiAPIError)
    async def gemini_api_exception_handler(request: Request, exc: GeminiAPIError) -> JSONResponse:
        """Handle Gemini API specific errors."""
        logger.error(
            "Gemini API error",
            message=exc.message,
            status_code=exc.status_code,
            details=exc.details,
            url=str(request.url),
            method=request.method
        )
        
        return JSONResponse(
            status_code=exc.status_code,
            content=create_error_response(
                status_code=exc.status_code,
                message=exc.message,
                details=exc.details,
                error_code="GEMINI_API_ERROR"
            )
        )
    
    @app.exception_handler(RateLimitError)
    async def rate_limit_exception_handler(request: Request, exc: RateLimitError) -> JSONResponse:
        """Handle rate limiting errors."""
        logger.warning(
            "Rate limit exceeded",
            message=exc.message,
            retry_after=exc.retry_after,
            url=str(request.url),
            method=request.method,
            client_ip=request.client.host if request.client else None
        )
        
        headers = {}
        if exc.retry_after:
            headers["Retry-After"] = str(exc.retry_after)
        
        return JSONResponse(
            status_code=429,
            content=create_error_response(
                status_code=429,
                message=exc.message,
                details={"retry_after": exc.retry_after} if exc.retry_after else None,
                error_code="RATE_LIMIT_ERROR"
            ),
            headers=headers
        )
    
    @app.exception_handler(AuthenticationError)
    async def authentication_exception_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
        """Handle authentication errors."""
        logger.warning(
            "Authentication error",
            message=exc.message,
            url=str(request.url),
            method=request.method,
            client_ip=request.client.host if request.client else None
        )
        
        return JSONResponse(
            status_code=401,
            content=create_error_response(
                status_code=401,
                message=exc.message,
                error_code="AUTHENTICATION_ERROR"
            )
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle unexpected exceptions."""
        error_id = f"error_{int(datetime.now(timezone.utc).timestamp())}"
        
        logger.error(
            "Unexpected error occurred",
            error_id=error_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
            url=str(request.url),
            method=request.method,
            traceback=traceback.format_exc() if settings and settings.debug else None
        )
        
        # Don't expose internal error details in production
        message = str(exc) if settings and settings.debug else "Internal server error"
        details: dict[str, object] = {"error_id": error_id}
        
        if settings and settings.debug:
            details["traceback"] = traceback.format_exc()
        
        return JSONResponse(
            status_code=500,
            content=create_error_response(
                status_code=500,
                message=message,
                details=details,
                error_code="INTERNAL_ERROR"
            )
        )