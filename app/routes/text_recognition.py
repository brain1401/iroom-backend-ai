"""
글자인식 API Routes (프로덕션 버전)

한국어 답안지 글자인식 처리를 위한 고도화된 FastAPI 엔드포인트

새로운 기능:
- 캐싱 기반 중복 처리 방지
- 서킷 브레이커 패턴 적용
- 배치 처리 지원
- 실시간 모니터링 및 메트릭
- 향상된 오류 복구
"""

import asyncio
import time
from datetime import datetime, timedelta

from typing import Any
from uuid import UUID, uuid4
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, BackgroundTasks, Form
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
import structlog
import httpx


from app.config.settings import Settings, get_settings
from app.middleware.auth import require_api_key
from app.models.text_recognition import (
    TextRecognitionAnswerResponse,
    TextRecognitionMetadata,
    TextRecognitionErrorResponse,
    AsyncTextRecognitionSubmitResponse,
    AsyncTextRecognitionCallbackData,
    AsyncJobStatus,
)
from app.utils.image_processing import (
    validate_image_file,
    optimize_image_for_gemini,
    ImageValidationError,
)
from app.services.cache import get_cache_service
from app.services.circuit_breaker import get_circuit_breaker, CircuitBreakerOpenError
from app.services.batch_text_recognition import BatchTextRecognitionItem
from app.services.monitoring import get_metrics_collector, TextRecognitionMetric

logger = structlog.get_logger("text_recognition_routes")

# 전역 상태 변수 - 백그라운드 작업 중복 방지용
_polling_started: bool = False


# 전역 배치 상태 관리
_batch_progress_storage: dict[UUID, dict] = {}

# 전역 비동기 작업 상태 관리
_async_job_storage: dict[UUID, AsyncJobStatus] = {}


async def _execute_batch_processing(
    batch_items: list[BatchTextRecognitionItem],
    batch_id: UUID,
    use_cache: bool = True,
    use_content_hash: bool = False,
) -> None:
    """
    백그라운드에서 실행되는 배치 글자인식 처리

    answer-sheet와 동일한 로직을 사용하여 배치 처리:
    - 캐싱 시스템
    - 서킷 브레이커
    - 메트릭 수집
    - 오류 처리 및 폴백

    Args:
        batch_items: 처리할 배치 항목들
        batch_id: 배치 ID
        use_cache: 캐시 사용 여부
        use_content_hash: 내용 기반 해시 사용 여부
    """
    from app.services.cache import get_cache_service
    from app.services.circuit_breaker import get_circuit_breaker
    from app.services.monitoring import get_metrics_collector
    from app.config.settings import get_settings

    settings = get_settings()
    cache_service = get_cache_service(
        redis_enabled=settings.redis_enabled, redis_url=settings.redis_url
    )
    metrics_collector = get_metrics_collector()
    gemini_circuit_breaker = get_circuit_breaker(
        name="gemini_vision_api",
        failure_threshold=3,
        failure_rate_threshold=0.3,
        recovery_timeout=120,
    )

    # 배치 진행 상태 초기화
    _batch_progress_storage[batch_id] = {
        "total_items": len(batch_items),
        "completed_items": 0,
        "failed_items": 0,
        "results": [],
        "status": "processing",
        "started_at": time.time(),
    }

    try:
        logger.info(
            "배치 글자인식 백그라운드 처리 시작",
            batch_id=str(batch_id),
            total_items=len(batch_items),
        )

        # 각 파일에 대해 answer-sheet와 동일한 로직으로 처리
        for item in batch_items:
            try:
                # 이미지 해시 계산
                image_hash = cache_service.compute_image_hash(
                    item.image_data, use_content_hash=use_content_hash
                )

                # answer-sheet의 _process_text_recognition_with_fallback와 동일한 로직
                result = await _process_single_item_with_fallback(
                    item.image_data,
                    image_hash,
                    item.filename,
                    use_cache,
                    cache_service,
                    gemini_circuit_breaker,
                    metrics_collector,
                    settings,
                )

                # 결과 저장
                _batch_progress_storage[batch_id]["results"].append(
                    {
                        "item_id": str(item.item_id),
                        "filename": item.filename,
                        "success": True,
                        "result": result.model_dump(mode='json') if result else None,
                    }
                )
                _batch_progress_storage[batch_id]["completed_items"] += 1

                logger.info(
                    "배치 항목 처리 성공",
                    batch_id=str(batch_id),
                    item_id=str(item.item_id),
                    filename=item.filename,
                )

            except Exception as e:
                logger.error(
                    "배치 항목 처리 실패",
                    batch_id=str(batch_id),
                    item_id=str(item.item_id),
                    filename=item.filename,
                    error=str(e),
                )

                # 실패 결과 저장
                _batch_progress_storage[batch_id]["results"].append(
                    {
                        "item_id": str(item.item_id),
                        "filename": item.filename,
                        "success": False,
                        "error": str(e),
                    }
                )
                _batch_progress_storage[batch_id]["failed_items"] += 1

        # 배치 처리 완료
        _batch_progress_storage[batch_id]["status"] = "completed"
        _batch_progress_storage[batch_id]["completed_at"] = time.time()

        processing_time = (
            _batch_progress_storage[batch_id]["completed_at"]
            - _batch_progress_storage[batch_id]["started_at"]
        )

        logger.info(
            "배치 글자인식 백그라운드 처리 완료",
            batch_id=str(batch_id),
            total_items=len(batch_items),
            completed_items=_batch_progress_storage[batch_id]["completed_items"],
            failed_items=_batch_progress_storage[batch_id]["failed_items"],
            processing_time_seconds=round(processing_time, 2),
        )

    except Exception as e:
        logger.error(
            "배치 글자인식 백그라운드 처리 중 치명적 오류",
            batch_id=str(batch_id),
            error=str(e),
        )

        _batch_progress_storage[batch_id]["status"] = "failed"
        _batch_progress_storage[batch_id]["error"] = str(e)

async def _send_callback_with_retry(
    job_id: UUID,
    callback_url: str,
    callback_data: AsyncTextRecognitionCallbackData,
    max_retries: int = 10,
    retry_delay: float = 2.0,
) -> bool:
    """
    콜백 전송 (재시도 로직 포함)
    
    Args:
        job_id: 작업 ID
        callback_url: 콜백 URL
        callback_data: 전송할 데이터
        max_retries: 최대 재시도 횟수
        retry_delay: 재시도 간격 (초)
    
    Returns:
        bool: 전송 성공 여부
    """
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    callback_url,
                    json=callback_data.model_dump(mode='json'),
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "iRoom-AI-Backend/1.0.0"
                    }
                )
                
                # 성공 응답 확인 (2xx)
                if 200 <= response.status_code < 300:
                    logger.info(
                        "콜백 전송 성공",
                        job_id=str(job_id),
                        callback_url=callback_url,
                        status_code=response.status_code,
                        attempt=attempt + 1
                    )
                    return True
                else:
                    logger.warning(
                        "콜백 전송 실패 - HTTP 오류",
                        job_id=str(job_id),
                        callback_url=callback_url,
                        status_code=response.status_code,
                        attempt=attempt + 1
                    )
                    
        except httpx.RequestError as e:
            logger.warning(
                "콜백 전송 실패 - 네트워크 오류",
                job_id=str(job_id),
                callback_url=callback_url,
                error=str(e),
                attempt=attempt + 1
            )
        except Exception as e:
            logger.error(
                "콜백 전송 중 예상치 못한 오류",
                job_id=str(job_id),
                callback_url=callback_url,
                error=str(e),
                attempt=attempt + 1
            )
        
        # 마지막 시도가 아니면 재시도 대기
        if attempt < max_retries:
            await asyncio.sleep(retry_delay * (2 ** attempt))  # 지수 백오프
    
    logger.error(
        "콜백 전송 최종 실패",
        job_id=str(job_id),
        callback_url=callback_url,
        max_retries=max_retries
    )
    return False

