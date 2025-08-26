"""
서킷 브레이커 패턴 구현

외부 API 장애 시 자동 복구 및 폴백 메커니즘 제공

주요 기능:
- 실패율 기반 서킷 오픈/클로즈
- 반자동 복구 (half-open 상태)
- 메트릭 수집 및 모니터링
- 폴백 전략 지원
"""

import asyncio
import time
from enum import Enum
from typing import Callable, Any, Optional, Dict
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger("circuit_breaker")


class CircuitState(Enum):
    """서킷 브레이커 상태"""
    CLOSED = "closed"      # 정상 상태 - 요청 허용
    OPEN = "open"          # 장애 상태 - 요청 차단
    HALF_OPEN = "half_open"  # 복구 테스트 상태 - 제한적 요청 허용


@dataclass
class CircuitBreakerMetrics:
    """서킷 브레이커 메트릭"""
    total_requests: int = 0
    failed_requests: int = 0
    successful_requests: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    state_changed_at: float = field(default_factory=time.time)
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    
    @property
    def failure_rate(self) -> float:
        """실패율 계산 (0.0-1.0)"""
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests
    
    @property
    def success_rate(self) -> float:
        """성공률 계산 (0.0-1.0)"""
        return 1.0 - self.failure_rate


class CircuitBreakerOpenError(Exception):
    """서킷 브레이커가 열린 상태에서 요청이 차단된 경우"""
    def __init__(self, last_failure_time: Optional[float] = None):
        self.last_failure_time = last_failure_time
        super().__init__("Circuit breaker is OPEN - requests are blocked")


