"""
모니터링 및 메트릭 수집 서비스

프로덕션 환경에서 시스템 상태와 성능 모니터링

주요 기능:
- 글자인식 처리 메트릭 수집
- 성능 통계 및 분석
- 알림 시스템 연동
- 대시보드용 데이터 제공
"""

import time
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field
from collections import defaultdict, deque
import structlog
from enum import Enum

logger = structlog.get_logger("monitoring")


class AlertLevel(Enum):
    """알림 레벨"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class TextRecognitionMetric:
    """글자인식 처리 메트릭"""
    timestamp: float = field(default_factory=time.time)
    processing_time_ms: int = 0
    image_size_kb: int = 0
    image_quality: str = "unknown"
    confidence_avg: float = 0.0
    questions_detected: int = 0
    success: bool = True
    error_code: Optional[str] = None
    gemini_model: str = "gemini-2.0-flash-exp"


@dataclass
class SystemMetric:
    """시스템 메트릭"""
    timestamp: float = field(default_factory=time.time)
    cpu_usage_percent: float = 0.0
    memory_usage_mb: float = 0.0
    active_requests: int = 0
    queue_size: int = 0
    circuit_breaker_state: str = "closed"


@dataclass
class PerformanceStats:
    """성능 통계"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    avg_processing_time_ms: float = 0.0
    p50_processing_time_ms: float = 0.0
    p95_processing_time_ms: float = 0.0
    p99_processing_time_ms: float = 0.0
    min_processing_time_ms: int = 0
    max_processing_time_ms: int = 0
    success_rate: float = 0.0
    avg_confidence: float = 0.0
    
    # 시간 범위
    start_time: float = 0.0
    end_time: float = 0.0
    
    @property
    def requests_per_minute(self) -> float:
        """분당 요청 수 계산"""
        duration_minutes = (self.end_time - self.start_time) / 60
        if duration_minutes > 0:
            return self.total_requests / duration_minutes
        return 0.0


