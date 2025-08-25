"""
전역 오류 핸들러

FastAPI 애플리케이션용 중앙집중식 오류 처리 제공

주요 기능:
- 커스텀 예외 정의 (Gemini API, Rate limit, 인증 오류)
- 표준화된 오류 응답 형식
- 프로덕션/디버그 모드별 오류 노출 수준 조정
- 구조화된 로깅과 오류 추적

지원하는 오류 유형:
- HTTP 예외 (FastAPI/Starlette)
- 요청 검증 오류 (Pydantic)
- 비즈니스 로직 오류 (커스텀 예외)
- 예상치 못한 시스템 오류
"""

import traceback
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import structlog

from pydantic import BaseModel
from app.config.settings import Settings


logger = structlog.get_logger("error_handler")


class ErrorDetail(BaseModel):
    """오류 상세 정보 모델"""

    message: str
    status_code: int
    timestamp: str
    code: str | None = None
    details: dict[str, object] | None = None


class ErrorResponse(BaseModel):
    """표준화된 오류 응답 모델"""

    error: ErrorDetail


class GeminiAPIError(Exception):
    """Gemini API 전용 커스텀 예외"""

    message: str
    status_code: int
    details: dict[str, object]

    def __init__(
        self,
        message: str,
        status_code: int = 503,
        details: dict[str, object] | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class RateLimitError(Exception):
    """Rate Limiting 전용 커스텀 예외"""

    message: str
    retry_after: int | None

    def __init__(self, message: str, retry_after: int | None = None):
        self.message = message
        self.retry_after = retry_after
        super().__init__(self.message)


class AuthenticationError(Exception):
    """인증 오류 전용 커스텀 예외"""

    message: str

    def __init__(self, message: str = "Authentication required"):
        self.message = message
        super().__init__(self.message)


def create_error_response(
    status_code: int,
    message: str,
    details: dict[str, object] | None = None,
    error_code: str | None = None,
) -> dict[str, object]:
    """
    표준화된 오류 응답 생성

    모든 오류 응답의 일관된 형식 보장:
    - 타임스탬프 포함
    - 상태 코드와 메시지
    - 선택적 상세 정보 및 오류 코드

    Args:
        status_code: HTTP 상태 코드
        message: 오류 메시지
        details: 추가 오류 상세 정보 (선택적)
        error_code: 애플리케이션별 오류 코드 (선택적)

    Returns:
        Dict: 표준화된 오류 응답 딕셔너리
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
    FastAPI 애플리케이션 전역 오류 핸들러 설정

    등록되는 핸들러:
    - HTTPException: 표준 HTTP 오류
    - StarletteHTTPException: Starlette 프레임워크 오류
    - RequestValidationError: 요청 검증 오류
    - GeminiAPIError: Gemini API 관련 오류
    - RateLimitError: Rate Limiting 오류
    - AuthenticationError: 인증 오류
    - Exception: 예상치 못한 일반 오류

    Args:
        app: FastAPI 애플리케이션 인스턴스
        settings: 애플리케이션 설정
    """

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        """표준 HTTP 예외 처리"""
        logger.warning(
            "HTTP exception occurred",
            status_code=exc.status_code,
            detail=exc.detail,
            url=str(request.url),
            method=request.method,
        )

        return JSONResponse(
            status_code=exc.status_code,
            content=create_error_response(
                status_code=exc.status_code, message=exc.detail, error_code="HTTP_ERROR"
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def starlette_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Starlette HTTP 예외 처리"""
        logger.warning(
            "Starlette HTTP exception occurred",
            status_code=exc.status_code,
            detail=exc.detail,
            url=str(request.url),
            method=request.method,
        )

        return JSONResponse(
            status_code=exc.status_code,
            content=create_error_response(
                status_code=exc.status_code,
                message=exc.detail,
                error_code="STARLETTE_ERROR",
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """요청 검증 오류 처리"""
        logger.warning(
            "Request validation error",
            errors=exc.errors(),
            url=str(request.url),
            method=request.method,
        )

        return JSONResponse(
            status_code=422,
            content=create_error_response(
                status_code=422,
                message="Request validation failed",
                details={"validation_errors": exc.errors()},
                error_code="VALIDATION_ERROR",
            ),
        )

    @app.exception_handler(GeminiAPIError)
    async def gemini_api_exception_handler(
        request: Request, exc: GeminiAPIError
    ) -> JSONResponse:
        """Gemini API 전용 오류 처리"""
        logger.error(
            "Gemini API error",
            message=exc.message,
            status_code=exc.status_code,
            details=exc.details,
            url=str(request.url),
            method=request.method,
        )

        return JSONResponse(
            status_code=exc.status_code,
            content=create_error_response(
                status_code=exc.status_code,
                message=exc.message,
                details=exc.details,
                error_code="GEMINI_API_ERROR",
            ),
        )

    @app.exception_handler(RateLimitError)
    async def rate_limit_exception_handler(
        request: Request, exc: RateLimitError
    ) -> JSONResponse:
        """Rate Limiting 오류 처리"""
        logger.warning(
            "Rate limit exceeded",
            message=exc.message,
            retry_after=exc.retry_after,
            url=str(request.url),
            method=request.method,
            client_ip=request.client.host if request.client else None,
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
                error_code="RATE_LIMIT_ERROR",
            ),
            headers=headers,
        )

    @app.exception_handler(AuthenticationError)
    async def authentication_exception_handler(
        request: Request, exc: AuthenticationError
    ) -> JSONResponse:
        """인증 오류 처리"""
        logger.warning(
            "Authentication error",
            message=exc.message,
            url=str(request.url),
            method=request.method,
            client_ip=request.client.host if request.client else None,
        )

        return JSONResponse(
            status_code=401,
            content=create_error_response(
                status_code=401, message=exc.message, error_code="AUTHENTICATION_ERROR"
            ),
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """예상치 못한 예외 처리"""
        error_id = f"error_{int(datetime.now(timezone.utc).timestamp())}"

        logger.error(
            "Unexpected error occurred",
            error_id=error_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
            url=str(request.url),
            method=request.method,
            traceback=traceback.format_exc() if settings and settings.debug else None,
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
                error_code="INTERNAL_ERROR",
            ),
        )