class CircuitBreaker:
    """
    서킷 브레이커 구현체
    
    동작 원리:
    1. CLOSED: 정상 요청 허용, 실패 카운트 추적
    2. OPEN: 임계값 초과시 모든 요청 차단
    3. HALF_OPEN: 일정 시간 후 복구 테스트
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,        # 연속 실패 임계값
        failure_rate_threshold: float = 0.5,  # 실패율 임계값 (50%)
        recovery_timeout: int = 60,        # 복구 테스트 대기 시간 (초)
        half_open_max_calls: int = 3,      # HALF_OPEN 상태 최대 호출 수
        monitoring_window: int = 100,      # 모니터링 윈도우 크기
    ):
        """
        서킷 브레이커 초기화
        
        Args:
            name: 서킷 브레이커 이름
            failure_threshold: 연속 실패 임계값
            failure_rate_threshold: 실패율 임계값 (0.0-1.0)
            recovery_timeout: 복구 테스트 대기 시간 (초)
            half_open_max_calls: HALF_OPEN 상태에서 허용할 최대 호출 수
            monitoring_window: 메트릭 모니터링 윈도우 크기
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.failure_rate_threshold = failure_rate_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.monitoring_window = monitoring_window
        
        # 상태 관리
        self.state = CircuitState.CLOSED
        self.metrics = CircuitBreakerMetrics()
        
        # 동시성 제어
        self._lock = asyncio.Lock()
        
        logger.info(
            "서킷 브레이커 초기화",
            name=name,
            failure_threshold=failure_threshold,
            failure_rate_threshold=failure_rate_threshold,
            recovery_timeout=recovery_timeout
        )
    
    async def call(
        self, 
        func: Callable[[], Any], 
        fallback: Optional[Callable[[], Any]] = None
    ) -> Any:
        """
        서킷 브레이커를 통한 함수 호출
        
        Args:
            func: 실행할 함수
            fallback: 장애 시 대체 함수
            
        Returns:
            함수 실행 결과 또는 폴백 결과
            
        Raises:
            CircuitBreakerOpenError: 서킷이 열린 상태일 때
        """
        async with self._lock:
            # 상태 확인 및 전환
            await self._check_state_transition()
            
            # OPEN 상태에서 요청 차단
            if self.state == CircuitState.OPEN:
                logger.warning(
                    "서킷 브레이커 요청 차단",
                    name=self.name,
                    state=self.state.value,
                    last_failure=self.metrics.last_failure_time
                )
                
                if fallback:
                    logger.info("폴백 함수 실행", name=self.name)
                    return await self._execute_fallback(fallback)
                else:
                    raise CircuitBreakerOpenError(self.metrics.last_failure_time)
            
            # HALF_OPEN 상태에서 제한적 허용
            if (self.state == CircuitState.HALF_OPEN and 
                self.metrics.consecutive_successes >= self.half_open_max_calls):
                logger.warning(
                    "HALF_OPEN 상태 호출 제한 초과",
                    name=self.name,
                    consecutive_successes=self.metrics.consecutive_successes,
                    max_calls=self.half_open_max_calls
                )
                
                if fallback:
                    return await self._execute_fallback(fallback)
                else:
                    raise CircuitBreakerOpenError()
        
        # 함수 실행
        try:
            start_time = time.time()
            result = await self._execute_function(func)
            execution_time = time.time() - start_time
            
            # 성공 기록
            await self._record_success(execution_time)
            return result
            
        except Exception as e:
            # 실패 기록
            await self._record_failure(e)
            
            # 폴백 실행
            if fallback:
                logger.info(
                    "주 함수 실패, 폴백 실행",
                    name=self.name,
                    error=str(e)[:100]
                )
                return await self._execute_fallback(fallback)
            else:
                raise
    
    async def _execute_function(self, func: Callable[[], Any]) -> Any:
        """함수 실행 (동기/비동기 모두 지원)"""
        if asyncio.iscoroutinefunction(func):
            return await func()
        else:
            return func()
    
    async def _execute_fallback(self, fallback: Callable[[], Any]) -> Any:
        """폴백 함수 실행"""
        try:
            if asyncio.iscoroutinefunction(fallback):
                return await fallback()
            else:
                return fallback()
        except Exception as e:
            logger.error(
                "폴백 함수 실행 실패",
                name=self.name,
                error=str(e)
            )
            raise
    
    async def _record_success(self, execution_time: float):
        """성공 기록"""
        async with self._lock:
            self.metrics.total_requests += 1
            self.metrics.successful_requests += 1
            self.metrics.last_success_time = time.time()
            self.metrics.consecutive_successes += 1
            self.metrics.consecutive_failures = 0
            
            # HALF_OPEN -> CLOSED 전환
            if (self.state == CircuitState.HALF_OPEN and
                self.metrics.consecutive_successes >= self.half_open_max_calls):
                await self._transition_to_closed()
            
            # 메트릭 윈도우 관리
            self._manage_metrics_window()
            
            logger.debug(
                "서킷 브레이커 성공 기록",
                name=self.name,
                execution_time_ms=round(execution_time * 1000, 2),
                state=self.state.value,
                consecutive_successes=self.metrics.consecutive_successes
            )
    
    async def _record_failure(self, error: Exception):
        """실패 기록"""
        async with self._lock:
            self.metrics.total_requests += 1
            self.metrics.failed_requests += 1
            self.metrics.last_failure_time = time.time()
            self.metrics.consecutive_failures += 1
            self.metrics.consecutive_successes = 0
            
            # CLOSED/HALF_OPEN -> OPEN 전환 체크
            should_open = (
                self.metrics.consecutive_failures >= self.failure_threshold or
                (self.metrics.total_requests >= self.monitoring_window and
                 self.metrics.failure_rate >= self.failure_rate_threshold)
            )
            
            if should_open and self.state != CircuitState.OPEN:
                await self._transition_to_open()
            
            # 메트릭 윈도우 관리
            self._manage_metrics_window()
            
            logger.warning(
                "서킷 브레이커 실패 기록",
                name=self.name,
                error=str(error)[:100],
                state=self.state.value,
                consecutive_failures=self.metrics.consecutive_failures,
                failure_rate=round(self.metrics.failure_rate, 3)
            )
    
    async def _check_state_transition(self):
        """상태 전환 확인"""
        current_time = time.time()
        
        # OPEN -> HALF_OPEN 전환 (복구 테스트)
        if (self.state == CircuitState.OPEN and
            self.metrics.last_failure_time and
            current_time - self.metrics.last_failure_time >= self.recovery_timeout):
            await self._transition_to_half_open()
    
    async def _transition_to_closed(self):
        """CLOSED 상태로 전환"""
        self.state = CircuitState.CLOSED
        self.metrics.state_changed_at = time.time()
        
        logger.info(
            "서킷 브레이커 CLOSED 상태 전환",
            name=self.name,
            consecutive_successes=self.metrics.consecutive_successes
        )
    
    async def _transition_to_open(self):
        """OPEN 상태로 전환"""
        self.state = CircuitState.OPEN
        self.metrics.state_changed_at = time.time()
        
        logger.error(
            "서킷 브레이커 OPEN 상태 전환",
            name=self.name,
            consecutive_failures=self.metrics.consecutive_failures,
            failure_rate=round(self.metrics.failure_rate, 3)
        )
    
    async def _transition_to_half_open(self):
        """HALF_OPEN 상태로 전환"""
        self.state = CircuitState.HALF_OPEN
        self.metrics.state_changed_at = time.time()
        self.metrics.consecutive_successes = 0
        
        logger.info(
            "서킷 브레이커 HALF_OPEN 상태 전환 (복구 테스트)",
            name=self.name,
            recovery_timeout=self.recovery_timeout
        )
    
    def _manage_metrics_window(self):
        """메트릭 윈도우 관리 (슬라이딩 윈도우)"""
        if self.metrics.total_requests > self.monitoring_window * 2:
            # 메트릭 리셋 (간단한 구현)
            self.metrics.total_requests = self.monitoring_window
            self.metrics.failed_requests = int(
                self.metrics.failed_requests * 0.7  # 70% 유지
            )
            self.metrics.successful_requests = (
                self.metrics.total_requests - self.metrics.failed_requests
            )
    
    def get_metrics(self) -> Dict[str, Any]:
        """현재 메트릭 조회"""
        return {
            "name": self.name,
            "state": self.state.value,
            "total_requests": self.metrics.total_requests,
            "success_rate": round(self.metrics.success_rate, 3),
            "failure_rate": round(self.metrics.failure_rate, 3),
            "consecutive_failures": self.metrics.consecutive_failures,
            "consecutive_successes": self.metrics.consecutive_successes,
            "last_failure_time": self.metrics.last_failure_time,
            "last_success_time": self.metrics.last_success_time,
            "state_changed_at": self.metrics.state_changed_at,
            "time_since_last_failure": (
                time.time() - self.metrics.last_failure_time
                if self.metrics.last_failure_time else None
            ),
        }
    
    async def reset(self):
        """서킷 브레이커 리셋 (수동 복구)"""
        async with self._lock:
            self.state = CircuitState.CLOSED
            self.metrics = CircuitBreakerMetrics()
            
            logger.info("서킷 브레이커 수동 리셋", name=self.name)


# 전역 서킷 브레이커 인스턴스들
_circuit_breakers: Dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    **kwargs
) -> CircuitBreaker:
    """
    서킷 브레이커 인스턴스 반환 (싱글톤 패턴)
    
    Args:
        name: 서킷 브레이커 이름
        **kwargs: 서킷 브레이커 설정
        
    Returns:
        CircuitBreaker: 서킷 브레이커 인스턴스
    """
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name=name, **kwargs)
    return _circuit_breakers[name]


def get_all_circuit_breakers() -> Dict[str, CircuitBreaker]:
    """모든 서킷 브레이커 인스턴스 반환"""
    return _circuit_breakers.copy()