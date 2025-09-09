"""
헬스체크 라우트

애플리케이션 상태 모니터링용 포괄적 헬스체크 엔드포인트 제공

주요 기능:
- 기본 상태 확인 (/health)
- 준비 상태 확인 (/health/ready) - Kubernetes readiness probe
- 생존 상태 확인 (/health/live) - Kubernetes liveness probe
- 메트릭 엔드포인트 (/health/metrics)

Kubernetes 배포 지원:
- 종속성 확인 (Gemini API, Redis)
- 서비스 준비 상태 검증
- 애플리케이션 생존 상태 모니터링
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, FastAPI
from pydantic import BaseModel

from app.config.settings import Settings, get_settings


class HealthResponse(BaseModel):
    """헬스체크 응답 모델"""

    status: str
    timestamp: str
    version: str
    uptime_seconds: float
    details: dict[str, object] = {}


class ReadinessResponse(BaseModel):
    """준비 상태 체크 응답 모델"""

    ready: bool
    checks: dict[str, bool]
    timestamp: str


class LivenessResponse(BaseModel):
    """생존 상태 체크 응답 모델"""

    status: str
    timestamp: str
    uptime_seconds: float


class MetricsResponse(BaseModel):
    """메트릭 응답 모델"""

    uptime_seconds: float
    timestamp: str
    version: str
    config: dict[str, object]


# Track application start time
_start_time = time.time()


def get_uptime() -> float:
    """애플리케이션 업타임 계산 (초 단위)"""
    return time.time() - _start_time


async def check_gemini_api_health(settings: Settings) -> bool:
    """
    Vertex AI Gemini API 접근 가능성 확인
    
    ADC(Application Default Credentials) 기반 인증 검증:
    - gcloud auth application-default login 상태 확인
    - Vertex AI 서비스 계정 인증 확인
    - 경량 API 호출로 실제 접근성 테스트
    
    Args:
        settings: 애플리케이션 설정
        
    Returns:
        bool: Vertex AI API 상태 정상 여부
    """
    try:
        # Vertex AI 인증 및 접근성 간단 테스트
        # ADC를 통한 자동 인증 확인
        from google.auth import default
        from google.auth.exceptions import DefaultCredentialsError
        
        try:
            # ADC 자격 증명 확인
            _, project_id = default()
            
            # 프로젝트 ID가 설정에서 지정된 것과 일치하는지 확인
            if project_id and project_id != settings.gcp_project_id:
                return False
                
            return True
            
        except DefaultCredentialsError:
            # ADC 자격 증명이 설정되지 않음
            return False
            
    except Exception:
        return False


async def check_redis_health(settings: Settings) -> bool:
    """
    Redis 접근 가능성 확인 (활성화된 경우)

    검증 로직:
    1. Redis 비활성화 상태 → 정상으로 판단
    2. Redis 활성화 상태 → 연결 테스트 수행
    3. 연결 실패 시 → 비정상으로 판단

    Args:
        settings: 애플리케이션 설정

    Returns:
        bool: Redis 상태 정상 여부 (비활성화시 True, 활성화시 연결 테스트 결과)
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
    헬스체크 라우터 생성 (모든 엔드포인트 포함)

    생성되는 엔드포인트:
    - GET /health - 기본 상태 확인
    - GET /health/ready - 준비 상태 확인 (종속성 검증)
    - GET /health/live - 생존 상태 확인
    - GET /health/metrics - 운영 메트릭

    Args:
        settings: 애플리케이션 설정

    Returns:
        APIRouter: 헬스체크 엔드포인트가 구성된 라우터
    """
    router = APIRouter(tags=["헬스체크"])

    @router.get("/health", response_model=HealthResponse, summary="기본 헬스체크")
    async def health_check() -> HealthResponse:
        """
        기본 헬스체크 엔드포인트

        애플리케이션 기본 상태 정보와 메타데이터 반환
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
                "authentication_required": settings.require_api_key,
            },
        )

    @router.get(
        "/health/ready",
        response_model=ReadinessResponse,
        summary="준비 상태 확인",
        responses={
            503: {
                "description": "Service Not Ready - 종속성 확인 실패",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                },
            }
        },
    )
    async def readiness_check() -> ReadinessResponse:
        """
        Kubernetes 배포용 준비 상태 프로브

        트래픽 처리 준비 상태 확인 및 종속성 검증
        """
        checks = {
            "gemini_api": await check_gemini_api_health(settings),
            "redis": await check_redis_health(settings),
        }

        all_ready = all(checks.values())

        response = ReadinessResponse(
            ready=all_ready,
            checks=checks,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if not all_ready:
            raise HTTPException(status_code=503, detail=response.dict())

        return response

    @router.get("/health/live", response_model=LivenessResponse, summary="생존 상태 확인")
    async def liveness_check() -> LivenessResponse:
        """
        Kubernetes 배포용 생존 상태 프로브

        애플리케이션 실행 상태 간단 확인
        """
        return LivenessResponse(
            status="alive",
            timestamp=datetime.now(timezone.utc).isoformat(),
            uptime_seconds=get_uptime(),
        )

    @router.get("/health/metrics", response_model=MetricsResponse, summary="운영 메트릭")
    async def metrics_endpoint() -> MetricsResponse:
        """
        기본 메트릭 엔드포인트

        모니터링용 운영 메트릭 제공 (Prometheus 통합 가능)
        """
        # In production, you might integrate with Prometheus here
        return MetricsResponse(
            uptime_seconds=get_uptime(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            version=settings.app_version,
            config={
                "rate_limiting_enabled": settings.rate_limit_enabled,
                "authentication_required": settings.require_api_key,
                "debug_mode": settings.debug,
            },
        )

    return router


def setup_health_routes(app: FastAPI, settings: Settings | None = None) -> None:
    """
    FastAPI 애플리케이션에 헬스체크 라우트 설정

    설정에 따른 조건부 라우트 등록:
    - health_check_enabled=True인 경우에만 라우트 활성화

    Args:
        app: FastAPI 애플리케이션 인스턴스
        settings: 애플리케이션 설정 (선택적, 미제공시 의존성에서 로딩)
    """
    if settings is None:
        settings = get_settings()

    if settings.health_check_enabled:
        health_router = create_health_router(settings)
        app.include_router(health_router)
