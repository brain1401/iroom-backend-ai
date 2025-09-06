"""
Gemini AI Backend Server

Google Gemini 2.5 Pro API용 프로덕션 FastAPI 서버

주요 기능:
- 모듈형 아키텍처와 관심사 분리
- Gemini API 제약에 최적화된 Rate limiting
- 인증 및 CORS 지원
- 구조화된 로깅과 모니터링
- Kubernetes 배포용 헬스체크
- 오류 처리 및 서킷 브레이커 패턴
"""

import uvicorn
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from dotenv import load_dotenv

from app.config.settings import Settings, get_settings
from app.middleware.cors import setup_cors
from app.middleware.rate_limit import setup_rate_limiting
from app.middleware.auth import setup_authentication
from app.middleware.logging import setup_logging
from app.routes.health import setup_health_routes
from app.routes.gemini import setup_gemini_routes
from app.routes.text_recognition import setup_text_recognition_routes  # 글자인식 (메인)
from app.routes.grading import setup_grading_routes
from app.utils.errors import setup_error_handlers

# Load environment variables early
load_dotenv()


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    FastAPI 인스턴스 생성용 애플리케이션 팩토리

    모든 미들웨어와 라우터 구성 포함한 완전한 앱 인스턴스 생성

    주요 과정:
    1. 설정 로딩 (환경변수 기반)
    2. 미들웨어 체인 구성 (순서 중요)
    3. 라우터 등록
    4. 오류 핸들러 설정
    5. OpenAPI 스키마 커스터마이징

    Args:
        settings: 애플리케이션 설정 (선택적, 미제공시 환경변수에서 로딩)

    Returns:
        FastAPI: 구성 완료된 애플리케이션 인스턴스
    """
    if settings is None:
        settings = get_settings()

    # Create FastAPI app with metadata
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="LangServe 통합 Google Gemini 2.5 Pro 프로덕션 API",
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
    setup_text_recognition_routes(app, settings)  # 글자인식 (메인)
    setup_grading_routes(app, settings)  # 채점 시스템

    # Setup error handlers (should be last)
    setup_error_handlers(app, settings)
    
    # Startup event handler for background tasks
    @app.on_event("startup")
    async def startup_event():
        """앱 시작 시 백그라운드 작업 시작"""
        import asyncio
        from app.routes.text_recognition import _start_polling_background_task
        
        # 폴링 백그라운드 작업 시작
        try:
            asyncio.create_task(_start_polling_background_task())
            import structlog
            logger = structlog.get_logger("startup")
            logger.info("비동기 글자인식 폴링 백그라운드 작업 시작")
        except Exception as e:
            import structlog
            logger = structlog.get_logger("startup")
            logger.error("폴링 백그라운드 작업 시작 실패", error=str(e))

    # Customize OpenAPI schema with security and error responses
    def custom_openapi():
        """
        OpenAPI 스키마 커스터마이제이션

        기능:
        - 보안 스키마 추가 (API 키 인증 활성화시)
        - 오류 응답 모델 추가
        - Rate Limiting 헤더 문서화
        """
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )

        # Add ErrorResponse models to schema components
        from app.utils.errors import ErrorResponse, ErrorDetail

        # Get individual schemas
        error_detail_schema = ErrorDetail.model_json_schema()
        error_response_schema = ErrorResponse.model_json_schema()

        # Ensure components exist
        if "components" not in openapi_schema:
            openapi_schema["components"] = {}
        if "schemas" not in openapi_schema["components"]:
            openapi_schema["components"]["schemas"] = {}

        # Fix ErrorResponse schema to use proper OpenAPI references
        # Remove $defs and update reference to use components/schemas
        if "$defs" in error_response_schema:
            # Extract ErrorDetail from $defs and add it separately
            if "ErrorDetail" in error_response_schema["$defs"]:
                error_detail_from_defs = error_response_schema["$defs"]["ErrorDetail"]
                openapi_schema["components"]["schemas"][
                    "ErrorDetail"
                ] = error_detail_from_defs

            # Remove $defs from ErrorResponse
            error_response_schema = {
                k: v for k, v in error_response_schema.items() if k != "$defs"
            }

            # Update the reference in ErrorResponse
            if (
                "properties" in error_response_schema
                and "error" in error_response_schema["properties"]
                and "$ref" in error_response_schema["properties"]["error"]
            ):
                error_response_schema["properties"]["error"][
                    "$ref"
                ] = "#/components/schemas/ErrorDetail"
        else:
            # If no $defs, add ErrorDetail separately
            openapi_schema["components"]["schemas"]["ErrorDetail"] = error_detail_schema

        # Add the corrected ErrorResponse schema
        openapi_schema["components"]["schemas"]["ErrorResponse"] = error_response_schema

        # 보안 스키마 추가 (인증 활성화시)
        if settings.require_api_key:
            openapi_schema["components"]["securitySchemes"] = {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": settings.api_key_header,
                    "description": f"API 키 인증 - {settings.api_key_header} 헤더 사용",
                },
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "API 키 인증 - Authorization Bearer 토큰 사용",
                },
            }

            # 보안 요구사항을 보호된 엔드포인트에 추가
            for path, methods in openapi_schema["paths"].items():
                # Gemini와 OCR 엔드포인트에 인증 적용 (헬스체크 제외)
                if (path.startswith("/gemini/") and path != "/gemini/health") or (
                    path.startswith("/text-recognition/")
                    and path != "/text-recognition/health"
                ):
                    for method, details in methods.items():
                        if method in ["post", "get"]:
                            details["security"] = [
                                {"ApiKeyAuth": []},
                                {"BearerAuth": []},
                            ]

        # 오류 응답 모델 추가
        error_responses = {
            "400": {
                "description": "Bad Request - 잘못된 요청",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                },
                "headers": {
                    "X-RateLimit-Remaining": {
                        "schema": {"type": "integer"},
                        "description": "남은 요청 수",
                    },
                    "X-RateLimit-Reset": {
                        "schema": {"type": "integer"},
                        "description": "Rate limit 재설정 시간 (Unix timestamp)",
                    },
                },
            },
            "401": {
                "description": "Unauthorized - 인증 실패",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                },
            },
            "403": {
                "description": "Forbidden - 권한 부족",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                },
            },
            "429": {
                "description": "Too Many Requests - Rate limit 초과",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                },
                "headers": {
                    "Retry-After": {
                        "schema": {"type": "integer"},
                        "description": "재시도까지 대기 시간 (초)",
                    },
                    "X-RateLimit-Limit": {
                        "schema": {"type": "integer"},
                        "description": "최대 요청 수",
                    },
                    "X-RateLimit-Remaining": {
                        "schema": {"type": "integer"},
                        "description": "남은 요청 수",
                    },
                    "X-RateLimit-Reset": {
                        "schema": {"type": "integer"},
                        "description": "Rate limit 재설정 시간 (Unix timestamp)",
                    },
                },
            },
            "500": {
                "description": "Internal Server Error - 내부 서버 오류",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                },
            },
            "503": {
                "description": "Service Unavailable - Gemini API 비활성화",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                },
            },
        }

        # 모든 엔드포인트에 오류 응답 추가 (기본 상태 코드 제외)
        for path, methods in openapi_schema["paths"].items():
            for method, details in methods.items():
                if "responses" in details:
                    # 인증이 필요한 엔드포인트에 401 추가
                    if (
                        settings.require_api_key
                        and path.startswith("/gemini/")
                        and path != "/gemini/health"
                    ):
                        details["responses"]["401"] = error_responses["401"]

                    # Rate limiting이 활성화된 엔드포인트에 429 추가
                    if settings.rate_limit_enabled and not path.startswith("/health/"):
                        details["responses"]["429"] = error_responses["429"]

                    # 모든 엔드포인트에 500 추가
                    details["responses"]["500"] = error_responses["500"]

                    # Gemini와 OCR 엔드포인트에 503 추가
                    if path.startswith("/gemini/") or path.startswith(
                        "/text-recognition/"
                    ):
                        details["responses"]["503"] = error_responses["503"]

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi

    return app


# Create the app instance
app = create_app()


def main():
    """
    프로덕션 배포용 메인 서버 진입점

    기본 프로덕션 구성:
    - 단일 워커 구성
    - 로그 레벨 설정 적용
    - 호스트 및 포트 바인딩

    참고:
    - 고트래픽 환경의 경우 Gunicorn 등 WSGI 서버 사용 권장
    """
    settings = get_settings()

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        log_level=settings.log_level.lower(),
    )


def dev_server():
    """
    개발 서버 (핫 리로드 및 디버깅 기능)

    활성화 기능:
    - 코드 변경 시 자동 리로드
    - 상세 오류 메시지와 디버그 모드
    - API 문서화 엔드포인트
    - 액세스 로그 출력
    """
    settings = get_settings()

    uvicorn.run(
        "app.server:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        reload_dirs=["app"],
        log_level="debug",
        access_log=True,
    )


def prod_server():
    """
    최적화된 프로덕션 서버

    프로덕션 최적화 기능:
    - 동시성 향상을 위한 멀티 워커
    - 프로덕션 로깅 구성
    - 컨테이너 배포 최적화
    - 보안 헤더 비활성화

    성능 고려사항:
    - I/O 바운드 LLM API 특성상 워커 수 증가 가능
    - 커스텀 로깅 사용으로 액세스 로그 비활성화
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
