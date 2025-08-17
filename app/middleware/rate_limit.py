"""
Rate Limiting Middleware for Gemini 2.5 Pro

Implements sophisticated rate limiting tailored to Gemini API constraints:
- Free tier: 15 RPM, 1M tokens/day
- Paid tier: 60 RPM, 10M tokens/day

Features:
- Request-based limiting (per minute)
- Token-based limiting (per day)
- User-specific quotas
- Circuit breaker pattern
"""

import time
from collections import defaultdict
from collections.abc import Callable, Awaitable

from fastapi import FastAPI, Request, HTTPException
from starlette.responses import Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config.settings import Settings


class TokenCounter:
    """Estimates and tracks token usage for Gemini API calls."""
    
    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        Estimate token count for input text.
        Rough estimation: 1 token ≈ 4 characters for most languages.
        """
        return max(1, len(text) // 4)
    
    @staticmethod
    def estimate_request_tokens(request_data: dict[str, object]) -> int:
        """Estimate tokens for a complete request."""
        if isinstance(request_data, dict) and "input" in request_data:
            input_text = str(request_data["input"])
            return TokenCounter.estimate_tokens(input_text)
        return 100  # Default estimation


class GeminiRateLimiter:
    """
    Advanced rate limiter specifically designed for Gemini 2.5 Pro API.
    
    Tracks both request rates and token consumption per user.
    """
    
    def __init__(self, settings: Settings):
        self.settings: Settings = settings
        self.user_requests: dict[str, list[float]] = defaultdict(list)
        self.user_tokens: dict[str, dict[str, int]] = defaultdict(lambda: {"daily": 0, "last_reset": 0})
        self.circuit_breaker: dict[str, dict[str, object]] = defaultdict(lambda: {
            "failures": 0, 
            "last_failure": 0.0, 
            "state": "closed"  # closed, open, half-open
        })
    
    def _get_user_key(self, request: Request) -> str:
        """Extract user identifier from request."""
        # Try API key from header
        api_key = request.headers.get(self.settings.api_key_header)
        if api_key:
            return f"api_key:{api_key}"
        
        # Fallback to IP address
        return f"ip:{get_remote_address(request)}"
    
    def _reset_daily_tokens_if_needed(self, user_key: str) -> None:
        """Reset daily token count if a new day has started."""
        now = int(time.time())
        today = now // 86400  # Seconds in a day
        
        user_tokens = self.user_tokens[user_key]
        if user_tokens["last_reset"] != today:
            user_tokens["daily"] = 0
            user_tokens["last_reset"] = today
    
    def _check_request_rate(self, user_key: str) -> bool:
        """Check if user is within request rate limits."""
        now = time.time()
        minute_ago = now - 60
        
        # Clean old requests
        self.user_requests[user_key] = [
            req_time for req_time in self.user_requests[user_key] 
            if req_time > minute_ago
        ]
        
        # Check limit
        current_requests = len(self.user_requests[user_key])
        return current_requests < self.settings.rate_limit_requests_per_minute
    
    def _check_token_limit(self, user_key: str, estimated_tokens: int) -> bool:
        """Check if user is within daily token limits."""
        self._reset_daily_tokens_if_needed(user_key)
        
        current_daily = self.user_tokens[user_key]["daily"]
        return (current_daily + estimated_tokens) <= self.settings.rate_limit_tokens_per_day
    
    def _check_circuit_breaker(self, user_key: str) -> bool:
        """Check circuit breaker state for user."""
        cb = self.circuit_breaker[user_key]
        now = time.time()
        
        if cb["state"] == "open":
            # Check if we should transition to half-open
            last_failure_obj = cb["last_failure"]
            assert isinstance(last_failure_obj, (int, float))
            if now - last_failure_obj > 300:  # 5 minutes cooldown
                cb["state"] = "half-open"
                return True
            return False
        
        return True  # closed or half-open allows requests
    
    async def check_limits(self, request: Request, estimated_tokens: int = 0) -> bool:
        """
        Check all rate limits for the request.
        
        Args:
            request: FastAPI request object
            estimated_tokens: Estimated token count for this request
            
        Returns:
            bool: True if request is allowed, False if rate limited
            
        Raises:
            HTTPException: If rate limits are exceeded
        """
        if not self.settings.rate_limit_enabled:
            return True
        
        user_key = self._get_user_key(request)
        
        # Check circuit breaker
        if not self._check_circuit_breaker(user_key):
            raise HTTPException(
                status_code=503,
                detail="Service temporarily unavailable. Please try again later."
            )
        
        # Check request rate limit
        if not self._check_request_rate(user_key):
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {self.settings.rate_limit_requests_per_minute} requests per minute"
            )
        
        # Check token limit
        if estimated_tokens > 0 and not self._check_token_limit(user_key, estimated_tokens):
            raise HTTPException(
                status_code=429,
                detail=f"Daily token limit exceeded: {self.settings.rate_limit_tokens_per_day} tokens per day"
            )
        
        # Record successful request
        now = time.time()
        self.user_requests[user_key].append(now)
        
        if estimated_tokens > 0:
            self.user_tokens[user_key]["daily"] += estimated_tokens
        
        return True
    
    def record_failure(self, request: Request) -> None:
        """Record API failure for circuit breaker."""
        user_key = self._get_user_key(request)
        cb = self.circuit_breaker[user_key]
        
        failures_obj = cb["failures"]
        assert isinstance(failures_obj, int)
        cb["failures"] = failures_obj + 1
        cb["last_failure"] = time.time()
        
        # Open circuit breaker after 5 consecutive failures
        updated_failures = cb["failures"]
        assert isinstance(updated_failures, int)
        if updated_failures >= 5:
            cb["state"] = "open"
    
    def record_success(self, request: Request) -> None:
        """Record API success for circuit breaker."""
        user_key = self._get_user_key(request)
        cb = self.circuit_breaker[user_key]
        
        cb["failures"] = 0
        cb["state"] = "closed"


# Global rate limiter instance
_rate_limiter: GeminiRateLimiter | None = None


def get_rate_limiter() -> GeminiRateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        from app.config.settings import get_settings
        _rate_limiter = GeminiRateLimiter(get_settings())
    return _rate_limiter


async def rate_limit_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """
    Rate limiting middleware for FastAPI.
    
    Checks rate limits before processing requests and records usage.
    """
    rate_limiter = get_rate_limiter()
    
    # Extract estimated tokens from request body if available
    estimated_tokens = 0
    if request.method == "POST" and "gemini" in str(request.url):
        try:
            body = await request.body()
            if body:
                import json
                request_data = json.loads(body)
                estimated_tokens = TokenCounter.estimate_request_tokens(request_data)
                
                # Re-create request with body for downstream processing
                
                async def receive():
                    return {"type": "http.request", "body": body}
                
                request._receive = receive
        except:
            estimated_tokens = 100  # Default estimation on parse error
    
    # Check rate limits
    try:
        await rate_limiter.check_limits(request, estimated_tokens)
    except HTTPException:
        raise
    
    # Process request
    try:
        response = await call_next(request)
        rate_limiter.record_success(request)
        return response
    except Exception:
        rate_limiter.record_failure(request)
        raise


def setup_rate_limiting(app: FastAPI, settings: Settings) -> None:
    """
    Configure rate limiting middleware for the FastAPI application.
    
    Args:
        app: FastAPI application instance
        settings: Application settings
    """
    if settings.rate_limit_enabled:
        # Initialize global rate limiter
        global _rate_limiter
        _rate_limiter = GeminiRateLimiter(settings)
        
        # Add custom middleware
        app.middleware("http")(rate_limit_middleware)
        
        # Setup slowapi for basic rate limiting
        limiter = Limiter(key_func=get_remote_address)
        app.state.limiter = limiter
        
        # 🔧 FastAPI 데코레이터 방식으로 예외 핸들러 등록
        @app.exception_handler(RateLimitExceeded)
        async def handle_rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> Response:
            return _rate_limit_exceeded_handler(request, exc)