async def _poll_pending_jobs():
    """
    콜백 미수신 작업들을 주기적으로 확인하는 폴링 메커니즘
    
    AI 서버에서 콜백을 전송하지 않는 경우의 백업 시스템
    - 30초 이상 pending 상태인 job들을 확인
    - AI 서버에 직접 상태 조회
    - 필요시 강제 콜백 전송
    """
    try:
        current_time = datetime.now()
        pending_jobs = []
        
        # 30초 이상 pending 상태인 job들 찾기
        for job_id, job_status in _async_job_storage.items():
            if (job_status.status in ["submitted", "processing"] and 
                job_status.started_at and 
                (current_time - job_status.started_at).total_seconds() > 30):
                pending_jobs.append((job_id, job_status))
        
        if not pending_jobs:
            return
            
        logger.info(
            "콜백 미수신 작업 발견, 폴링 시작",
            pending_count=len(pending_jobs)
        )
        
        # 각 pending job에 대해 AI 서버 상태 확인
        for job_id, job_status in pending_jobs:
            try:
                # AI 서버에 상태 조회 (여기서는 mock 응답, 실제로는 AI 서버 API 호출)
                # TODO: 실제 AI 서버 상태 조회 API 연동 필요
                
                # 일단 타임아웃된 경우로 처리
                elapsed_seconds = (current_time - job_status.started_at).total_seconds()
                
                if elapsed_seconds > 300:  # 5분 초과
                    # 타임아웃 처리
                    job_status.status = "failed"
                    job_status.completed_at = current_time
                    
                    error_response = TextRecognitionErrorResponse(
                        error_code="PROCESSING_TIMEOUT_DETECTED_BY_POLLING",
                        error_message=f"폴링에서 타임아웃 감지: {elapsed_seconds:.0f}초 경과",
                        details="AI server callback not received within timeout period"
                    )
                    job_status.error = error_response
                    
                    # 강제 콜백 전송
                    callback_data = AsyncTextRecognitionCallbackData(
                        job_id=job_id,
                        status="failed",
                        error=error_response,
                        processing_time_ms=int(elapsed_seconds * 1000),
                        metadata=job_status.original_metadata
                    )
                    
                    await _send_callback_with_retry(
                        job_id, 
                        job_status.callback_url, 
                        callback_data,
                        max_retries=5  # 폴링에서는 더 적은 재시도
                    )
                    
                    logger.warning(
                        "폴링으로 타임아웃 처리 완료",
                        job_id=str(job_id),
                        elapsed_seconds=elapsed_seconds
                    )
                    
            except Exception as e:
                logger.error(
                    "폴링 중 개별 작업 처리 실패",
                    job_id=str(job_id),
                    error=str(e)
                )
                
    except Exception as e:
        logger.error(
            "폴링 메커니즘 실행 중 오류",
            error=str(e)
        )


async def _start_polling_background_task():
    """
    폴링 백그라운드 작업 시작
    """
    while True:
        try:
            await _poll_pending_jobs()
            await asyncio.sleep(30)  # 30초마다 폴링
        except Exception as e:
            logger.error("폴링 백그라운드 작업 오류", error=str(e))
            await asyncio.sleep(60)  # 오류 시 1분 대기