class MetricsCollector:
    """
    메트릭 수집 및 분석 서비스
    
    특징:
    - 실시간 메트릭 수집
    - 시계열 데이터 저장
    - 통계 계산 및 분석
    - 알림 임계값 모니터링
    """
    
    def __init__(
        self,
        window_size: int = 1000,         # 메트릭 윈도우 크기
        alert_thresholds: Optional[Dict[str, float]] = None
    ):
        """
        메트릭 컬렉터 초기화
        
        Args:
            window_size: 메트릭 윈도우 크기 (최근 N개 유지)
            alert_thresholds: 알림 임계값 설정
        """
        self.window_size = window_size
        self.alert_thresholds = alert_thresholds or {
            "success_rate": 0.95,      # 성공률 95% 미만시 알림
            "avg_processing_time": 5000,  # 평균 처리시간 5초 초과시 알림
            "error_rate": 0.05,        # 오류율 5% 초과시 알림
        }
        
        # 메트릭 저장소 (메모리 기반, 프로덕션에서는 Redis/InfluxDB 권장)
        self.text_recognition_metrics: deque = deque(maxlen=window_size)
        self.system_metrics: deque = deque(maxlen=window_size // 10)  # 시스템 메트릭은 적게 저장
        
        # 집계 데이터 캐시
        self._stats_cache: Optional[PerformanceStats] = None
        self._cache_timestamp: float = 0
        self._cache_ttl: int = 60  # 캐시 TTL (초)
        
        # 알림 관련
        self._last_alerts: Dict[str, float] = {}
        self._alert_cooldown: int = 300  # 알림 쿨다운 (초)
        
        logger.info(
            "메트릭 컬렉터 초기화",
            window_size=window_size,
            alert_thresholds=alert_thresholds
        )
    
    def record_text_recognition_metric(self, metric: TextRecognitionMetric):
        """
        OCR 메트릭 기록
        
        Args:
            metric: 기록할 OCR 메트릭
        """
        self.text_recognition_metrics.append(metric)
        
        # 캐시 무효화
        self._stats_cache = None
        
        # 실시간 알림 체크
        asyncio.create_task(self._check_alerts())
        
        logger.debug(
            "OCR 메트릭 기록",
            processing_time=metric.processing_time_ms,
            success=metric.success,
            confidence=metric.confidence_avg,
            quality=metric.image_quality
        )
    
    def record_system_metric(self, metric: SystemMetric):
        """
        시스템 메트릭 기록
        
        Args:
            metric: 기록할 시스템 메트릭
        """
        self.system_metrics.append(metric)
        
        logger.debug(
            "시스템 메트릭 기록",
            cpu_usage=metric.cpu_usage_percent,
            memory_usage_mb=metric.memory_usage_mb,
            active_requests=metric.active_requests
        )
    
    def get_performance_stats(
        self,
        time_range_minutes: Optional[int] = None
    ) -> PerformanceStats:
        """
        성능 통계 조회 (캐싱 지원)
        
        Args:
            time_range_minutes: 분석할 시간 범위 (분 단위)
            
        Returns:
            PerformanceStats: 성능 통계 정보
        """
        current_time = time.time()
        
        # 캐시 확인
        if (self._stats_cache and 
            current_time - self._cache_timestamp < self._cache_ttl):
            return self._stats_cache
        
        # 시간 범위 필터링
        metrics = list(self.text_recognition_metrics)
        if time_range_minutes:
            cutoff_time = current_time - (time_range_minutes * 60)
            metrics = [m for m in metrics if m.timestamp >= cutoff_time]
        
        if not metrics:
            return PerformanceStats()
        
        # 통계 계산
        processing_times = [m.processing_time_ms for m in metrics]
        successful_metrics = [m for m in metrics if m.success]
        
        stats = PerformanceStats(
            total_requests=len(metrics),
            successful_requests=len(successful_metrics),
            failed_requests=len(metrics) - len(successful_metrics),
            avg_processing_time_ms=sum(processing_times) / len(processing_times),
            min_processing_time_ms=min(processing_times),
            max_processing_time_ms=max(processing_times),
            start_time=metrics[0].timestamp,
            end_time=metrics[-1].timestamp,
            success_rate=len(successful_metrics) / len(metrics),
            avg_confidence=sum(m.confidence_avg for m in successful_metrics) / len(successful_metrics) if successful_metrics else 0.0
        )
        
        # 백분위수 계산
        sorted_times = sorted(processing_times)
        stats.p50_processing_time_ms = self._percentile(sorted_times, 0.5)
        stats.p95_processing_time_ms = self._percentile(sorted_times, 0.95)
        stats.p99_processing_time_ms = self._percentile(sorted_times, 0.99)
        
        # 캐시 업데이트
        self._stats_cache = stats
        self._cache_timestamp = current_time
        
        logger.debug(
            "성능 통계 계산 완료",
            time_range_minutes=time_range_minutes,
            total_requests=stats.total_requests,
            success_rate=round(stats.success_rate, 3),
            avg_processing_time=round(stats.avg_processing_time_ms, 2)
        )
        
        return stats
    
    def _percentile(self, sorted_data: List[float], percentile: float) -> float:
        """백분위수 계산"""
        if not sorted_data:
            return 0.0
        
        k = (len(sorted_data) - 1) * percentile
        f = int(k)
        c = k - f
        
        if f == len(sorted_data) - 1:
            return sorted_data[f]
        
        return sorted_data[f] * (1 - c) + sorted_data[f + 1] * c
    
    def get_error_analysis(self, time_range_minutes: int = 60) -> Dict[str, Any]:
        """
        오류 분석 정보 제공
        
        Args:
            time_range_minutes: 분석할 시간 범위
            
        Returns:
            Dict: 오류 분석 정보
        """
        current_time = time.time()
        cutoff_time = current_time - (time_range_minutes * 60)
        
        failed_metrics = [
            m for m in self.text_recognition_metrics 
            if not m.success and m.timestamp >= cutoff_time
        ]
        
        if not failed_metrics:
            return {
                "total_errors": 0,
                "error_codes": {},
                "error_rate": 0.0,
                "most_common_error": None
            }
        
        # 오류 코드별 집계
        error_codes = defaultdict(int)
        for metric in failed_metrics:
            if metric.error_code:
                error_codes[metric.error_code] += 1
        
        # 전체 메트릭 중 오류 비율
        total_metrics = len([
            m for m in self.text_recognition_metrics 
            if m.timestamp >= cutoff_time
        ])
        
        error_rate = len(failed_metrics) / total_metrics if total_metrics > 0 else 0.0
        
        # 가장 흔한 오류
        most_common_error = max(error_codes.items(), key=lambda x: x[1])[0] if error_codes else None
        
        return {
            "total_errors": len(failed_metrics),
            "error_codes": dict(error_codes),
            "error_rate": round(error_rate, 4),
            "most_common_error": most_common_error,
            "time_range_minutes": time_range_minutes
        }
    
    def get_quality_metrics(self, time_range_minutes: int = 60) -> Dict[str, Any]:
        """
        이미지 품질 및 OCR 품질 메트릭
        
        Args:
            time_range_minutes: 분석할 시간 범위
            
        Returns:
            Dict: 품질 메트릭 정보
        """
        current_time = time.time()
        cutoff_time = current_time - (time_range_minutes * 60)
        
        recent_metrics = [
            m for m in self.text_recognition_metrics 
            if m.timestamp >= cutoff_time and m.success
        ]
        
        if not recent_metrics:
            return {}
        
        # 이미지 품질별 분포
        quality_distribution = defaultdict(int)
        quality_confidence = defaultdict(list)
        
        for metric in recent_metrics:
            quality_distribution[metric.image_quality] += 1
            quality_confidence[metric.image_quality].append(metric.confidence_avg)
        
        # 품질별 평균 신뢰도
        quality_avg_confidence = {
            quality: sum(confidences) / len(confidences)
            for quality, confidences in quality_confidence.items()
        }
        
        # 전반적 품질 통계
        avg_confidence = sum(m.confidence_avg for m in recent_metrics) / len(recent_metrics)
        avg_questions_detected = sum(m.questions_detected for m in recent_metrics) / len(recent_metrics)
        
        return {
            "quality_distribution": dict(quality_distribution),
            "quality_avg_confidence": quality_avg_confidence,
            "overall_avg_confidence": round(avg_confidence, 3),
            "avg_questions_detected": round(avg_questions_detected, 2),
            "time_range_minutes": time_range_minutes
        }
    
    async def _check_alerts(self):
        """알림 조건 체크"""
        try:
            stats = self.get_performance_stats(time_range_minutes=10)  # 최근 10분 데이터로 알림 체크
            
            # 성공률 체크
            if (stats.total_requests >= 10 and  # 최소 요청 수
                stats.success_rate < self.alert_thresholds["success_rate"]):
                await self._send_alert(
                    "low_success_rate",
                    AlertLevel.WARNING,
                    f"성공률이 {stats.success_rate:.1%}로 임계값 {self.alert_thresholds['success_rate']:.1%} 미만입니다.",
                    {"success_rate": stats.success_rate, "total_requests": stats.total_requests}
                )
            
            # 평균 처리 시간 체크
            if stats.avg_processing_time_ms > self.alert_thresholds["avg_processing_time"]:
                await self._send_alert(
                    "high_processing_time",
                    AlertLevel.WARNING,
                    f"평균 처리시간이 {stats.avg_processing_time_ms:.0f}ms로 임계값 {self.alert_thresholds['avg_processing_time']:.0f}ms를 초과했습니다.",
                    {"avg_processing_time_ms": stats.avg_processing_time_ms}
                )
            
            # 오류율 체크
            error_rate = 1.0 - stats.success_rate
            if error_rate > self.alert_thresholds["error_rate"]:
                await self._send_alert(
                    "high_error_rate",
                    AlertLevel.ERROR,
                    f"오류율이 {error_rate:.1%}로 임계값 {self.alert_thresholds['error_rate']:.1%}를 초과했습니다.",
                    {"error_rate": error_rate, "failed_requests": stats.failed_requests}
                )
        
        except Exception as e:
            logger.error("알림 체크 중 오류 발생", error=str(e))
    
    async def _send_alert(
        self, 
        alert_type: str, 
        level: AlertLevel, 
        message: str, 
        context: Dict[str, Any]
    ):
        """
        알림 전송 (쿨다운 적용)
        
        Args:
            alert_type: 알림 타입
            level: 알림 레벨
            message: 알림 메시지
            context: 추가 컨텍스트 정보
        """
        current_time = time.time()
        
        # 쿨다운 체크
        if (alert_type in self._last_alerts and
            current_time - self._last_alerts[alert_type] < self._alert_cooldown):
            return
        
        # 알림 전송 (실제 구현에서는 Slack, Email, SMS 등으로 전송)
        logger.warning(
            "시스템 알림 발생",
            alert_type=alert_type,
            level=level.value,
            message=message,
            context=context
        )
        
        # 쿨다운 업데이트
        self._last_alerts[alert_type] = current_time
        
        # TODO: 실제 알림 시스템 연동
        # await self._send_to_slack(message, level)
        # await self._send_to_email(message, level, context)
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """
        대시보드용 종합 데이터 제공
        
        Returns:
            Dict: 대시보드 표시용 데이터
        """
        current_stats = self.get_performance_stats(time_range_minutes=60)
        error_analysis = self.get_error_analysis(time_range_minutes=60)
        quality_metrics = self.get_quality_metrics(time_range_minutes=60)
        
        # 시스템 메트릭 (최신)
        latest_system_metric = list(self.system_metrics)[-1] if self.system_metrics else None
        
        return {
            "timestamp": datetime.now().isoformat(),
            "performance": {
                "requests_per_minute": round(current_stats.requests_per_minute, 2),
                "success_rate": round(current_stats.success_rate, 3),
                "avg_processing_time_ms": round(current_stats.avg_processing_time_ms, 2),
                "p95_processing_time_ms": round(current_stats.p95_processing_time_ms, 2),
                "total_requests_hour": current_stats.total_requests
            },
            "errors": error_analysis,
            "quality": quality_metrics,
            "system": {
                "cpu_usage_percent": latest_system_metric.cpu_usage_percent if latest_system_metric else 0,
                "memory_usage_mb": latest_system_metric.memory_usage_mb if latest_system_metric else 0,
                "active_requests": latest_system_metric.active_requests if latest_system_metric else 0,
                "queue_size": latest_system_metric.queue_size if latest_system_metric else 0
            } if latest_system_metric else {},
            "health_status": self._determine_health_status(current_stats, error_analysis)
        }
    
    def _determine_health_status(
        self, 
        stats: PerformanceStats, 
        error_analysis: Dict[str, Any]
    ) -> str:
        """
        시스템 건강 상태 결정
        
        Args:
            stats: 성능 통계
            error_analysis: 오류 분석 결과
            
        Returns:
            str: 건강 상태 ("healthy", "warning", "critical")
        """
        if stats.total_requests < 5:  # 충분한 데이터 없음
            return "healthy"
        
        # Critical 조건
        if (stats.success_rate < 0.8 or 
            error_analysis["error_rate"] > 0.2 or
            stats.avg_processing_time_ms > 10000):
            return "critical"
        
        # Warning 조건
        if (stats.success_rate < 0.95 or
            error_analysis["error_rate"] > 0.05 or
            stats.avg_processing_time_ms > 5000):
            return "warning"
        
        return "healthy"


# 전역 메트릭 컬렉터 인스턴스
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector(**kwargs) -> MetricsCollector:
    """메트릭 컬렉터 싱글톤 인스턴스 반환"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector(**kwargs)
    return _metrics_collector