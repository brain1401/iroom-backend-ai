"""
공통 데이터 모델

여러 도메인에서 공유되는 기본 모델과 열거형 정의
일관된 데이터 구조와 타입 안전성 제공

주요 구성 요소:
- BaseEntity: 공통 엔티티 기본 클래스 (ID, 생성/수정 시간)
- ProcessingStatus: 처리 상태 공통 열거형
- Priority: 우선순위 공통 열거형
- ResponseMetadata: 공통 메타데이터 모델

사용 예시:
- 글자인식, 채점, 모니터링 등 모든 도메인에서 재사용
- 일관된 응답 형식과 상태 관리 보장
"""

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4
from typing import Optional

from pydantic import BaseModel, Field


class ProcessingStatus(str, Enum):
    """처리 상태 공통 열거형"""
    
    PENDING = "PENDING"                # 대기 중
    IN_PROGRESS = "IN_PROGRESS"        # 처리 중
    COMPLETED = "COMPLETED"            # 완료
    FAILED = "FAILED"                  # 실패
    CANCELLED = "CANCELLED"            # 취소됨
    TIMEOUT = "TIMEOUT"                # 시간 초과


class Priority(str, Enum):
    """우선순위 공통 열거형"""
    
    LOW = "LOW"                        # 낮음
    NORMAL = "NORMAL"                  # 보통 (기본값)
    HIGH = "HIGH"                      # 높음
    CRITICAL = "CRITICAL"              # 긴급


class ConfidenceLevel(str, Enum):
    """신뢰도 수준 공통 열거형"""
    
    VERY_LOW = "VERY_LOW"              # 매우 낮음 (< 0.3)
    LOW = "LOW"                        # 낮음 (0.3-0.5)
    MEDIUM = "MEDIUM"                  # 보통 (0.5-0.7)
    HIGH = "HIGH"                      # 높음 (0.7-0.9)
    VERY_HIGH = "VERY_HIGH"            # 매우 높음 (> 0.9)


class BaseEntity(BaseModel):
    """
    공통 엔티티 기본 클래스
    
    모든 도메인 엔티티에서 공통으로 사용되는 필드들을 정의:
    - 고유 식별자 (UUID)
    - 생성/수정 시간 추적
    - 버전 관리 (선택적)
    """
    
    id: UUID = Field(default_factory=uuid4, description="고유 식별자")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="생성 시각"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="최종 수정 시각"
    )
    version: int = Field(default=1, description="엔티티 버전")

    class Config:
        """Pydantic 설정"""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v),
        }


class ProcessingMetadata(BaseModel):
    """
    처리 과정 메타데이터 공통 모델
    
    모든 비동기 처리 작업에서 사용되는 공통 메타데이터:
    - 처리 상태와 진행률
    - 성능 지표
    - 오류 정보
    """
    
    status: ProcessingStatus = Field(default=ProcessingStatus.PENDING, description="처리 상태")
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="처리 진행률 (0.0-1.0)")
    started_at: Optional[datetime] = Field(default=None, description="처리 시작 시각")
    completed_at: Optional[datetime] = Field(default=None, description="처리 완료 시각")
    
    # 성능 지표
    processing_time_seconds: Optional[float] = Field(default=None, description="처리 소요 시간 (초)")
    queue_time_seconds: Optional[float] = Field(default=None, description="대기 시간 (초)")
    
    # 오류 정보
    error_count: int = Field(default=0, description="발생한 오류 수")
    last_error: Optional[str] = Field(default=None, description="마지막 오류 메시지")
    
    # 추가 정보
    priority: Priority = Field(default=Priority.NORMAL, description="처리 우선순위")
    retry_count: int = Field(default=0, description="재시도 횟수")
    max_retries: int = Field(default=3, description="최대 재시도 횟수")


class ResponseMetadata(BaseModel):
    """
    API 응답 메타데이터 공통 모델
    
    모든 API 응답에 포함되는 공통 메타데이터:
    - 요청 처리 정보
    - 성능 지표
    - 추적 정보
    """
    
    request_id: UUID = Field(default_factory=uuid4, description="요청 고유 식별자")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="응답 생성 시각"
    )
    processing_time_ms: Optional[float] = Field(default=None, description="처리 시간 (밀리초)")
    
    # 서비스 정보
    service_version: str = Field(default="1.0.0", description="서비스 버전")
    model_version: str = Field(default="gemini-2.5-pro", description="AI 모델 버전")
    
    # 캐시 정보
    cache_hit: bool = Field(default=False, description="캐시 히트 여부")
    cache_key: Optional[str] = Field(default=None, description="캐시 키")


class PaginationMetadata(BaseModel):
    """
    페이지네이션 메타데이터 공통 모델
    
    목록 조회 API에서 사용되는 페이지네이션 정보
    """
    
    page: int = Field(default=1, ge=1, description="현재 페이지 번호")
    page_size: int = Field(default=20, ge=1, le=100, description="페이지 크기")
    total_items: int = Field(default=0, ge=0, description="전체 항목 수")
    total_pages: int = Field(default=0, ge=0, description="전체 페이지 수")
    has_next: bool = Field(default=False, description="다음 페이지 존재 여부")
    has_previous: bool = Field(default=False, description="이전 페이지 존재 여부")


class HealthStatus(str, Enum):
    """시스템 상태 공통 열거형"""
    
    HEALTHY = "HEALTHY"                # 정상
    DEGRADED = "DEGRADED"              # 성능 저하
    UNHEALTHY = "UNHEALTHY"            # 비정상
    UNKNOWN = "UNKNOWN"                # 알 수 없음


class ServiceInfo(BaseModel):
    """
    서비스 정보 공통 모델
    
    마이크로서비스 아키텍처에서 서비스 식별 및 상태 정보
    """
    
    name: str = Field(..., description="서비스 이름")
    version: str = Field(..., description="서비스 버전")
    status: HealthStatus = Field(default=HealthStatus.UNKNOWN, description="서비스 상태")
    uptime_seconds: Optional[float] = Field(default=None, description="서비스 가동 시간 (초)")
    last_health_check: Optional[datetime] = Field(default=None, description="마지막 헬스 체크 시각")