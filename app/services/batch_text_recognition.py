"""
배치 OCR 처리 서비스

다중 답안지 동시 처리를 위한 비동기 배치 서비스

주요 기능:
- 병렬 OCR 처리 (asyncio + semaphore)
- 진행률 추적
- 부분 실패 처리
- 결과 집계 및 통계
"""

import asyncio
import time
from typing import Any, AsyncGenerator
from uuid import uuid4, UUID
from datetime import datetime
from pydantic import BaseModel, Field
import structlog

from langchain_google_genai import ChatGoogleGenerativeAI
from app.models.text_recognition import (
    TextRecognitionAnswerResponse,
    TextRecognitionAnswer,
    TextRecognitionMetadata,
    TextRecognitionErrorResponse,
)
from app.utils.image_processing import (
    validate_image_file,
    assess_image_quality,
    optimize_image_for_gemini,
    ImageValidationError,
)

logger = structlog.get_logger("batch_text_recognition")


class BatchTextRecognitionItem(BaseModel):
    """배치 글자인식 처리 항목"""

    item_id: UUID = Field(default_factory=uuid4)
    filename: str
    image_data: bytes
    priority: int = Field(default=1, ge=1, le=5)  # 1=highest, 5=lowest


class BatchTextRecognitionProgress(BaseModel):
    """배치 글자인식 진행 상태"""

    batch_id: UUID
    total_items: int
    completed_items: int
    failed_items: int
    started_at: datetime
    estimated_completion: datetime | None = None

    @property
    def progress_percentage(self) -> float:
        """진행률 계산 (0-100)"""
        if self.total_items == 0:
            return 100.0
        return (self.completed_items / self.total_items) * 100


class BatchTextRecognitionResult(BaseModel):
    """배치 글자인식 결과"""

    item_id: UUID
    filename: str
    success: bool
    result: TextRecognitionAnswerResponse | None = None
    error: TextRecognitionErrorResponse | None = None
    processing_time_ms: int


class BatchTextRecognitionSummary(BaseModel):
    """배치 글자인식 완료 요약"""

    batch_id: UUID
    total_items: int
    successful_items: int
    failed_items: int
    total_processing_time_ms: int
    average_processing_time_ms: float
    results: list[BatchTextRecognitionResult]


