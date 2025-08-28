"""
캐싱 서비스

글자인식 결과 및 이미지 처리 결과 캐싱으로 성능 최적화

주요 기능:
- 이미지 해시 기반 중복 처리 방지
- 메모리 + Redis 다층 캐싱
- TTL 기반 캐시 만료 관리
- 캐시 히트율 모니터링
"""

import hashlib
import time
import pickle
import asyncio
from typing import Any, TYPE_CHECKING
from dataclasses import dataclass
import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisType
else:
    RedisType = Any

logger = structlog.get_logger("cache")

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    aioredis = None  # type: ignore
    REDIS_AVAILABLE = False
    logger.warning("Redis 라이브러리가 설치되지 않음. 메모리 캐시만 사용됩니다.")


@dataclass
class CacheStats:
    """캐시 통계"""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    memory_usage_mb: float = 0.0
    
    @property
    def hit_rate(self) -> float:
        """캐시 히트율 계산"""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class ImageHasher:
    """
    이미지 해시 생성기
    
    동일 이미지 감지를 위한 해시 알고리즘 구현
    """
    
    @staticmethod
    def compute_hash(image_data: bytes) -> str:
        """
        이미지 데이터의 SHA-256 해시 생성
        
        Args:
            image_data: 이미지 바이너리 데이터
            
        Returns:
            str: 16진수 해시 문자열
        """
        hasher = hashlib.sha256()
        hasher.update(image_data)
        return hasher.hexdigest()
    
    @staticmethod
    def compute_content_hash(image_data: bytes) -> str:
        """
        이미지 내용 기반 해시 (메타데이터 무시)
        
        Args:
            image_data: 이미지 바이너리 데이터
            
        Returns:
            str: 내용 기반 해시
        """
        try:
            from PIL import Image
            import io
            
            # 이미지를 표준 형식으로 정규화
            with Image.open(io.BytesIO(image_data)) as img:
                # RGB로 변환하고 리사이즈
                normalized = img.convert('RGB').resize((256, 256))
                
                # 정규화된 이미지 데이터로 해시 계산
                buffer = io.BytesIO()
                normalized.save(buffer, format='PNG')
                normalized_data = buffer.getvalue()
                
                hasher = hashlib.md5()  # 빠른 해시 사용
                hasher.update(normalized_data)
                return f"content_{hasher.hexdigest()}"
                
        except Exception as e:
            logger.warning("내용 기반 해시 계산 실패, 파일 해시 사용", error=str(e))
            return f"file_{ImageHasher.compute_hash(image_data)[:16]}"


