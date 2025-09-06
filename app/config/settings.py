"""
애플리케이션 구성 모듈

Pydantic Settings 기반 중앙집중식 설정 관리

주요 기능:
- 환경변수와 .env 파일 자동 로딩
- 타입 안전성과 검증 (Pydantic 모델)
- 대소문자 구분 없는 설정 로딩
- UTF-8 인코딩 지원

구성 영역:
- 앱 메타데이터 (이름, 버전, 디버그 모드)
- 서버 설정 (호스트, 포트, 워커)
- Gemini API 설정 (키, 모델, 토큰, 온도)
- Rate Limiting 설정 (Gemini 2.5 Pro 제약 기반)
- Redis 설정 (분산 Rate Limiting용)
- CORS 설정 (브라우저 지원)
- 인증 설정 (API 키 기반)
- 로깅 설정 (레벨, 형식)
- 헬스체크 설정
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import ClassVar


class Settings(BaseSettings):
    """타입 안전성과 검증 기능을 갖춘 애플리케이션 설정"""

    # pydantic-settings v2 설정 로딩 구성
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # 앱 구성
    app_name: str = Field(default="Gemini AI Backend", description="애플리케이션 이름")
    app_version: str = Field(default="1.0.0", description="애플리케이션 버전")
    debug: bool = Field(default=False, description="디버그 모드")

    # 서버 구성
    host: str = Field(default="0.0.0.0", description="서버 호스트")
    port: int = Field(default=8000, description="서버 포트")
    workers: int = Field(default=1, description="워커 프로세스 수")

    # Google Cloud Platform 구성 (Vertex AI)
    gcp_project_id: str = Field(
        default="question-recognition-395816", 
        description="Google Cloud 프로젝트 ID"
    )
    gcp_location: str = Field(
        default="us-central1", 
        description="Vertex AI 리전 (us-central1, asia-northeast3 등)"
    )
    
    # Gemini/Vertex AI 모델 구성
    gemini_model: str = Field(
        default="gemini-2.0-flash-exp",  # Vertex AI 지원 모델
        description="Vertex AI Gemini 모델명"
    )
    gemini_max_tokens: int = Field(default=32000, description="요청당 최대 토큰 수")
    gemini_temperature: float = Field(
        default=0.7, description="모델 온도 (창의성 수준)"
    )
    
    # 레거시 API 키 설정 (OAuth2 전환 후 비활성화)
    gemini_api_key: str | None = Field(
        default=None, 
        description="[DEPRECATED] Google Gemini API 키 - Vertex AI OAuth2 사용"
    )

    # Rate Limiting 구성 (Vertex AI는 더 높은 한도 제공)
    rate_limit_requests_per_minute: int = Field(
        default=60, description="분당 요청 수 (Vertex AI 기준)"
    )
    rate_limit_tokens_per_day: int = Field(
        default=10000000, description="일일 토큰 수 (Vertex AI 기준)"
    )
    rate_limit_enabled: bool = Field(default=True, description="Rate Limiting 활성화")

    # Redis 구성 (분산 Rate Limiting용)
    redis_url: str = Field(
        default="redis://localhost:6379", description="Redis 연결 URL"
    )
    redis_enabled: bool = Field(
        default=False, description="Redis 기반 Rate Limiting 활성화"
    )

    # CORS 구성
    cors_origins: list[str] = Field(default=["*"], description="허용된 CORS 오리진")
    cors_allow_credentials: bool = Field(default=True, description="CORS 자격증명 허용")

    # 인증 구성
    api_key_header: str = Field(default="x-api-key", description="API 키 헤더명")
    require_api_key: bool = Field(default=False, description="API 키 인증 필수 여부")
    valid_api_keys: list[str] = Field(default=[], description="유효한 API 키 목록")

    # 로깅 구성
    log_level: str = Field(default="INFO", description="로그 레벨")
    log_format: str = Field(default="json", description="로그 형식 (json 또는 text)")

    # 헬스체크 구성
    health_check_enabled: bool = Field(
        default=True, description="헬스체크 엔드포인트 활성화"
    )

    # OCR 전용 설정
    ocr_cache_enabled: bool = Field(default=True, description="OCR 결과 캐싱 활성화")
    ocr_cache_ttl: int = Field(default=3600, description="OCR 캐시 TTL (초)")
    ocr_max_batch_size: int = Field(default=20, description="배치 OCR 최대 파일 수")
    ocr_circuit_breaker_enabled: bool = Field(
        default=True, description="OCR 서킷 브레이커 활성화"
    )

    # 모니터링 설정
    metrics_enabled: bool = Field(default=True, description="메트릭 수집 활성화")
    metrics_window_size: int = Field(default=1000, description="메트릭 윈도우 크기")
    alert_enabled: bool = Field(default=True, description="알림 시스템 활성화")

    # 성능 최적화 설정
    max_concurrent_ocr: int = Field(default=5, description="최대 동시 OCR 처리 수")
    memory_cache_size_mb: int = Field(default=100, description="메모리 캐시 크기 (MB)")

    # 데이터베이스 설정
    database_url: str = Field(
        default="mysql://user:password@localhost:3306/iroom_db",
        description="데이터베이스 연결 URL",
    )
    database_pool_size: int = Field(default=10, description="데이터베이스 연결 풀 크기")
    database_pool_timeout: int = Field(
        default=30, description="데이터베이스 연결 타임아웃 (초)"
    )
    database_enabled: bool = Field(
        default=True, description="데이터베이스 사용 여부 (False시 인메모리 모드)"
    )

    # 채점 시스템 설정
    grading_max_concurrent_subjective: int = Field(
        default=3, description="주관식 동시 채점 최대 수"
    )
    grading_ai_model: str = Field(
        default="gemini-2.0-flash-exp", description="채점용 AI 모델 (Vertex AI)"
    )
    grading_confidence_threshold: float = Field(
        default=0.7, description="AI 채점 신뢰도 임계값 (이하시 수동 검토)"
    )


# 전역 설정 인스턴스
def get_settings() -> Settings:
    """설정 인스턴스 반환 (프로덕션에서는 캐시 가능)"""
    return Settings()