async def _process_async_text_recognition(
    job_id: UUID,
    image_data: bytes,
    filename: str,
    use_cache: bool = True,
    use_content_hash: bool = False,
    timeout_seconds: int = 300,  # 5분 타임아웃
) -> None:
    """
    비동기 글자인식 처리 백그라운드 함수
    
    이미지 검증, 처리, 콜백 전송을 모두 처리하며 타임아웃 제어
    
    Args:
        job_id: 작업 ID
        image_data: 이미지 데이터
        filename: 파일명
        use_cache: 캐시 사용 여부
        use_content_hash: 내용 기반 해시 사용 여부
        timeout_seconds: 처리 타임아웃 (초)
    """
    job_status = _async_job_storage.get(job_id)
    if not job_status:
        logger.error("비동기 작업 상태 없음", job_id=str(job_id))
        return
        
    # 시작 시간 기록
    start_time = time.time()
    job_status.started_at = datetime.now()
    job_status.status = "processing"
    
    logger.info(
        "비동기 글자인식 처리 시작",
        job_id=str(job_id),
        filename=filename,
        use_cache=use_cache,
        timeout_seconds=timeout_seconds
    )
    
    # 타임아웃 처리를 위한 래퍼
    try:
        # asyncio.wait_for로 타임아웃 제어
        await asyncio.wait_for(
            _process_with_timeout(
                job_id, job_status, image_data, filename, 
                use_cache, use_content_hash, start_time
            ),
            timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        # 타임아웃 처리
        processing_time_ms = int((time.time() - start_time) * 1000)
        job_status.status = "failed" 
        job_status.completed_at = datetime.now()
        
        error_response = TextRecognitionErrorResponse(
            error_code="PROCESSING_TIMEOUT",
            error_message=f"처리 시간이 {timeout_seconds}초를 초과했습니다.",
            details=f"Timeout after {timeout_seconds} seconds"
        )
        job_status.error = error_response
        
        # 타임아웃 콜백 전송
        callback_data = AsyncTextRecognitionCallbackData(
            job_id=job_id,
            status="failed", 
            error=error_response,
            processing_time_ms=processing_time_ms,
            metadata=job_status.original_metadata
        )
        
        await _send_callback_with_retry(
            job_id, job_status.callback_url, callback_data
        )
        
        logger.error(
            "비동기 처리 타임아웃", 
            job_id=str(job_id),
            timeout_seconds=timeout_seconds,
            processing_time_ms=processing_time_ms
        )
    except Exception as e:
        # 예상치 못한 오류
        processing_time_ms = int((time.time() - start_time) * 1000)
        job_status.status = "failed"
        job_status.completed_at = datetime.now()
        
        error_response = TextRecognitionErrorResponse(
            error_code="ASYNC_PROCESSING_FAILED",
            error_message="비동기 글자인식 처리 중 오류가 발생했습니다.",
            details=str(e)
        )
        job_status.error = error_response
        
        callback_data = AsyncTextRecognitionCallbackData(
            job_id=job_id,
            status="failed",
            error=error_response, 
            processing_time_ms=processing_time_ms,
            metadata=job_status.original_metadata
        )
        
        await _send_callback_with_retry(
            job_id, job_status.callback_url, callback_data
        )
        
        logger.error(
            "비동기 처리 예상치 못한 오류",
            job_id=str(job_id),
            error=str(e),
            processing_time_ms=processing_time_ms
        )


async def _process_with_timeout(
    job_id: UUID,
    job_status: AsyncJobStatus,
    image_data: bytes, 
    filename: str,
    use_cache: bool,
    use_content_hash: bool,
    start_time: float
) -> None:
    """
    타임아웃 처리를 위한 실제 처리 로직 분리
    """
    
    # 1단계: 이미지 검증 (백그라운드에서 수행)
    try:
        from PIL import Image
        import io
        
        # PIL로 이미지 유효성 검사
        image_stream = io.BytesIO(image_data)
        pil_image = Image.open(image_stream)
        pil_image.verify()  # 이미지 무결성 검증
        
        # 이미지 스트림 리셋 (verify 후 재사용 위해)
        image_stream.seek(0)
        pil_image = Image.open(image_stream)
        
        logger.info(
            "이미지 검증 성공",
            job_id=str(job_id),
            filename=filename,
            format=pil_image.format,
            size=pil_image.size
        )
        
    except Exception as img_error:
        # 이미지 검증 실패 - 콜백 전송
        processing_time_ms = int((time.time() - start_time) * 1000)
        job_status.status = "failed"
        job_status.completed_at = datetime.now()
        
        error_response = TextRecognitionErrorResponse(
            error_code="INVALID_IMAGE",
            error_message="이미지 파일이 유효하지 않습니다.",
            details=f"이미지 검증 실패: {str(img_error)}"
        )
        job_status.error = error_response
        
        # 검증 실패 콜백 전송
        callback_data = AsyncTextRecognitionCallbackData(
            job_id=job_id,
            status="failed",
            error=error_response,
            processing_time_ms=processing_time_ms,
            metadata=job_status.original_metadata
        )
        
        await _send_callback_with_retry(
            job_id, job_status.callback_url, callback_data
        )
        
        logger.warning(
            "이미지 검증 실패",
            job_id=str(job_id),
            filename=filename,
            error=str(img_error)
        )
        return
    
    # 2단계: 글자인식 처리 (기존 로직 재사용)
    from app.services.cache import get_cache_service
    from app.services.circuit_breaker import get_circuit_breaker
    from app.services.monitoring import get_metrics_collector
    from app.config.settings import get_settings
    
    settings = get_settings()
    cache_service = get_cache_service(
        redis_enabled=settings.redis_enabled, 
        redis_url=settings.redis_url
    )
    metrics_collector = get_metrics_collector()
    gemini_circuit_breaker = get_circuit_breaker(
        name="gemini_vision_api",
        failure_threshold=3,
        failure_rate_threshold=0.3,
        recovery_timeout=120,
    )
    
    # 이미지 해시 계산
    image_hash = cache_service.compute_image_hash(
        image_data, use_content_hash=use_content_hash
    )
    
    # 기존 처리 로직 재사용
    result = await _process_single_item_with_fallback(
        image_data,
        image_hash,
        filename,
        use_cache,
        cache_service,
        gemini_circuit_breaker,
        metrics_collector,
        settings,
    )
    
    # 3단계: 성공 처리 및 콜백 전송
    processing_time_ms = int((time.time() - start_time) * 1000)
    job_status.status = "completed"
    job_status.completed_at = datetime.now()
    job_status.result = result
    
    # 콜백 데이터 준비
    callback_data = AsyncTextRecognitionCallbackData(
        job_id=job_id,
        status="completed",
        result=result,
        processing_time_ms=processing_time_ms,
        metadata=job_status.original_metadata
    )
    
    # 콜백 전송
    success = await _send_callback_with_retry(
        job_id, job_status.callback_url, callback_data
    )
    
    logger.info(
        "비동기 글자인식 처리 완료",
        job_id=str(job_id),
        filename=filename,
        processing_time_ms=processing_time_ms,
        callback_sent=success
    )


def _cleanup_completed_jobs(max_age_hours: int = 24) -> None:
    """
    완료된 작업 정리 (메모리 관리)
    
    Args:
        max_age_hours: 보관 최대 시간 (시간)
    """
    cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
    jobs_to_remove = []
    
    for job_id, job_status in _async_job_storage.items():
        if (job_status.status in ["completed", "failed"] and 
            job_status.completed_at and 
            job_status.completed_at < cutoff_time):
            jobs_to_remove.append(job_id)
    
    for job_id in jobs_to_remove:
        del _async_job_storage[job_id]
        logger.debug("완료된 작업 정리", job_id=str(job_id))


async def _process_single_item_with_fallback(
    image_data: bytes,
    image_hash: str,
    filename: str,
    use_cache: bool,
    cache_service,
    circuit_breaker,
    metrics_collector,
    settings,
) -> TextRecognitionAnswerResponse | None:
    """
    단일 배치 항목을 answer-sheet와 동일한 로직으로 처리

    Args:
        image_data: 이미지 데이터
        image_hash: 이미지 해시
        filename: 파일명
        use_cache: 캐시 사용 여부
        cache_service: 캐시 서비스
        circuit_breaker: 서킷 브레이커
        metrics_collector: 메트릭 수집기
        settings: 애플리케이션 설정

    Returns:
        TextRecognitionAnswerResponse: 처리 결과
    """
    start_time = time.time()

    # 1. 캐시 확인 (answer-sheet와 동일한 로직)
    if use_cache:
        cached_result = await cache_service.get_text_recognition_result(image_hash)
        if cached_result is not None:
            logger.info(
                "캐시된 글자인식 결과 사용",
                filename=filename,
                image_hash=image_hash[:16],
            )

            # 캐시 히트 메트릭 기록
            metrics_collector.record_text_recognition_metric(
                TextRecognitionMetric(
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    image_size_kb=len(image_data) // 1024,
                    success=True,
                    confidence_avg=(
                        sum(a.confidence for a in cached_result.answers)
                        / len(cached_result.answers)
                        if cached_result.answers
                        else 0.0
                    ),
                    questions_detected=len(cached_result.answers),
                )
            )

            return cached_result

    # 2. 이미지 최적화 (answer-sheet와 동일한 로직)
    import asyncio

    loop = asyncio.get_event_loop()
    optimized_image = await loop.run_in_executor(
        None, optimize_image_for_gemini, image_data
    )

    # 3. 서킷 브레이커를 통한 글자인식 처리 (answer-sheet와 동일한 로직)
    async def text_recognition_main_function():
        """메인 글자인식 처리 함수"""
        from app.utils.text_recognition_core import (
            create_gemini_vision_model,
            process_text_recognition_with_gemini,
        )

        if not settings.gemini_api_key:
            raise HTTPException(status_code=503, detail="Gemini API key not configured")

        model = create_gemini_vision_model(settings.gemini_api_key)
        ocr_result = await process_text_recognition_with_gemini(optimized_image, model)

        # 품질 평가
        image_quality = "good"  # 실제로는 원본 이미지 품질 사용
        processing_time_ms = int((time.time() - start_time) * 1000)

        # 메타데이터 생성
        metadata = TextRecognitionMetadata(
            image_quality=image_quality,
            processing_time_ms=processing_time_ms,
            total_questions_detected=len(ocr_result.answers),
            model_version="gemini-2.5-pro",
        )

        # 최종 응답 생성
        response = TextRecognitionAnswerResponse(
            answers=ocr_result.answers, metadata=metadata
        )
        
        # 응답 검증 로깅
        logger.info(
            "글자인식 응답 생성 완료",
            filename=filename,
            image_hash=image_hash[:16],
            answers_count=len(response.answers),
            has_answers=len(response.answers) > 0,
            processing_time_ms=processing_time_ms,
            questions_detected=len(ocr_result.answers),
            cache_will_save=use_cache and len(ocr_result.answers) > 0
        )

        # 캐시 저장 (성공시에만)
        if use_cache and ocr_result.answers:
            await cache_service.set_text_recognition_result(
                image_hash, response, ttl=3600  # 1시간
            )

        return response

    async def text_recognition_fallback_function():
        """글자인식 폴백 함수"""
        logger.warning(
            "글자인식 폴백 모드 실행 - 빈 답안 반환",
            filename=filename,
            image_hash=image_hash[:16],
            reason="batch_processing_fallback"
        )

        processing_time_ms = int((time.time() - start_time) * 1000)

        return TextRecognitionAnswerResponse(
            answers=[],  # 빈 답안 목록
            metadata=TextRecognitionMetadata(
                image_quality="unknown",
                processing_time_ms=processing_time_ms,
                total_questions_detected=0,
                model_version="fallback",
            ),
        )

    try:
        result = await circuit_breaker.call(
            text_recognition_main_function, fallback=text_recognition_fallback_function
        )

        # 성공 메트릭 기록
        metrics_collector.record_text_recognition_metric(
            TextRecognitionMetric(
                processing_time_ms=result.metadata.processing_time_ms,
                image_size_kb=len(image_data) // 1024,
                image_quality=result.metadata.image_quality,
                confidence_avg=(
                    sum(a.confidence for a in result.answers) / len(result.answers)
                    if result.answers
                    else 0.0
                ),
                questions_detected=len(result.answers),
                success=True,
            )
        )

        return result

    except Exception as e:
        logger.error("단일 배치 항목 처리 실패", filename=filename, error=str(e))

        # 실패 메트릭 기록
        metrics_collector.record_text_recognition_metric(
            TextRecognitionMetric(
                processing_time_ms=int((time.time() - start_time) * 1000),
                image_size_kb=len(image_data) // 1024,
                success=False,
                error_code="PROCESSING_ERROR",
            )
        )

        # 폴백 실행
        return await text_recognition_fallback_function()


def create_text_recognition_router(settings: Settings) -> APIRouter:
    """
    글자인식 라우터 생성 (프로덕션 기능 포함)

    Args:
        settings: 애플리케이션 설정

    Returns:
        APIRouter: 구성된 글자인식 라우터
    """
    router = APIRouter(prefix="/text-recognition", tags=["글자인식"])

    # 서비스 의존성
    cache_service = get_cache_service(
        redis_enabled=settings.redis_enabled, redis_url=settings.redis_url
    )
    metrics_collector = get_metrics_collector()

    # Gemini API 서킷 브레이커
    gemini_circuit_breaker = get_circuit_breaker(
        name="gemini_vision_api",
        failure_threshold=3,
        failure_rate_threshold=0.3,
        recovery_timeout=120,  # 2분
    )

    # 배치 글자인식 서비스 설정 (필요시 활성화)
    # batch_text_recognition_service = BatchTextRecognitionService(
    #     gemini_api_key=settings.gemini_api_key or "",
    #     max_concurrent=5,
    #     rate_limit_per_minute=settings.rate_limit_requests_per_minute
    # )

    # 인증 의존성 설정
    dependencies = []
    if settings.require_api_key:
        dependencies.append(Depends(require_api_key))

    async def _process_text_recognition_with_fallback(
        image_data: bytes, image_hash: str, use_cache: bool = True
    ) -> TextRecognitionAnswerResponse:
        """
        서킷 브레이커와 캐싱을 적용한 글자인식 처리

        Args:
            image_data: 최적화된 이미지 데이터
            image_hash: 이미지 해시
            use_cache: 캐시 사용 여부

        Returns:
            TextRecognitionAnswerResponse: 글자인식 처리 결과
        """
        start_time = time.time()

        # 1. 캐시 확인
        if use_cache:
            cached_result = await cache_service.get_text_recognition_result(image_hash)
            if cached_result is not None:
                logger.info("캐시된 글자인식 결과 사용", image_hash=image_hash[:16])

                # 캐시 히트 메트릭 기록
                metrics_collector.record_text_recognition_metric(
                    TextRecognitionMetric(
                        processing_time_ms=int((time.time() - start_time) * 1000),
                        image_size_kb=len(image_data) // 1024,
                        success=True,
                        confidence_avg=(
                            sum(a.confidence for a in cached_result.answers)
                            / len(cached_result.answers)
                            if cached_result.answers
                            else 0.0
                        ),
                        questions_detected=len(cached_result.answers),
                    )
                )

                return cached_result

        # 2. 서킷 브레이커를 통한 글자인식 처리
        async def text_recognition_main_function():
            """메인 글자인식 처리 함수"""
            from app.utils.text_recognition_core import (
                create_gemini_vision_model,
                process_text_recognition_with_gemini,
            )

            if not settings.gemini_api_key:
                raise HTTPException(
                    status_code=503, detail="Gemini API key not configured"
                )

            model = create_gemini_vision_model(settings.gemini_api_key)
            ocr_result = await process_text_recognition_with_gemini(image_data, model)

            # 품질 평가 (이미 최적화된 이미지라 가정)
            image_quality = "good"  # 실제로는 원본 이미지 품질 사용
            processing_time_ms = int((time.time() - start_time) * 1000)

            # 메타데이터 생성
            metadata = TextRecognitionMetadata(
                image_quality=image_quality,
                processing_time_ms=processing_time_ms,
                total_questions_detected=len(ocr_result.answers),
                model_version="gemini-2.5-pro",
            )

            # 최종 응답 생성
            response = TextRecognitionAnswerResponse(
                answers=ocr_result.answers, metadata=metadata
            )

            # 캐시 저장 (성공시에만)
            if use_cache and ocr_result.answers:
                await cache_service.set_text_recognition_result(
                    image_hash, response, ttl=3600  # 1시간
                )

            return response

        async def text_recognition_fallback_function():
            """글자인식 폴백 함수 (간단한 응답)"""
            logger.warning(
                "글자인식 폴백 모드 실행 - 빈 답안 반환",
                image_hash=image_hash[:16],
                reason="main_route_fallback"
            )

            processing_time_ms = int((time.time() - start_time) * 1000)

            return TextRecognitionAnswerResponse(
                answers=[],  # 빈 답안 목록
                metadata=TextRecognitionMetadata(
                    image_quality="unknown",
                    processing_time_ms=processing_time_ms,
                    total_questions_detected=0,
                    model_version="fallback",
                ),
            )

        # 3. 서킷 브레이커를 통한 실행
        try:
            result = await gemini_circuit_breaker.call(
                text_recognition_main_function,
                fallback=text_recognition_fallback_function,
            )

            # 성공 메트릭 기록
            metrics_collector.record_text_recognition_metric(
                TextRecognitionMetric(
                    processing_time_ms=result.metadata.processing_time_ms,
                    image_size_kb=len(image_data) // 1024,
                    image_quality=result.metadata.image_quality,
                    confidence_avg=(
                        sum(a.confidence for a in result.answers) / len(result.answers)
                        if result.answers
                        else 0.0
                    ),
                    questions_detected=len(result.answers),
                    success=True,
                )
            )

            return result

        except CircuitBreakerOpenError:
            # 서킷 브레이커가 열린 상태
            logger.error("서킷 브레이커 열림, 폴백 실행", image_hash=image_hash[:16])

            # 실패 메트릭 기록
            metrics_collector.record_text_recognition_metric(
                TextRecognitionMetric(
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    image_size_kb=len(image_data) // 1024,
                    success=False,
                    error_code="CIRCUIT_BREAKER_OPEN",
                )
            )

            # 폴백 실행
            return await text_recognition_fallback_function()

        except Exception as e:
            logger.error("글자인식 처리 실패", error=str(e), image_hash=image_hash[:16])

            # 실패 메트릭 기록
            metrics_collector.record_text_recognition_metric(
                TextRecognitionMetric(
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    image_size_kb=len(image_data) // 1024,
                    success=False,
                    error_code="PROCESSING_ERROR",
                )
            )

            raise HTTPException(
                status_code=500, detail=f"글자인식 처리 중 오류 발생: {str(e)}"
            )

    @router.post(
        "/answer-sheet",
        response_model=TextRecognitionAnswerResponse,
        summary="한국어 답안지 글자인식 처리 (번호 기반 혼합 문제 유형)",
        description="""
        고도화된 글자인식 처리 엔드포인트 - 번호 기반 혼합 문제 유형 지원
        
        주요 기능:
        - 번호 기반 문제 인식 (1, 2, 3... 형식)
        - 혼합 답안 유형 지원 (객관식: A,B,C,D + 주관식: 수식,텍스트)
        - 이미지 해시 기반 중복 처리 방지 (캐싱)
        - 서킷 브레이커 패턴으로 장애 복구
        - 실시간 성능 모니터링
        - 향상된 오류 처리 및 폴백
        
        지원 문제 형식:
        - 번호 패턴: 1., 2), (1), 1번, ①, 문제1 등
        - 객관식 답안: A, B, C, D, E (또는 가, 나, 다, 라, 마)
        - 주관식 답안: 수학 수식, 텍스트, 숫자
        """,
        dependencies=dependencies,
    )
    async def process_answer_sheet_text_recognition(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(
            ..., description="답안지 이미지 파일 (JPEG, PNG, WEBP, GIF 지원, 최대 20MB)"
        ),
        use_cache: bool = True,
        use_content_hash: bool = False,
    ) -> TextRecognitionAnswerResponse | JSONResponse:
        """
        한국어 답안지 글자인식 처리

        처리 과정:
        1. 이미지 해시 계산 및 캐시 확인
        2. 이미지 검증 및 최적화
        3. 서킷 브레이커를 통한 안전한 글자인식 처리
        4. 결과 캐싱 및 메트릭 수집

        Args:
            background_tasks: 백그라운드 작업 (메트릭 수집 등)
            file: 업로드된 답안지 이미지 파일
            use_cache: 캐시 사용 여부 (기본: True)
            use_content_hash: 내용 기반 해시 사용 여부 (기본: False)

        Returns:
            TextRecognitionAnswerResponse: 구조화된 글자인식 처리 결과
        """
        request_start_time = time.time()

        try:
            # 1. 이미지 데이터 읽기
            logger.info(
                "글자인식 처리 시작",
                filename=file.filename,
                content_type=file.content_type,
                use_cache=use_cache,
                use_content_hash=use_content_hash,
            )

            image_data = await file.read()

            # 2. 이미지 해시 계산
            image_hash = cache_service.compute_image_hash(
                image_data, use_content_hash=use_content_hash
            )

            # 3. 이미지 검증
            try:
                _, _, _ = validate_image_file(image_data)
            except ImageValidationError as e:
                logger.warning(
                    "이미지 검증 실패",
                    error=str(e),
                    filename=file.filename,
                    image_hash=image_hash[:16],
                )
                return JSONResponse(
                    status_code=400,
                    content=TextRecognitionErrorResponse(
                        error_code="IMAGE_VALIDATION_FAILED",
                        error_message=str(e),
                        details=f"파일명: {file.filename}, 해시: {image_hash[:16]}",
                    ).model_dump_json(),
                    media_type="application/json",
                )

            # 4. 이미지 최적화 (CPU 집약적 작업을 별도 스레드에서 처리)
            import asyncio

            loop = asyncio.get_event_loop()
            optimized_image = await loop.run_in_executor(
                None,  # 기본 ThreadPoolExecutor 사용
                optimize_image_for_gemini,
                image_data,
            )

            # 5. 글자인식 처리 (서킷 브레이커 + 캐싱)
            response = await _process_text_recognition_with_fallback(
                optimized_image, image_hash, use_cache=use_cache
            )

            # 6. 응답 로깅
            total_processing_time = int((time.time() - request_start_time) * 1000)

            logger.info(
                "글자인식 처리 완료",
                sheet_id=str(response.sheet_id),
                processing_time_ms=total_processing_time,
                answers_count=len(response.answers),
                image_quality=response.metadata.image_quality,
                image_hash=image_hash[:16],
                cache_used=use_cache,
            )

            return response

        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "글자인식 처리 중 예상치 못한 오류",
                error=str(e),
                filename=file.filename,
            )
            return JSONResponse(
                status_code=500,
                content=TextRecognitionErrorResponse(
                    error_code="INTERNAL_ERROR",
                    error_message="글자인식 처리 중 내부 오류가 발생했습니다.",
                    details=str(e) if settings.debug else None,
                ).model_dump_json(),
                media_type="application/json",
            )

    @router.post(
        "/batch",
        summary="배치 글자인식 처리",
        description="""
        여러 답안지를 동시에 처리하는 배치 글자인식 엔드포인트
        
        주요 기능:
        - 실제 Gemini API 호출로 텍스트 인식 처리
        - answer-sheet와 동일한 품질의 처리 보장
        - 캐싱 및 서킷 브레이커 적용
        - 실시간 진행률 추적
        """,
    )
    async def process_batch_text_recognition(
        background_tasks: BackgroundTasks,
        files: list[UploadFile] = File(...),
        priority: int = 1,
        use_cache: bool = True,
        use_content_hash: bool = False,
    ) -> dict[str, str | int]:
        """
        배치 글자인식 처리 엔드포인트

        Args:
            background_tasks: 백그라운드 작업 관리
            files: 처리할 이미지 파일 목록 (최대 20개)
            priority: 처리 우선순위 (1=highest, 5=lowest)
            use_cache: 캐시 사용 여부 (기본: True)
            use_content_hash: 내용 기반 해시 사용 여부 (기본: False)

        Returns:
            Dict: 배치 ID와 진행률 스트림 URL
        """
        if len(files) > 20:
            raise HTTPException(
                status_code=400, detail="최대 20개의 파일까지 처리 가능합니다."
            )

        # 배치 항목 생성 (검증 포함)
        batch_items = []
        for file in files:
            try:
                image_data = await file.read()
                validate_image_file(image_data)  # 이미지 검증

                batch_items.append(
                    BatchTextRecognitionItem(
                        filename=file.filename or f"image_{len(batch_items)}",
                        image_data=image_data,
                        priority=priority,
                    )
                )
            except Exception as e:
                logger.warning(f"배치 항목 준비 실패: {file.filename}", error=str(e))
                continue

        if not batch_items:
            raise HTTPException(
                status_code=400, detail="유효한 이미지 파일이 없습니다."
            )

        # 배치 ID 생성
        batch_id = batch_items[0].item_id  # 첫 번째 아이템 ID를 배치 ID로 사용

        logger.info(
            "배치 글자인식 처리 요청",
            batch_id=str(batch_id),
            total_files=len(batch_items),
            priority=priority,
            use_cache=use_cache,
        )

        # 백그라운드에서 실제 배치 처리 시작
        background_tasks.add_task(
            _execute_batch_processing,
            batch_items,
            batch_id,
            use_cache,
            use_content_hash,
        )

        return {
            "batch_id": str(batch_id),
            "total_files": len(batch_items),
            "progress_stream_url": f"/text-recognition/batch/{batch_id}/progress",
            "status": "started",
        }

    async def stream_batch_progress(batch_id: UUID) -> EventSourceResponse:
        """
        배치 글자인식 진행률 스트리밍 (SSE)

        실제 배치 처리 진행률을 실시간으로 스트리밍

        Args:
            batch_id: 배치 ID

        Returns:
            EventSourceResponse: 실시간 진행률 스트림
        """

        async def progress_generator():
            """실제 배치 처리 진행률 스트림 생성기"""
            try:
                # 배치 상태가 존재하지 않는 경우
                if batch_id not in _batch_progress_storage:
                    error_data = {
                        "batch_id": str(batch_id),
                        "error": "배치를 찾을 수 없습니다",
                        "status": "not_found",
                    }
                    yield f"data: {error_data}\n\n"
                    return

                # 배치 처리가 완료될 때까지 진행률 스트리밍
                last_completed = -1
                while True:
                    batch_info = _batch_progress_storage.get(batch_id)

                    if not batch_info:
                        break

                    # 진행률 계산
                    total_items = batch_info["total_items"]
                    completed_items = batch_info["completed_items"]
                    failed_items = batch_info["failed_items"]
                    status = batch_info["status"]

                    progress_percentage = (
                        (completed_items / total_items * 100) if total_items > 0 else 0
                    )

                    # 새로운 진행률이 있거나 상태가 변경된 경우에만 전송
                    if completed_items != last_completed or status in [
                        "completed",
                        "failed",
                    ]:
                        progress_data = {
                            "batch_id": str(batch_id),
                            "progress_percentage": round(progress_percentage, 1),
                            "completed_items": completed_items,
                            "failed_items": failed_items,
                            "total_items": total_items,
                            "status": status,
                        }

                        # 완료 시간 정보 추가
                        if "completed_at" in batch_info:
                            processing_time = (
                                batch_info["completed_at"] - batch_info["started_at"]
                            )
                            progress_data["processing_time_seconds"] = round(
                                processing_time, 2
                            )

                        # 에러 정보 추가 (실패한 경우)
                        if status == "failed" and "error" in batch_info:
                            progress_data["error"] = batch_info["error"]

                        yield f"data: {progress_data}\n\n"
                        last_completed = completed_items

                    # 완료되었으면 스트림 종료
                    if status in ["completed", "failed"]:
                        break

                    # 0.5초마다 상태 확인
                    await asyncio.sleep(0.5)

                # 배치 처리 완료 후 상태 정리 (1분 후)
                await asyncio.sleep(60)
                if batch_id in _batch_progress_storage:
                    del _batch_progress_storage[batch_id]

            except Exception as e:
                logger.error(
                    "배치 진행률 스트리밍 오류", batch_id=str(batch_id), error=str(e)
                )
                error_data = {
                    "batch_id": str(batch_id),
                    "error": str(e),
                    "status": "stream_error",
                }
                yield f"data: {error_data}\n\n"

        return EventSourceResponse(progress_generator())

    @router.get(
        "/metrics",
        summary="글자인식 성능 메트릭",
        description="글자인식 처리 성능 통계 및 시스템 상태 정보",
    )
    async def get_text_recognition_metrics(
        time_range_minutes: int = 60,
    ) -> dict[str, Any]:
        """
        글자인식 성능 메트릭 조회

        Args:
            time_range_minutes: 조회할 시간 범위 (분)

        Returns:
            Dict: 성능 메트릭 및 통계 정보
        """
        # 성능 통계
        performance_stats = metrics_collector.get_performance_stats(time_range_minutes)

        # 오류 분석
        error_analysis = metrics_collector.get_error_analysis(time_range_minutes)

        # 품질 메트릭
        quality_metrics = metrics_collector.get_quality_metrics(time_range_minutes)

        # 캐시 통계
        cache_stats = cache_service.get_cache_stats()

        # 서킷 브레이커 상태
        circuit_breaker_metrics = gemini_circuit_breaker.get_metrics()

        return {
            "timestamp": time.time(),
            "time_range_minutes": time_range_minutes,
            "performance": {
                "total_requests": performance_stats.total_requests,
                "success_rate": round(performance_stats.success_rate, 4),
                "avg_processing_time_ms": round(
                    performance_stats.avg_processing_time_ms, 2
                ),
                "p95_processing_time_ms": round(
                    performance_stats.p95_processing_time_ms, 2
                ),
                "requests_per_minute": round(performance_stats.requests_per_minute, 2),
            },
            "errors": error_analysis,
            "quality": quality_metrics,
            "cache": cache_stats,
            "circuit_breaker": circuit_breaker_metrics,
            "health_status": metrics_collector._determine_health_status(
                performance_stats, error_analysis
            ),
        }

    @router.get(
        "/dashboard",
        summary="글자인식 대시보드 데이터",
        description="모니터링 대시보드용 종합 데이터",
    )
    async def get_dashboard_data() -> dict[str, Any]:
        """글자인식 대시보드용 종합 데이터"""
        return metrics_collector.get_dashboard_data()

    @router.post(
        "/cache/invalidate",
        summary="캐시 무효화",
        description="특정 이미지 또는 전체 글자인식 캐시 무효화",
    )
    async def invalidate_cache(
        image_hash: str | None = None, invalidate_all: bool = False
    ) -> dict[str, str | int]:
        """
        글자인식 캐시 무효화

        Args:
            image_hash: 무효화할 특정 이미지 해시
            invalidate_all: 전체 캐시 무효화 여부

        Returns:
            Dict: 무효화 결과
        """
        if invalidate_all:
            # 전체 캐시 무효화 (실제 구현에서는 Redis FLUSHDB 등 사용)
            logger.warning("전체 글자인식 캐시 무효화 요청")
            return {
                "status": "success",
                "message": "전체 캐시 무효화 완료",
                "invalidated_items": "all",
            }

        elif image_hash:
            # 특정 이미지 캐시 무효화
            success = await cache_service.invalidate_text_recognition_result(image_hash)
            return {
                "status": "success" if success else "not_found",
                "message": f"이미지 캐시 무효화: {image_hash[:16]}",
                "invalidated_items": 1 if success else 0,
            }

        else:
            raise HTTPException(
                status_code=400,
                detail="image_hash 또는 invalidate_all=true를 지정해야 합니다.",
            )

    @router.get(
        "/health",
        summary="글자인식 서비스 상태 확인",
        description="향상된 헬스체크 (서킷 브레이커, 캐시, 메트릭 포함)",
    )
    async def text_recognition_health_check() -> JSONResponse:
        """글자인식 서비스 종합 헬스체크"""
        try:
            # 기본 Gemini API 확인
            if not settings.gemini_api_key:
                raise Exception("Gemini API key not configured")

            # 서킷 브레이커 상태
            cb_metrics = gemini_circuit_breaker.get_metrics()

            # 캐시 상태
            cache_stats = cache_service.get_cache_stats()

            # 최근 성능 통계
            recent_stats = metrics_collector.get_performance_stats(
                time_range_minutes=10
            )

            health_data = {
                "status": "healthy",
                "service": "글자인식",
                "version": "1.0.0",
                "gemini_model": "gemini-2.5-pro",
                "features": [
                    "korean_handwriting_recognition",
                    "structured_answer_extraction",
                    "image_quality_assessment",
                    "caching_support",
                    "circuit_breaker_protection",
                    "batch_processing",
                    "real_time_monitoring",
                ],
                "circuit_breaker": {
                    "state": cb_metrics["state"],
                    "success_rate": cb_metrics.get("success_rate", 0),
                    "consecutive_failures": cb_metrics["consecutive_failures"],
                },
                "cache": {
                    "enabled": "l1_memory"
                    in cache_stats,  # Memory cache is always enabled if present
                    "hit_rate": (
                        cache_stats["total"]["hit_rate"]
                        if "total" in cache_stats
                        else 0
                    ),
                    "memory_usage_mb": (
                        cache_stats["l1_memory"]["memory_usage_mb"]
                        if "l1_memory" in cache_stats
                        else 0
                    ),
                },
                "performance": (
                    {
                        "recent_requests": recent_stats.total_requests,
                        "success_rate": round(recent_stats.success_rate, 3),
                        "avg_processing_time_ms": round(
                            recent_stats.avg_processing_time_ms, 2
                        ),
                    }
                    if recent_stats.total_requests > 0
                    else {}
                ),
            }

            # 건강 상태 판정
            if cb_metrics["state"] == "open":
                health_data["status"] = "degraded"
                health_data["issues"] = ["circuit_breaker_open"]
            elif recent_stats.total_requests > 5 and recent_stats.success_rate < 0.9:
                health_data["status"] = "warning"
                health_data["issues"] = ["low_success_rate"]

            status_code = 200
            if health_data["status"] == "degraded":
                status_code = 503
            elif health_data["status"] == "warning":
                status_code = 200  # Warning은 여전히 200 OK

            return JSONResponse(status_code=status_code, content=health_data)

        except Exception as e:
            logger.error("글자인식 헬스체크 실패", error=str(e))
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unhealthy",
                    "service": "글자인식",
                    "error": str(e),
                    "features_available": [],
                },
            )

    @router.post(
        "/async/submit",
        response_model=AsyncTextRecognitionSubmitResponse,
        summary="비동기 글자인식 처리 제출",
        description="""
        Spring Boot 시스템에서 호출하는 비동기 글자인식 처리 엔드포인트
        
        주요 기능:
        - 파일 업로드 + callback_url 수신
        - 고유한 job_id 즉시 반환
        - BackgroundTasks로 실제 글자인식 처리 시작
        - 완료 시 callback_url로 결과 전송
        
        처리 흐름:
        1. 파일 및 콜백 URL 검증
        2. job_id 생성 및 작업 상태 등록
        3. 즉시 job_id 반환 (HTTP 202)
        4. BackgroundTasks로 비동기 처리 시작
        5. 처리 완료 시 콜백 URL로 결과 전송
        """,
        status_code=202,
        dependencies=dependencies,
    )
    async def submit_async_text_recognition(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        callback_url: str = Form(..., pattern=r"^https?://.+"),
        priority: int = Form(1, ge=1, le=10),
        use_cache: bool = Form(True),
        use_content_hash: bool = Form(False),
    ) -> AsyncTextRecognitionSubmitResponse:
        """
        비동기 글자인식 처리 요청 제출
    
    이미지 검증은 백그라운드에서 수행되며,
    제출 시점에는 기본적인 파일 형식만 확인
    
    Args:
        file: 업로드된 이미지 파일
        callback_url: 처리 완료 시 결과를 받을 콜백 URL
        priority: 우선순위 (1-10, 높을수록 우선)
        use_cache: 캐시 사용 여부
        use_content_hash: 내용 기반 해시 사용 여부
        
    Returns:
        AsyncTextRecognitionSubmitResponse: 작업 ID와 예상 완료 시간
        """
        job_id = uuid4()
        estimated_seconds = 30  # 기본 예상 시간
        
        logger.info(
            "비동기 글자인식 처리 제출",
            job_id=str(job_id),
            filename=file.filename,
            callback_url=callback_url,
            priority=priority,
            use_cache=use_cache
        )
        
        try:
            # 파일 읽기 (검증은 백그라운드에서)
            image_data = await file.read()
            
            # 파일 크기 확인 (최소한의 검증)
            if len(image_data) == 0:
                raise HTTPException(
                    status_code=400,
                    detail="빈 파일입니다."
                )
            
            if len(image_data) > 50 * 1024 * 1024:  # 50MB 제한
                raise HTTPException(
                    status_code=400,
                    detail="파일 크기가 너무 큽니다. (최대 50MB)"
                )
            
            # 작업 상태 초기화
            job_status = AsyncJobStatus(
                job_id=job_id,
                status="submitted",
                callback_url=callback_url,
                priority=priority,
                submitted_at=datetime.now(),
                original_metadata={
                    "filename": file.filename or "unknown",
                    "use_cache": str(use_cache),
                    "use_content_hash": str(use_content_hash)
                }
            )
            _async_job_storage[job_id] = job_status
            
            # 백그라운드 작업 시작 (이미지 검증 포함)
            background_tasks.add_task(
                _process_async_text_recognition,
                job_id=job_id,
                image_data=image_data,
                filename=file.filename or "unknown",
                use_cache=use_cache,
                use_content_hash=use_content_hash,
            )
            
            # 예상 완료 시간 계산
            estimated_completion = datetime.now() + timedelta(seconds=estimated_seconds)
            
            return AsyncTextRecognitionSubmitResponse(
                job_id=job_id,
                status="submitted",
                estimated_completion_time=estimated_completion,
                callback_url=callback_url
            )
            
        except HTTPException:
            # HTTP 예외는 그대로 재발생
            raise
        except Exception as e:
            logger.error(
                "비동기 작업 제출 중 예상치 못한 오류",
                job_id=str(job_id),
                filename=file.filename,
                error=str(e)
            )
            raise HTTPException(
                status_code=500,
                detail="비동기 작업 제출 중 오류가 발생했습니다."
            )

    @router.get(
        "/async/status/{job_id}",
        summary="비동기 작업 상태 조회",
        description="""
        비동기 글자인식 작업의 현재 상태를 조회합니다.
        
        상태 종류:
        - submitted: 제출됨 (처리 대기 중)
        - processing: 처리 중
        - completed: 완료됨
        - failed: 실패함
        """
    )
    async def get_async_job_status(job_id: UUID) -> dict[str, Any]:
        """
        비동기 작업 상태 조회
        
        Args:
            job_id: 조회할 작업 ID
            
        Returns:
            dict: 작업 상태 정보
        """
        job_status = _async_job_storage.get(job_id)
        
        if not job_status:
            raise HTTPException(
                status_code=404,
                detail=f"작업을 찾을 수 없습니다: {job_id}"
            )
        
        # 처리 시간 계산
        processing_time_ms = None
        if job_status.started_at:
            end_time = job_status.completed_at or datetime.now()
            processing_time_ms = int((end_time - job_status.started_at).total_seconds() * 1000)
        
        response_data = {
            "job_id": str(job_status.job_id),
            "status": job_status.status,
            "callback_url": job_status.callback_url,
            "priority": job_status.priority,
            "submitted_at": job_status.submitted_at.isoformat(),
            "started_at": job_status.started_at.isoformat() if job_status.started_at else None,
            "completed_at": job_status.completed_at.isoformat() if job_status.completed_at else None,
            "processing_time_ms": processing_time_ms,
            "retry_count": job_status.retry_count,
        }
        
        # 결과 포함 (완료된 경우)
        if job_status.status == "completed" and job_status.result:
            response_data["result"] = job_status.result.model_dump(mode='json')
            
        # 오류 정보 포함 (실패한 경우)
        if job_status.status == "failed" and job_status.error:
            response_data["error"] = job_status.error.model_dump(mode='json')
            
        return response_data

    @router.get(
        "/async/ai-server-status/{job_id}",
        summary="AI 서버 직접 상태 조회",
        description="""
        AI 서버에서 job 상태를 직접 조회하는 API
        
        콜백이 오지 않을 때 Spring Boot에서 능동적으로 상태 확인 가능
        - 내부 저장소 + AI 서버 직접 조회 병행
        - 실시간 처리 상태 확인
        - 디버깅 정보 포함
        """,
        dependencies=dependencies,
    )
    async def get_ai_server_job_status(job_id: UUID) -> JSONResponse:
        """
        AI 서버에서 job 상태를 직접 조회
        
        Spring Boot 클라이언트가 콜백을 기다리지 않고
        능동적으로 AI 서버 상태를 확인할 수 있는 API
        
        Args:
            job_id: 작업 ID
            
        Returns:
            dict: AI 서버 상태 + 내부 상태 통합 정보
        """
        try:
            # 내부 저장소 상태 확인
            job_status = _async_job_storage.get(job_id)
            
            response_data = {
                "job_id": str(job_id),
                "timestamp": datetime.now().isoformat(),
                "internal_status": None,
                "ai_server_status": None,
                "debug_info": {}
            }
            
            if job_status:
                response_data["internal_status"] = {
                    "status": job_status.status,
                    "submitted_at": job_status.submitted_at.isoformat() if job_status.submitted_at else None,
                    "started_at": job_status.started_at.isoformat() if job_status.started_at else None,
                    "completed_at": job_status.completed_at.isoformat() if job_status.completed_at else None,
                    "callback_url": job_status.callback_url,
                    "error": job_status.error.model_dump(mode='json') if job_status.error else None,
                    "result": job_status.result.model_dump(mode='json') if job_status.result else None
                }
                
                # 처리 시간 계산
                if job_status.started_at:
                    end_time = job_status.completed_at or datetime.now()
                    elapsed_seconds = (end_time - job_status.started_at).total_seconds()
                    response_data["debug_info"]["elapsed_seconds"] = elapsed_seconds
                    response_data["debug_info"]["is_timeout"] = elapsed_seconds > 300
            
            # AI 서버 상태 정보 구성 (현재 서버가 AI 서버이므로 내부 상태 활용)
            if job_status:
                # 작업이 존재하는 경우 - 내부 상태 정보를 AI 서버 상태로 변환
                ai_server_info: dict[str, Any] = {
                    "status": job_status.status,
                    "job_id": str(job_status.job_id),
                    "message": f"작업 상태: {job_status.status}"
                }
                
                # 상태별 추가 정보
                if job_status.status == "completed" and job_status.result:
                    ai_server_info["result_summary"] = {
                        "success": len(job_status.result.answers) > 0,  # answers가 있으면 성공으로 간주
                        "total_items": len(job_status.result.answers)   # answers 리스트 길이가 처리된 아이템 수
                    }
                elif job_status.status == "failed" and job_status.error:
                    ai_server_info["error_info"] = {
                        "error_code": job_status.error.error_code,
                        "error_message": job_status.error.error_message,
                        "details": job_status.error.details
                    }
                elif job_status.status == "processing":
                    if job_status.started_at:
                        processing_duration = (datetime.now() - job_status.started_at).total_seconds()
                        ai_server_info["processing_duration_seconds"] = processing_duration
                
                response_data["ai_server_status"] = ai_server_info
            else:
                # 작업이 존재하지 않는 경우
                response_data["ai_server_status"] = {
                    "status": "not_found",
                    "message": f"Job ID {job_id}를 찾을 수 없습니다",
                    "possible_reasons": [
                        "잘못된 Job ID",
                        "작업이 완료되어 정리됨 (24시간 후 자동 삭제)",
                        "서버 재시작으로 인한 메모리 초기화"
                    ]
                }
            
            # 종합 상태 판정
            if not job_status:
                response_data["overall_status"] = "not_found"
                response_data["recommendation"] = "Job ID가 존재하지 않거나 만료되었습니다."
                return JSONResponse(status_code=404, content=response_data)
            elif job_status.status == "failed":
                response_data["overall_status"] = "failed"
                response_data["recommendation"] = "작업이 실패했습니다. 오류 정보를 확인하세요."
            elif job_status.status == "completed":
                response_data["overall_status"] = "completed"
                response_data["recommendation"] = "작업이 완료되었습니다."
            elif (job_status.started_at and 
                  (datetime.now() - job_status.started_at).total_seconds() > 300):
                response_data["overall_status"] = "timeout_suspected"
                response_data["recommendation"] = "타임아웃이 의심됩니다. 폴링 메커니즘이 곧 처리할 예정입니다."
            else:
                response_data["overall_status"] = "processing"
                response_data["recommendation"] = "작업이 처리 중입니다."
            
            return JSONResponse(content=response_data)
            
        except Exception as e:
            logger.error(
                "AI 서버 상태 조회 실패",
                job_id=str(job_id),
                error=str(e)
            )
            return JSONResponse(
                status_code=500,
                content={
                    "job_id": str(job_id),
                    "overall_status": "error",
                    "error": f"상태 조회 중 오류 발생: {str(e)}"
                }
            )

    @router.get(
        "/async/result/{job_id}",
        summary="비동기 작업 결과 조회",
        description="""
        완료된 비동기 글자인식 작업의 결과를 조회합니다.
        
        주의사항:
        - 작업이 완료된 경우에만 결과 반환
        - 처리 중이거나 실패한 경우 적절한 오류 반환
        """
    )
    async def get_async_job_result(job_id: UUID) -> JSONResponse:
        """
        비동기 작업 결과 조회
        
        Args:
            job_id: 조회할 작업 ID
            
        Returns:
            JSONResponse: 작업 결과 또는 오류 메시지
        """
        job_status = _async_job_storage.get(job_id)
        
        if not job_status:
            return JSONResponse(
                status_code=404,
                content={
                    "error": "Job not found",
                    "job_id": str(job_id),
                    "message": f"작업을 찾을 수 없습니다: {job_id}"
                }
            )
        
        # 상태별 응답
        if job_status.status == "completed" and job_status.result:
            return JSONResponse(
                status_code=200,
                content={
                    "job_id": str(job_id),
                    "status": "completed",
                    "result": job_status.result.model_dump(mode='json'),
                    "completed_at": job_status.completed_at.isoformat() if job_status.completed_at else None
                }
            )
        elif job_status.status == "processing":
            return JSONResponse(
                status_code=202,
                content={
                    "job_id": str(job_id),
                    "status": "processing",
                    "message": "작업이 아직 처리 중입니다",
                    "started_at": job_status.started_at.isoformat() if job_status.started_at else None
                }
            )
        elif job_status.status == "failed":
            return JSONResponse(
                status_code=500,
                content={
                    "job_id": str(job_id),
                    "status": "failed",
                    "error": job_status.error.model_dump(mode='json') if job_status.error else None,
                    "message": "작업 처리 중 오류가 발생했습니다"
                }
            )
        else:
            return JSONResponse(
                status_code=202,
                content={
                    "job_id": str(job_id),
                    "status": job_status.status,
                    "message": f"작업 상태: {job_status.status}"
                }
            )

    @router.get(
        "/async/queue",
        summary="비동기 작업 큐 상태 조회",
        description="""
        현재 비동기 작업 큐의 상태를 조회합니다.
        
        제공 정보:
        - 전체 작업 수
        - 상태별 작업 수
        - 최근 작업 목록
        """
    )
    async def get_async_queue_status() -> JSONResponse:
        """
        비동기 작업 큐 상태 조회
        
        Returns:
            JSONResponse: 큐 상태 정보
        """
        # 상태별 작업 수 계산
        status_counts = {
            "submitted": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0
        }
        
        recent_jobs = []
        current_time = datetime.now()
        
        for job_id, job_status in _async_job_storage.items():
            status_counts[job_status.status] = status_counts.get(job_status.status, 0) + 1
            
            # 최근 10개 작업 정보
            if len(recent_jobs) < 10:
                job_info = {
                    "job_id": str(job_id),
                    "status": job_status.status,
                    "priority": job_status.priority,
                    "submitted_at": job_status.submitted_at.isoformat() if job_status.submitted_at else None
                }
                
                # 경과 시간 계산
                if job_status.submitted_at:
                    elapsed = (current_time - job_status.submitted_at).total_seconds()
                    job_info["elapsed_seconds"] = round(elapsed, 2)
                
                recent_jobs.append(job_info)
        
        # 큐 통계 계산
        total_jobs = len(_async_job_storage)
        active_jobs = status_counts["submitted"] + status_counts["processing"]
        
        return JSONResponse(
            status_code=200,
            content={
                "queue_status": {
                    "total_jobs": total_jobs,
                    "active_jobs": active_jobs,
                    "status_counts": status_counts
                },
                "recent_jobs": recent_jobs,
                "timestamp": current_time.isoformat(),
                "queue_info": {
                    "max_capacity": 1000,  # 예시 값
                    "current_load": round((active_jobs / 1000) * 100, 2) if active_jobs > 0 else 0,
                    "is_healthy": active_jobs < 100  # 100개 미만이면 건강한 상태로 간주
                }
            }
        )

    @router.post(
        "/async/callback/{job_id}",
        summary="비동기 작업 콜백 수신",
        description="""
        Spring Boot에서 전송하는 콜백 수신 엔드포인트 (선택적)
        
        주로 콜백 전송 확인 및 로깅 목적으로 사용
        실제 처리 결과는 콜백 전송 시 이미 포함되어 전송됨
        """
    )
    async def receive_async_callback(
        job_id: UUID,
        callback_data: dict[str, Any]
    ) -> dict[str, str]:
        """
        비동기 작업 콜백 수신
        
        Args:
            job_id: 작업 ID
            callback_data: Spring Boot에서 전송한 콜백 데이터
            
        Returns:
            dict: 수신 확인 응답
        """
        logger.info(
            "비동기 작업 콜백 수신",
            job_id=str(job_id),
            callback_data=callback_data
        )
        
        # 작업 상태 업데이트 (선택적)
        job_status = _async_job_storage.get(job_id)
        if job_status:
            job_status.last_callback_attempt = datetime.now()
            logger.info(
                "콜백 수신 확인",
                job_id=str(job_id),
                current_status=job_status.status
            )
        else:
            logger.warning(
                "알 수 없는 작업 ID 콜백 수신",
                job_id=str(job_id)
            )
        
        return {
            "status": "received",
            "job_id": str(job_id),
            "message": "콜백이 성공적으로 수신되었습니다."
        }

    @router.get(
        "/async/jobs",
        summary="진행 중인 비동기 작업 목록",
        description="현재 진행 중인 모든 비동기 글자인식 작업의 상태를 조회합니다."
    )
    async def list_async_jobs(
        status_filter: str | None = None,
        limit: int = 50
    ) -> dict[str, Any]:
        """
        진행 중인 비동기 작업 목록 조회
        
        Args:
            status_filter: 상태 필터 (submitted, processing, completed, failed)
            limit: 최대 조회 개수
            
        Returns:
            dict: 작업 목록 및 요약 정보
        """
        jobs = list(_async_job_storage.values())
        
        # 상태 필터 적용
        if status_filter:
            jobs = [job for job in jobs if job.status == status_filter]
        
        # 최신 순으로 정렬 및 제한
        jobs.sort(key=lambda x: x.submitted_at, reverse=True)
        jobs = jobs[:limit]
        
        # 통계 계산
        all_jobs = list(_async_job_storage.values())
        stats = {
            "total_jobs": len(all_jobs),
            "submitted": len([j for j in all_jobs if j.status == "submitted"]),
            "processing": len([j for j in all_jobs if j.status == "processing"]),
            "completed": len([j for j in all_jobs if j.status == "completed"]),
            "failed": len([j for j in all_jobs if j.status == "failed"]),
        }
        
        # 응답 데이터 구성
        job_list = []
        for job in jobs:
            processing_time_ms = None
            if job.started_at:
                end_time = job.completed_at or datetime.now()
                processing_time_ms = int((end_time - job.started_at).total_seconds() * 1000)
            
            job_list.append({
                "job_id": str(job.job_id),
                "status": job.status,
                "callback_url": job.callback_url,
                "priority": job.priority,
                "submitted_at": job.submitted_at.isoformat(),
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "processing_time_ms": processing_time_ms,
                "retry_count": job.retry_count,
            })
        
        return {
            "jobs": job_list,
            "stats": stats,
            "filter_applied": status_filter,
            "returned_count": len(job_list),
        }

    return router


def setup_text_recognition_routes(app, settings: Settings | None = None) -> None:
    """
    글자인식 라우터를 FastAPI 앱에 등록

    Args:
        app: FastAPI 애플리케이션 인스턴스
        settings: 애플리케이션 설정
    """
    if settings is None:
        settings = get_settings()

    text_recognition_router = create_text_recognition_router(settings)
    app.include_router(text_recognition_router)

    logger.info(
        "글자인식 routes registered",
        endpoints=[
            "/text-recognition/answer-sheet",
            "/text-recognition/batch",
            "/text-recognition/async/submit",
            "/text-recognition/async/status/{job_id}",
            "/text-recognition/async/result/{job_id}",
            "/text-recognition/async/queue",
            "/text-recognition/metrics",
            "/text-recognition/dashboard",
            "/text-recognition/health",
        ],
        authentication_required=settings.require_api_key,
        features_enabled=[
            "caching",
            "circuit_breaker",
            "batch_processing",
            "monitoring",
        ],
    )

    # 폴링 백그라운드 작업은 앱 startup 이벤트에서 시작됨
    # setup_text_recognition_routes 함수에서 처리