class MemoryCache:
    """
    메모리 기반 LRU 캐시
    
    특징:
    - 메모리 사용량 제한
    - TTL 기반 만료
    - LRU 제거 정책
    """
    
    def __init__(self, max_size_mb: int = 100, default_ttl: int = 3600):
        """
        메모리 캐시 초기화
        
        Args:
            max_size_mb: 최대 메모리 사용량 (MB)
            default_ttl: 기본 TTL (초)
        """
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.default_ttl = default_ttl
        
        self._cache: dict[str, tuple[Any, float, int]] = {}  # key -> (value, expire_time, size)
        self._access_order: dict[str, float] = {}  # key -> last_access_time
        self._current_size = 0
        self._stats = CacheStats()
        
        logger.info(
            "메모리 캐시 초기화", 
            max_size_mb=max_size_mb, 
            default_ttl=default_ttl
        )
    
    async def get(self, key: str) -> Any | None:
        """캐시에서 값 조회"""
        current_time = time.time()
        
        if key not in self._cache:
            self._stats.misses += 1
            return None
        
        value, expire_time, size = self._cache[key]
        
        # TTL 만료 체크
        if expire_time < current_time:
            await self.delete(key)
            self._stats.misses += 1
            return None
        
        # 액세스 시간 업데이트 (LRU)
        self._access_order[key] = current_time
        self._stats.hits += 1
        
        logger.debug("메모리 캐시 히트", key=key[:32], size_bytes=size)
        return value
    
    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """캐시에 값 저장"""
        try:
            # 값 직렬화 및 크기 계산
            serialized = pickle.dumps(value)
            value_size = len(serialized)
            
            ttl = ttl or self.default_ttl
            expire_time = time.time() + ttl
            
            # 공간 확보
            await self._make_space(value_size)
            
            # 기존 값이 있다면 크기 조정
            if key in self._cache:
                _, _, old_size = self._cache[key]
                self._current_size -= old_size
            
            # 새 값 저장
            self._cache[key] = (value, expire_time, value_size)
            self._access_order[key] = time.time()
            self._current_size += value_size
            
            logger.debug(
                "메모리 캐시 저장",
                key=key[:32],
                size_bytes=value_size,
                ttl=ttl,
                total_size_mb=round(self._current_size / 1024 / 1024, 2)
            )
            
            return True
            
        except Exception as e:
            logger.error("메모리 캐시 저장 실패", key=key[:32], error=str(e))
            return False
    
    async def delete(self, key: str) -> bool:
        """캐시에서 값 삭제"""
        if key in self._cache:
            _, _, size = self._cache[key]
            del self._cache[key]
            del self._access_order[key]
            self._current_size -= size
            
            logger.debug("메모리 캐시 삭제", key=key[:32], size_bytes=size)
            return True
        
        return False
    
    async def _make_space(self, required_size: int):
        """공간 확보 (LRU 제거)"""
        while self._current_size + required_size > self.max_size_bytes:
            if not self._access_order:
                break
            
            # 가장 오래된 항목 찾기
            oldest_key = min(self._access_order, key=lambda k: self._access_order.get(k, 0.0))
            await self.delete(oldest_key)
            self._stats.evictions += 1
    
    async def cleanup_expired(self):
        """만료된 항목 정리"""
        current_time = time.time()
        expired_keys = []
        
        for key, (_, expire_time, _) in self._cache.items():
            if expire_time < current_time:
                expired_keys.append(key)
        
        for key in expired_keys:
            await self.delete(key)
        
        if expired_keys:
            logger.info("만료된 캐시 항목 정리", count=len(expired_keys))
    
    def get_stats(self) -> CacheStats:
        """캐시 통계 반환"""
        self._stats.memory_usage_mb = self._current_size / 1024 / 1024
        return self._stats