class BatchTextRecognitionService:
    """
    배치 글자인식 처리 서비스

    특징:
    - 동시성 제어 (semaphore 기반)
    - Rate limiting 준수
    - 실시간 진행률 추적
    - 부분 실패 허용
    - 우선순위 기반 처리
    """

    def __init__(
        self,
        gemini_api_key: str,
        max_concurrent: int = 5,
        rate_limit_per_minute: int = 15,
    ):
        """
        배치 OCR 서비스 초기화

        Args:
            gemini_api_key: Gemini API 키
            max_concurrent: 최대 동시 처리 수
            rate_limit_per_minute: 분당 요청 제한
        """
        self.gemini_api_key = gemini_api_key
        self.max_concurrent = max_concurrent
        self.rate_limit_per_minute = rate_limit_per_minute

        # 동시성 제어
        self.semaphore = asyncio.Semaphore(max_concurrent)

        # Rate limiting (단순 토큰 버킷 알고리즘)
        self.rate_limiter = asyncio.Semaphore(rate_limit_per_minute)

        # 진행 상태 추적
        self._progress_tracker: dict[UUID, BatchTextRecognitionProgress] = {}

        # Gemini 모델 (재사용)
        self._gemini_model: ChatGoogleGenerativeAI | None = None

    def _get_gemini_model(self) -> ChatGoogleGenerativeAI:
        """Gemini 모델 인스턴스 생성/재사용"""
        if self._gemini_model is None:
            self._gemini_model = ChatGoogleGenerativeAI(
                model="gemini-2.5-pro",
                google_api_key=self.gemini_api_key,
                temperature=0.1,
                max_output_tokens=8000,
            )
        return self._gemini_model

    async def _process_single_ocr(
        self, item: BatchTextRecognitionItem, batch_id: UUID
    ) -> BatchTextRecognitionResult:
        """
        단일 OCR 처리 (동시성 제어 적용)

        Args:
            item: 처리할 OCR 항목
            batch_id: 배치 ID

        Returns:
            BatchTextRecognitionResult: 처리 결과
        """
        start_time = time.time()

        async with self.semaphore:  # 동시성 제어
            async with self.rate_limiter:  # Rate limiting
                try:
                    # 이미지 검증
                    image_format, width, height = validate_image_file(item.image_data)

                    # 품질 평가
                    image_quality = assess_image_quality(item.image_data, width, height)

                    # 이미지 최적화
                    optimized_image = optimize_image_for_gemini(item.image_data)

                    # OCR 처리 (핵심 로직 사용)
                    gemini_model = self._get_gemini_model()

                    # 임시로 OCR 처리 함수를 여기서 구현 (모듈 분리 필요시 별도 유틸로 이동)
                    ocr_result = await self._call_gemini_vision(
                        optimized_image, gemini_model
                    )

                    # 처리 시간 계산
                    processing_time_ms = int((time.time() - start_time) * 1000)

                    # 메타데이터 생성
                    metadata = TextRecognitionMetadata(
                        image_quality=image_quality,
                        processing_time_ms=processing_time_ms,
                        total_questions_detected=len(ocr_result.get("answers", [])),
                        model_version="gemini-2.5-pro",
                    )

                    # 응답 생성
                    answers = []
                    for answer_data in ocr_result.get("answers", []):
                        try:
                            answers.append(TextRecognitionAnswer(**answer_data))
                        except Exception:
                            continue

                    response = TextRecognitionAnswerResponse(
                        answers=answers, metadata=metadata
                    )

                    # 성공 결과 반환
                    result = BatchTextRecognitionResult(
                        item_id=item.item_id,
                        filename=item.filename,
                        success=True,
                        result=response,
                        processing_time_ms=processing_time_ms,
                    )

                    logger.info(
                        "배치 OCR 항목 처리 성공",
                        batch_id=str(batch_id),
                        item_id=str(item.item_id),
                        filename=item.filename,
                        processing_time_ms=processing_time_ms,
                        image_quality=image_quality,
                    )

                    return result

                except ImageValidationError as e:
                    # 이미지 검증 오류
                    error_response = TextRecognitionErrorResponse(
                        error_code="IMAGE_VALIDATION_FAILED",
                        error_message=str(e),
                        details=f"파일명: {item.filename}",
                    )

                    processing_time_ms = int((time.time() - start_time) * 1000)

                    return BatchTextRecognitionResult(
                        item_id=item.item_id,
                        filename=item.filename,
                        success=False,
                        error=error_response,
                        processing_time_ms=processing_time_ms,
                    )

                except Exception as e:
                    # 일반 처리 오류
                    error_response = TextRecognitionErrorResponse(
                        error_code="PROCESSING_FAILED",
                        error_message="OCR 처리 중 오류가 발생했습니다.",
                        details=str(e),
                    )

                    processing_time_ms = int((time.time() - start_time) * 1000)

                    logger.error(
                        "배치 OCR 항목 처리 실패",
                        batch_id=str(batch_id),
                        item_id=str(item.item_id),
                        filename=item.filename,
                        error=str(e),
                    )

                    return BatchTextRecognitionResult(
                        item_id=item.item_id,
                        filename=item.filename,
                        success=False,
                        error=error_response,
                        processing_time_ms=processing_time_ms,
                    )

    async def _call_gemini_vision(
        self, image_data: bytes, model: ChatGoogleGenerativeAI
    ) -> dict[str, Any]:
        """
        Gemini Vision API 호출 (기존 로직과 동일)

        Args:
            image_data: 최적화된 이미지 데이터
            model: Gemini 모델 인스턴스

        Returns:
            Dict: 파싱된 OCR 결과
        """
        import json
        import base64
        from langchain_core.messages import HumanMessage

        # Base64 인코딩
        image_base64 = base64.b64encode(image_data).decode("utf-8")

        # 프롬프트 (기존과 동일)
        prompt = """
You are an expert Korean handwriting recognition specialist for exam answer sheets.

Extract all handwritten Korean text from subjective question areas in this image.

Return the results in this exact JSON format:
{
    "answers": [
        {
            "question_number": 1,
            "question_label": "주1",
            "extracted_text": "handwritten Korean text",
            "confidence": 0.85
        }
    ]
}
"""

        # 메시지 구성
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                },
            ]
        )

        # API 호출
        response = await model.ainvoke([message])

        # 응답 처리
        response_text = str(response.content).strip()

        # JSON 파싱 (기존 로직과 동일)
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_json = not in_json
                    continue
                if in_json:
                    json_lines.append(line)
            response_text = "\n".join(json_lines)

        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            return {"answers": []}

    async def process_batch(
        self, items: list[BatchTextRecognitionItem]
    ) -> AsyncGenerator[BatchTextRecognitionProgress, None]:
        """
        배치 OCR 처리 (스트리밍 진행률 포함)

        Args:
            items: 처리할 OCR 항목 목록

        Yields:
            BatchTextRecognitionProgress: 실시간 진행 상태
        """
        batch_id = uuid4()
        start_time = time.time()

        # 우선순위 정렬 (1=highest)
        sorted_items = sorted(items, key=lambda x: x.priority)

        # 진행 상태 초기화
        progress = BatchTextRecognitionProgress(
            batch_id=batch_id,
            total_items=len(items),
            completed_items=0,
            failed_items=0,
            started_at=datetime.now(),
        )
        self._progress_tracker[batch_id] = progress

        logger.info(
            "배치 OCR 처리 시작",
            batch_id=str(batch_id),
            total_items=len(items),
            max_concurrent=self.max_concurrent,
        )

        # 초기 진행률 전송
        yield progress

        # 비동기 처리 태스크 생성
        tasks = [self._process_single_ocr(item, batch_id) for item in sorted_items]

        results: list[BatchTextRecognitionResult] = []

        # 완료된 태스크부터 처리 (as_completed)
        for completed_task in asyncio.as_completed(tasks):
            try:
                result = await completed_task
                results.append(result)

                # 진행 상태 업데이트
                if result.success:
                    progress.completed_items += 1
                else:
                    progress.failed_items += 1

                # 완료 시간 추정
                elapsed_time = time.time() - start_time
                if progress.completed_items > 0:
                    estimated_total_time = elapsed_time * (
                        len(items) / progress.completed_items
                    )
                    remaining_time = estimated_total_time - elapsed_time
                    if remaining_time > 0:
                        progress.estimated_completion = datetime.fromtimestamp(
                            datetime.now().timestamp() + remaining_time
                        )

                # 진행률 전송
                yield progress

            except Exception as e:
                # 태스크 처리 중 예외 발생
                logger.error(
                    "배치 처리 태스크 오류", batch_id=str(batch_id), error=str(e)
                )
                progress.failed_items += 1
                yield progress

        # 배치 처리 완료
        total_time = int((time.time() - start_time) * 1000)

        # 통계 계산
        successful_count = sum(1 for r in results if r.success)
        failed_count = len(results) - successful_count
        avg_processing_time = (
            sum(r.processing_time_ms for r in results) / len(results) if results else 0
        )

        logger.info(
            "배치 OCR 처리 완료",
            batch_id=str(batch_id),
            total_items=len(items),
            successful_items=successful_count,
            failed_items=failed_count,
            total_processing_time_ms=total_time,
            average_processing_time_ms=round(avg_processing_time, 2),
        )

        # 진행 추적 정리
        del self._progress_tracker[batch_id]

    def get_batch_progress(self, batch_id: UUID) -> BatchTextRecognitionProgress | None:
        """배치 진행 상태 조회"""
        return self._progress_tracker.get(batch_id)

    def get_active_batches(self) -> list[BatchTextRecognitionProgress]:
        """활성 배치 목록 조회"""
        return list(self._progress_tracker.values())
