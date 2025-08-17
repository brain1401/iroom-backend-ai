"""
Authentication Middleware

Provides API key-based authentication for securing Gemini API access.
Supports both required and optional authentication modes.
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.security import HTTPBearer

from app.config.settings import Settings


class APIKeyAuth:
    """API Key authentication handler."""
    
    settings: Settings
    security: HTTPBearer
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.security = HTTPBearer(auto_error=False)
    
    async def verify_api_key(self, request: Request) -> str | None:
        """
        Verify API key from request headers.
        
        Args:
            request: FastAPI request object
            
        Returns:
            str: Valid API key if found, None otherwise
            
        Raises:
            HTTPException: If authentication is required but invalid
        """
        # Try API key from custom header
        api_key = request.headers.get(self.settings.api_key_header)
        
        # Try Authorization header as fallback
        if not api_key:
            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                api_key = auth_header[7:]  # Remove "Bearer " prefix
        
        # Check if API key is required
        if self.settings.require_api_key:
            if not api_key:
                raise HTTPException(
                    status_code=401,
                    detail=f"API key required in '{self.settings.api_key_header}' header or Authorization Bearer token"
                )
            
            if api_key not in self.settings.valid_api_keys:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid API key"
                )
        
        return api_key if api_key in self.settings.valid_api_keys else None


# Global auth instance
_auth_handler: APIKeyAuth | None = None


def get_auth_handler() -> APIKeyAuth:
    """Get the global authentication handler."""
    global _auth_handler
    if _auth_handler is None:
        from app.config.settings import get_settings
        _auth_handler = APIKeyAuth(get_settings())
    return _auth_handler


async def verify_api_key(request: Request) -> str | None:
    """
    FastAPI dependency to verify API key.
    
    Args:
        request: FastAPI request object
        
    Returns:
        str | None: Valid API key if authenticated, None otherwise
    """
    auth_handler = get_auth_handler()
    return await auth_handler.verify_api_key(request)


async def require_api_key(request: Request) -> str:
    """
    FastAPI dependency that requires valid API key.
    
    Args:
        request: FastAPI request object
        
    Returns:
        str: Valid API key
        
    Raises:
        HTTPException: If API key is invalid or missing
    """
    auth_handler = get_auth_handler()
    api_key = await auth_handler.verify_api_key(request)
    
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Valid API key required"
        )
    
    return api_key


def setup_authentication(app: FastAPI, settings: Settings) -> None:
    """
    Configure authentication for the FastAPI application.
    
    Args:
        app: FastAPI application instance
        settings: Application settings
    """
    # Initialize global auth handler
    global _auth_handler
    _auth_handler = APIKeyAuth(settings)
    
    # Add authentication info to OpenAPI docs
    if settings.require_api_key:
        app.openapi_tags = [
            {
                "name": "Authentication",
                "description": f"API key required in '{settings.api_key_header}' header"
            }
        ]