class RedisCache:
    """
    Redis 기반 분산 캐시
    
    특징:
    - 다중 인스턴스 간 캐시 공유
    - 지속성 지원
    - 클러스터 확장 가능
    """
    
    def __init__(
        self, 
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "ocr_cache:",
        default_ttl: int = 3600
    ):
        """
        Redis 캐시 초기화
        
        Args:
            redis_url: Redis 연결 URL
            key_prefix: 키 접두사
            default_ttl: 기본 TTL (초)
        """
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.default_ttl = default_ttl
        self._redis: RedisType | None = None
        self._stats = CacheStats()
        
        logger.info("Redis 캐시 초기화", redis_url=redis_url, key_prefix=key_prefix)
    
    async def _get_redis(self) -> RedisType:
        """Redis 연결 획득 (지연 초기화)"""
        if not REDIS_AVAILABLE or aioredis is None:
            raise RuntimeError("Redis 라이브러리가 설치되지 않음")
        
        if self._redis is None:
            self._redis = aioredis.from_url(
                self.redis_url,
                decode_responses=False,  # 바이너리 데이터 지원
                socket_connect_timeout=5,
                socket_timeout=5
            )
            
            # 연결 테스트
            await self._redis.ping()
            logger.info("Redis 연결 성공")
        
        assert self._redis is not None  # Type narrowing for mypy
        return self._redis
    
    def _make_key(self, key: str) -> str:
        """접두사가 포함된 키 생성"""
        return f"{self.key_prefix}{key}"
    
    async def get(self, key: str) -> Any | None:
        """Redis에서 값 조회"""
        try:
            redis = await self._get_redis()
            full_key = self._make_key(key)
            
            serialized = await redis.get(full_key)
            if serialized is None:
                self._stats.misses += 1
                return None
            
            value = pickle.loads(serialized)
            self._stats.hits += 1
            
            logger.debug("Redis 캐시 히트", key=key[:32])
            return value
            
        except Exception as e:
            logger.error("Redis 캐시 조회 실패", key=key[:32], error=str(e))
            self._stats.misses += 1
            return None
    
    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Redis에 값 저장"""
        try:
            redis = await self._get_redis()
            full_key = self._make_key(key)
            ttl = ttl or self.default_ttl
            
            serialized = pickle.dumps(value)
            await redis.setex(full_key, ttl, serialized)
            
            logger.debug(
                "Redis 캐시 저장",
                key=key[:32],
                size_bytes=len(serialized),
                ttl=ttl
            )
            
            return True
            
        except Exception as e:
            logger.error("Redis 캐시 저장 실패", key=key[:32], error=str(e))
            return False
    
    async def delete(self, key: str) -> bool:
        """Redis에서 값 삭제"""
        try:
            redis = await self._get_redis()
            full_key = self._make_key(key)
            
            result = await redis.delete(full_key)
            logger.debug("Redis 캐시 삭제", key=key[:32], existed=bool(result))
            
            return bool(result)
            
        except Exception as e:
            logger.error("Redis 캐시 삭제 실패", key=key[:32], error=str(e))
            return False
    
    def get_stats(self) -> CacheStats:
        """Redis 캐시 통계 반환"""
        return self._stats
    
    async def close(self):
        """Redis 연결 종료"""
        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("Redis 연결 종료")


class CacheService:
    """
    다층 캐시 서비스 (메모리 + Redis)
    
    캐시 계층:
    1. L1: 메모리 캐시 (빠름, 작은 용량)
    2. L2: Redis 캐시 (중간 속도, 큰 용량, 분산)
    
    동작 방식:
    - 조회시: L1 -> L2 순서로 검색
    - 저장시: L1과 L2에 동시 저장
    - 히트시: 상위 레벨로 승격
    """
    
    def __init__(
        self,
        redis_enabled: bool = True,
        redis_url: str = "redis://localhost:6379",
        memory_cache_size_mb: int = 100,
        default_ttl: int = 3600
    ):
        """
        캐시 서비스 초기화
        
        Args:
            redis_enabled: Redis 캐시 사용 여부
            redis_url: Redis 연결 URL
            memory_cache_size_mb: 메모리 캐시 크기 (MB)
            default_ttl: 기본 TTL (초)
        """
        self.default_ttl = default_ttl
        
        # L1: 메모리 캐시
        self.memory_cache = MemoryCache(
            max_size_mb=memory_cache_size_mb,
            default_ttl=default_ttl
        )
        
        # L2: Redis 캐시
        self.redis_cache: RedisCache | None = None
        if redis_enabled and REDIS_AVAILABLE:
            try:
                self.redis_cache = RedisCache(
                    redis_url=redis_url,
                    default_ttl=default_ttl
                )
                logger.info("다층 캐시 서비스 초기화 (메모리 + Redis)")
            except Exception as e:
                logger.warning("Redis 캐시 초기화 실패, 메모리 캐시만 사용", error=str(e))
                self.redis_cache = None
        else:
            logger.info("다층 캐시 서비스 초기화 (메모리만)")
        
        # 정리 태스크는 이벤트 루프가 시작된 후 시작됨
        self._cleanup_task = None
    
    async def start_cleanup_task(self):
        """정리 태스크 시작 (이벤트 루프 실행 중에 호출)"""
        if self._cleanup_task is None:
            try:
                self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
                logger.info("캐시 정리 태스크 시작")
            except RuntimeError:
                logger.warning("이벤트 루프가 실행되지 않아 정리 태스크 시작 불가")
    
    async def stop_cleanup_task(self):
        """정리 태스크 중지"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("캐시 정리 태스크 중지")
    
    async def _ensure_cleanup_task(self):
        """정리 태스크가 시작되었는지 확인하고 필요시 시작"""
        if self._cleanup_task is None:
            await self.start_cleanup_task()
    
    async def get_text_recognition_result(self, image_hash: str) -> Any | None:
        """
        글자인식 결과 조회
        
        Args:
            image_hash: 이미지 해시
            
        Returns:
            Any | None: 캐시된 OCR 결과
        """
        await self._ensure_cleanup_task()
        cache_key = f"ocr_result:{image_hash}"
        
        # L1 캐시 확인
        result = await self.memory_cache.get(cache_key)
        if result is not None:
            logger.debug("L1 캐시 히트", image_hash=image_hash[:16])
            return result
        
        # L2 캐시 확인
        if self.redis_cache:
            result = await self.redis_cache.get(cache_key)
            if result is not None:
                # L1으로 승격
                await self.memory_cache.set(cache_key, result, ttl=self.default_ttl // 2)
                logger.debug("L2 캐시 히트, L1으로 승격", image_hash=image_hash[:16])
                return result
        
        logger.debug("캐시 미스", image_hash=image_hash[:16])
        return None
    
    async def set_text_recognition_result(
        self, 
        image_hash: str, 
        ocr_result: Any, 
        ttl: int | None = None
    ) -> bool:
        """
        OCR 결과 저장
        
        Args:
            image_hash: 이미지 해시
            text_recognition_result: 저장할 글자인식 결과
            ttl: TTL (초)
            
        Returns:
            bool: 저장 성공 여부
        """
        cache_key = f"ocr_result:{image_hash}"
        ttl = ttl or self.default_ttl
        
        # 동시 저장 (L1 + L2)
        tasks = [
            self.memory_cache.set(cache_key, ocr_result, ttl)
        ]
        
        if self.redis_cache:
            tasks.append(
                self.redis_cache.set(cache_key, ocr_result, ttl)
            )
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success = any(result is True for result in results if not isinstance(result, Exception))
        
        logger.info(
            "OCR 결과 캐시 저장",
            image_hash=image_hash[:16],
            ttl=ttl,
            success=success,
            l1_success=results[0] is True,
            l2_success=len(results) > 1 and results[1] is True
        )
        
        return success
    
    async def invalidate_text_recognition_result(self, image_hash: str) -> bool:
        """
        OCR 결과 캐시 무효화
        
        Args:
            image_hash: 이미지 해시
            
        Returns:
            bool: 무효화 성공 여부
        """
        cache_key = f"ocr_result:{image_hash}"
        
        tasks = [
            self.memory_cache.delete(cache_key)
        ]
        
        if self.redis_cache:
            tasks.append(
                self.redis_cache.delete(cache_key)
            )
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success = any(result is True for result in results if not isinstance(result, Exception))
        
        logger.info("OCR 결과 캐시 무효화", image_hash=image_hash[:16], success=success)
        return success
    
    def compute_image_hash(self, image_data: bytes, use_content_hash: bool = False) -> str:
        """
        이미지 해시 계산
        
        Args:
            image_data: 이미지 바이너리 데이터
            use_content_hash: 내용 기반 해시 사용 여부
            
        Returns:
            str: 이미지 해시
        """
        if use_content_hash:
            return ImageHasher.compute_content_hash(image_data)
        else:
            return ImageHasher.compute_hash(image_data)
    
    def get_cache_stats(self) -> dict[str, Any]:
        """
        전체 캐시 통계 조회
        
        Returns:
            Dict: 캐시 통계 정보
        """
        memory_stats = self.memory_cache.get_stats()
        redis_stats = self.redis_cache.get_stats() if self.redis_cache else CacheStats()
        
        # 전체 통계 계산
        total_hits = memory_stats.hits + redis_stats.hits
        total_misses = memory_stats.misses + redis_stats.misses
        total_requests = total_hits + total_misses
        
        return {
            "total": {
                "requests": total_requests,
                "hits": total_hits,
                "misses": total_misses,
                "hit_rate": total_hits / total_requests if total_requests > 0 else 0.0
            },
            "l1_memory": {
                "hits": memory_stats.hits,
                "misses": memory_stats.misses,
                "hit_rate": memory_stats.hit_rate,
                "memory_usage_mb": memory_stats.memory_usage_mb,
                "evictions": memory_stats.evictions
            },
            "l2_redis": {
                "hits": redis_stats.hits,
                "misses": redis_stats.misses,
                "hit_rate": redis_stats.hit_rate,
                "enabled": self.redis_cache is not None
            } if self.redis_cache else {"enabled": False}
        }
    
    async def _periodic_cleanup(self):
        """주기적 캐시 정리 (백그라운드 태스크)"""
        while True:
            try:
                await asyncio.sleep(300)  # 5분마다 실행
                await self.memory_cache.cleanup_expired()
                logger.debug("캐시 정리 완료")
                
            except Exception as e:
                logger.error("캐시 정리 중 오류", error=str(e))
                await asyncio.sleep(60)  # 오류 시 1분 후 재시도
    
    async def close(self):
        """캐시 서비스 종료"""
        if self.redis_cache:
            await self.redis_cache.close()
        
        logger.info("캐시 서비스 종료")


# 전역 캐시 서비스 인스턴스
_cache_service: CacheService | None = None


def get_cache_service(**kwargs) -> CacheService:
    """캐시 서비스 싱글톤 인스턴스 반환"""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService(**kwargs)
    return _cache_service