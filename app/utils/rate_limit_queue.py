"""
Rate limiting queue 시스템 구현

주요 기능:
- Request queue 관리
- Exponential backoff retry
- Priority queue 지원
"""

import asyncio
import time
from typing import Any, Callable, Optional, TypeVar, Coroutine
from dataclasses import dataclass, field
from heapq import heappush, heappop
import logging
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass(order=True)
class QueuedRequest:
    """
    우선순위 큐에서 사용할 요청 래퍼
    
    속성:
    - priority: 낮을수록 높은 우선순위
    - timestamp: 요청 생성 시간
    - future: 결과를 받을 Future 객체
    - func: 실행할 함수
    - args: 함수 인자
    - kwargs: 함수 키워드 인자
    """
    priority: int
    timestamp: float = field(compare=False)
    future: asyncio.Future = field(compare=False)
    func: Callable = field(compare=False)
    args: tuple = field(compare=False, default_factory=tuple)
    kwargs: dict = field(compare=False, default_factory=dict)


class RateLimitQueue:
    """
    Rate limiting을 위한 요청 큐 시스템
    
    주요 기능:
    - 요청 큐잉 및 순차 처리
    - Exponential backoff retry
    - Circuit breaker 통합
    - 우선순위 큐 지원
    """
    
    def __init__(
        self,
        max_queue_size: int = 100,
        requests_per_minute: int = 15,
        initial_backoff: float = 2.0,
        max_backoff: float = 64.0,
        backoff_factor: float = 2.0,
        max_retries: int = 5
    ):
        """
        Rate limit queue 초기화
        
        Args:
            max_queue_size: 최대 큐 크기
            requests_per_minute: 분당 요청 수 제한
            initial_backoff: 초기 백오프 시간 (초)
            max_backoff: 최대 백오프 시간 (초)
            backoff_factor: 백오프 증가 계수
            max_retries: 최대 재시도 횟수
        """
        self.max_queue_size = max_queue_size
        self.requests_per_minute = requests_per_minute
        self.request_interval = 60.0 / requests_per_minute
        
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.backoff_factor = backoff_factor
        self.max_retries = max_retries
        
        # 우선순위 큐
        self._queue: list[QueuedRequest] = []
        self._queue_lock = asyncio.Lock()
        
        # 처리 상태
        self._last_request_time = 0.0
        self._processing = False
        self._processor_task: Optional[asyncio.Task] = None
        
        # 통계
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.retry_count = 0
    
    async def enqueue(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        *args,
        priority: int = 5,
        **kwargs
    ) -> T:
        """
        요청을 큐에 추가하고 결과 반환
        
        Args:
            func: 실행할 비동기 함수
            args: 함수 인자
            priority: 우선순위 (0이 가장 높음)
            kwargs: 함수 키워드 인자
            
        Returns:
            함수 실행 결과
            
        Raises:
            RuntimeError: 큐가 가득 찬 경우
        """
        async with self._queue_lock:
            if len(self._queue) >= self.max_queue_size:
                raise RuntimeError(f"Request queue full (max {self.max_queue_size})")
            
            future = asyncio.Future()
            request = QueuedRequest(
                priority=priority,
                timestamp=time.time(),
                future=future,
                func=func,
                args=args,
                kwargs=kwargs
            )
            
            heappush(self._queue, request)
            self.total_requests += 1
            
            logger.debug(
                f"요청 큐 추가: priority={priority}, queue_size={len(self._queue)}"
            )
        
        # 처리기 시작
        if not self._processing:
            await self._start_processor()
        
        # 결과 대기
        return await future
    
    async def _start_processor(self):
        """요청 처리기 시작"""
        if self._processing:
            return
        
        self._processing = True
        self._processor_task = asyncio.create_task(self._process_queue())
        logger.info("Rate limit queue processor 시작")
    
    async def _process_queue(self):
        """큐에서 요청을 처리"""
        while self._processing:
            async with self._queue_lock:
                if not self._queue:
                    self._processing = False
                    break
                
                request = heappop(self._queue)
            
            # Rate limiting 적용
            await self._apply_rate_limit()
            
            # 요청 실행 (retry 포함)
            try:
                result = await self._execute_with_retry(request)
                request.future.set_result(result)
                self.successful_requests += 1
            except Exception as e:
                request.future.set_exception(e)
                self.failed_requests += 1
                logger.error(f"요청 처리 실패: {e}")
        
        logger.info("Rate limit queue processor 종료")
    
    async def _apply_rate_limit(self):
        """Rate limiting 적용"""
        now = time.time()
        time_since_last = now - self._last_request_time
        
        if time_since_last < self.request_interval:
            wait_time = self.request_interval - time_since_last
            logger.debug(f"Rate limit 대기: {wait_time:.2f}초")
            await asyncio.sleep(wait_time)
        
        self._last_request_time = time.time()
    
    async def _execute_with_retry(self, request: QueuedRequest) -> Any:
        """
        Exponential backoff로 요청 실행
        
        Args:
            request: 실행할 요청
            
        Returns:
            함수 실행 결과
            
        Raises:
            마지막 발생한 예외
        """
        backoff = self.initial_backoff
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                # 함수 실행
                result = await request.func(*request.args, **request.kwargs)
                
                if attempt > 0:
                    logger.info(f"재시도 성공: attempt={attempt + 1}")
                
                return result
                
            except Exception as e:
                last_exception = e
                
                # 재시도 가능 여부 확인
                if attempt >= self.max_retries:
                    logger.error(
                        f"최대 재시도 횟수 초과: {self.max_retries + 1}회 시도"
                    )
                    break
                
                # 429 에러나 ResourceExhausted인 경우만 재시도
                error_msg = str(e).lower()
                if not any(x in error_msg for x in ['429', 'rate', 'quota', 'exceeded']):
                    logger.error(f"재시도 불가능한 에러: {e}")
                    break
                
                # Exponential backoff 대기
                wait_time = min(backoff, self.max_backoff)
                logger.warning(
                    f"재시도 대기: attempt={attempt + 1}/{self.max_retries}, "
                    f"wait={wait_time:.1f}초, error={e}"
                )
                
                await asyncio.sleep(wait_time)
                backoff *= self.backoff_factor
                self.retry_count += 1
        
        if last_exception:
            raise last_exception
        else:
            raise RuntimeError("최대 재시도 횟수 초과")
    
    async def shutdown(self):
        """큐 처리 종료"""
        self._processing = False
        
        if self._processor_task:
            await self._processor_task
        
        # 대기 중인 요청 취소
        async with self._queue_lock:
            while self._queue:
                request = heappop(self._queue)
                request.future.cancel()
        
        logger.info(
            f"Rate limit queue 종료: "
            f"total={self.total_requests}, "
            f"success={self.successful_requests}, "
            f"failed={self.failed_requests}, "
            f"retries={self.retry_count}"
        )
    
    def get_stats(self) -> dict:
        """큐 통계 반환"""
        return {
            "queue_size": len(self._queue),
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "retry_count": self.retry_count,
            "success_rate": (
                self.successful_requests / self.total_requests 
                if self.total_requests > 0 else 0
            )
        }


# 전역 큐 인스턴스
_rate_limit_queue: Optional[RateLimitQueue] = None


def get_rate_limit_queue() -> RateLimitQueue:
    """전역 rate limit queue 인스턴스 반환"""
    global _rate_limit_queue
    if _rate_limit_queue is None:
        _rate_limit_queue = RateLimitQueue()
    return _rate_limit_queue


def with_rate_limit(priority: int = 5):
    """
    Rate limiting decorator
    
    사용 예:
    ```python
    @with_rate_limit(priority=1)
    async def call_gemini_api(prompt: str):
        # API 호출 로직
        pass
    ```
    """
    def decorator(func: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            queue = get_rate_limit_queue()
            return await queue.enqueue(func, *args, priority=priority, **kwargs)
        return wrapper
    return decorator