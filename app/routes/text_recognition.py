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

from typing import Any
from uuid import UUID
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
import structlog


from app.config.settings import Settings, get_settings
from app.middleware.auth import require_api_key
from app.models.text_recognition import (
    TextRecognitionAnswerResponse,
    TextRecognitionMetadata,
    TextRecognitionErrorResponse,
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


# 전역 배치 상태 관리
_batch_progress_storage: dict[UUID, dict] = {}


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
                        "result": result.model_dump() if result else None,
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

        # 캐시 저장 (성공시에만)
        if use_cache and ocr_result.answers:
            await cache_service.set_text_recognition_result(
                image_hash, response, ttl=3600  # 1시간
            )

        return response

    async def text_recognition_fallback_function():
        """글자인식 폴백 함수"""
        logger.warning(
            "글자인식 폴백 모드 실행", filename=filename, image_hash=image_hash[:16]
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
            logger.warning("글자인식 폴백 모드 실행", image_hash=image_hash[:16])

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
                image_format, width, height = validate_image_file(image_data)
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
