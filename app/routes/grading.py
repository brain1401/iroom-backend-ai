"""
채점 시스템 API 라우터

시험 답안 자동/AI 보조 채점을 위한 RESTful API 엔드포인트

주요 엔드포인트:
- POST /grading/{submission_id} - 단일 제출 채점
- GET /grading/{submission_id} - 채점 결과 조회  
- POST /grading/batch - 배치 채점
- GET /grading/progress/{batch_id} - 배치 채점 진행률 조회
- GET /grading/stats - 채점 시스템 통계
"""

import asyncio
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
import structlog

from app.config.settings import Settings, get_settings
from app.models.grading import (
    GradingRequest,
    ExamGradingResult,
    BatchGradingRequest,
    BatchGradingResult,
)
from app.services.grading_factory import get_repositories, get_grading_orchestrator

logger = structlog.get_logger("grading_api")

# FastAPI 라우터 생성
router = APIRouter(prefix="/grading", tags=["채점"])


@router.post("/{submission_id}", response_model=ExamGradingResult)
async def grade_submission(
    submission_id: UUID,
    request: GradingRequest | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    settings: Settings = Depends(get_settings),
) -> ExamGradingResult:
    """
    단일 시험 제출 채점

    제출 ID를 받아서 해당 제출의 모든 답안을 채점합니다.
    - 객관식: 자동 채점 (100% 정확도)
    - 주관식: AI 보조 채점 (gemini-2.5-pro)

    Args:
        submission_id: 채점할 제출 고유 ID
        request: 채점 옵션 (선택사항)
        background_tasks: 백그라운드 작업 관리
        settings: 애플리케이션 설정

    Returns:
        ExamGradingResult: 채점 완료된 결과

    Raises:
        HTTPException: 제출 정보 없음, 채점 실패 등
    """
    logger.info("단일 제출 채점 시작", submission_id=str(submission_id))

    try:
        # Repository 및 서비스 인스턴스 가져오기
        exam_repo, question_repo, grading_repo = get_repositories(settings)
        grading_orchestrator = get_grading_orchestrator(settings)

        # 1. 제출 정보 조회
        submission_data = await exam_repo.get_submission_by_id(submission_id)
        if not submission_data:
            raise HTTPException(
                status_code=404, detail=f"제출 정보를 찾을 수 없습니다: {submission_id}"
            )

        # 2. 시험지 ID 조회
        exam_sheet_id = await exam_repo.get_exam_sheet_id_by_submission_id(
            submission_id
        )
        if not exam_sheet_id:
            raise HTTPException(
                status_code=404,
                detail=f"시험지 정보를 찾을 수 없습니다: {submission_id}",
            )

        # 3. 기존 채점 결과 확인
        existing_result = await grading_repo.get_grading_result_by_submission_id(
            submission_id
        )
        if existing_result and not (request and request.force_regrade):
            logger.info(
                "기존 채점 결과 반환",
                submission_id=str(submission_id),
                result_id=str(existing_result.result_id),
            )
            return existing_result

        # 4. 문제 목록 조회
        questions = await question_repo.get_questions_by_exam_sheet_id(exam_sheet_id)
        if not questions:
            raise HTTPException(
                status_code=404,
                detail=f"시험지의 문제를 찾을 수 없습니다: {exam_sheet_id}",
            )

        # 5. 학생 답안 조회
        answers = await exam_repo.get_answers_by_submission_id(submission_id)
        if not answers:
            raise HTTPException(
                status_code=404,
                detail=f"제출된 답안을 찾을 수 없습니다: {submission_id}",
            )

        # 6. 채점 수행
        grading_result = await grading_orchestrator.grade_submission(
            submission_id=submission_id,
            questions=questions,
            answers=answers,
            exam_sheet_id=exam_sheet_id,
        )

        # 7. 채점 결과 저장 (백그라운드에서 실행)
        background_tasks.add_task(
            _save_grading_result_background, grading_repo, grading_result
        )

        logger.info(
            "단일 제출 채점 완료",
            submission_id=str(submission_id),
            total_score=grading_result.total_score,
            question_count=len(grading_result.question_results),
        )

        return grading_result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "단일 제출 채점 실패", submission_id=str(submission_id), error=str(e)
        )
        raise HTTPException(
            status_code=500, detail=f"채점 처리 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/{submission_id}", response_model=ExamGradingResult)
async def get_grading_result(
    submission_id: UUID, settings: Settings = Depends(get_settings)
) -> ExamGradingResult:
    """
    채점 결과 조회

    제출 ID로 해당 제출의 채점 결과를 조회합니다.

    Args:
        submission_id: 조회할 제출 고유 ID
        settings: 애플리케이션 설정

    Returns:
        ExamGradingResult: 채점 결과

    Raises:
        HTTPException: 채점 결과 없음
    """
    logger.info("채점 결과 조회", submission_id=str(submission_id))

    try:
        _, _, grading_repo = get_repositories(settings)

        result = await grading_repo.get_grading_result_by_submission_id(submission_id)
        if not result:
            raise HTTPException(
                status_code=404, detail=f"채점 결과를 찾을 수 없습니다: {submission_id}"
            )

        logger.info(
            "채점 결과 조회 완료",
            submission_id=str(submission_id),
            result_id=str(result.result_id),
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "채점 결과 조회 실패", submission_id=str(submission_id), error=str(e)
        )
        raise HTTPException(
            status_code=500, detail=f"채점 결과 조회 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/batch", response_model=BatchGradingResult)
async def grade_batch_submissions(
    request: BatchGradingRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    settings: Settings = Depends(get_settings),
) -> BatchGradingResult:
    """
    배치 채점 처리

    여러 제출을 동시에 채점합니다.
    최대 50개까지 동시 처리 가능합니다.

    Args:
        request: 배치 채점 요청 (제출 ID 목록)
        background_tasks: 백그라운드 작업 관리
        settings: 애플리케이션 설정

    Returns:
        BatchGradingResult: 배치 채점 결과

    Raises:
        HTTPException: 잘못된 요청, 처리 실패 등
    """
    logger.info(
        "배치 채점 시작",
        total_submissions=len(request.submission_ids),
        priority=request.priority,
    )

    try:
        # Repository 및 서비스 인스턴스 가져오기
        exam_repo, question_repo, grading_repo = get_repositories(settings)
        grading_orchestrator = get_grading_orchestrator(settings)

        # 배치 채점 실행
        batch_start_time = datetime.now()
        results: list[ExamGradingResult] = []
        failed_submissions: list[UUID] = []

        # 우선순위 기반 정렬
        sorted_submission_ids = sorted(
            request.submission_ids,
            key=lambda _: request.priority,  # 실제로는 개별 우선순위를 설정할 수 있음
        )

        # 병렬 채점 실행 (최대 동시성 제어)
        semaphore = asyncio.Semaphore(min(5, len(sorted_submission_ids)))

        async def process_single_submission(sub_id: UUID) -> ExamGradingResult | None:
            """단일 제출 처리 (세마포어 적용)"""
            async with semaphore:
                try:
                    # 제출 정보 조회
                    submission_data = await exam_repo.get_submission_by_id(sub_id)
                    if not submission_data:
                        logger.warning("제출 정보 없음", submission_id=str(sub_id))
                        return None

                    # 시험지 ID 조회
                    exam_sheet_id = await exam_repo.get_exam_sheet_id_by_submission_id(
                        sub_id
                    )
                    if not exam_sheet_id:
                        logger.warning("시험지 정보 없음", submission_id=str(sub_id))
                        return None

                    # 기존 채점 결과 확인
                    if not request.force_regrade:
                        existing_result = (
                            await grading_repo.get_grading_result_by_submission_id(
                                sub_id
                            )
                        )
                        if existing_result:
                            return existing_result

                    # 문제 목록 조회
                    questions = await question_repo.get_questions_by_exam_sheet_id(
                        exam_sheet_id
                    )
                    if not questions:
                        logger.warning(
                            "문제 정보 없음", exam_sheet_id=str(exam_sheet_id)
                        )
                        return None

                    # 학생 답안 조회
                    answers = await exam_repo.get_answers_by_submission_id(sub_id)
                    if not answers:
                        logger.warning("답안 정보 없음", submission_id=str(sub_id))
                        return None

                    # 채점 수행
                    result = await grading_orchestrator.grade_submission(
                        submission_id=sub_id,
                        questions=questions,
                        answers=answers,
                        exam_sheet_id=exam_sheet_id,
                    )

                    # 결과 저장
                    await grading_repo.save_grading_result(result)

                    return result

                except Exception as e:
                    logger.error(
                        "배치 채점 중 개별 제출 처리 실패",
                        submission_id=str(sub_id),
                        error=str(e),
                    )
                    return None

        # 모든 제출을 병렬로 처리
        tasks = [process_single_submission(sub_id) for sub_id in sorted_submission_ids]
        completed_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 결과 수집
        for i, result in enumerate(completed_results):
            submission_id = sorted_submission_ids[i]

            if isinstance(result, Exception):
                logger.error(
                    "배치 채점 중 예외 발생",
                    submission_id=str(submission_id),
                    error=str(result),
                )
                failed_submissions.append(submission_id)
            elif result is None:
                failed_submissions.append(submission_id)
            elif isinstance(result, ExamGradingResult):
                results.append(result)

        # 배치 결과 생성
        batch_end_time = datetime.now()
        total_processing_time_ms = int(
            (batch_end_time - batch_start_time).total_seconds() * 1000
        )

        batch_result = BatchGradingResult(
            batch_id=(
                results[0].result_id
                if results
                else UUID("00000000-0000-0000-0000-000000000000")
            ),
            total_submissions=len(request.submission_ids),
            successful_gradings=len(results),
            failed_gradings=len(failed_submissions),
            results=results,
            total_processing_time_ms=total_processing_time_ms,
            average_processing_time_ms=(
                total_processing_time_ms / len(results) if results else 0
            ),
        )

        logger.info(
            "배치 채점 완료",
            total_submissions=len(request.submission_ids),
            successful=len(results),
            failed=len(failed_submissions),
            processing_time_ms=total_processing_time_ms,
        )

        return batch_result

    except Exception as e:
        logger.error("배치 채점 실패", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"배치 채점 처리 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/stats")
async def get_grading_stats(settings: Settings = Depends(get_settings)) -> dict:
    """
    채점 시스템 통계 조회

    채점 서비스의 현재 상태 및 통계를 반환합니다.

    Args:
        settings: 애플리케이션 설정

    Returns:
        dict: 통계 정보
    """
    try:
        grading_orchestrator = get_grading_orchestrator(settings)

        # 활성 채점 작업 조회
        active_gradings = grading_orchestrator.get_active_gradings()

        # Repository 통계 (인메모리인 경우)
        repo_stats = {}
        if not settings.database_enabled:
            from app.repositories.memory_implementation import storage

            repo_stats = storage.get_stats()

        stats = {
            "service_status": "active",
            "active_grading_count": len(active_gradings),
            "active_gradings": [
                {
                    "submission_id": str(progress.submission_id),
                    "progress_percentage": progress.progress_percentage,
                    "remaining_questions": progress.remaining_questions,
                }
                for progress in active_gradings
            ],
            "configuration": {
                "database_enabled": settings.database_enabled,
                "max_concurrent_subjective": settings.grading_max_concurrent_subjective,
                "ai_model": settings.grading_ai_model,
                "confidence_threshold": settings.grading_confidence_threshold,
            },
            "memory_stats": repo_stats,
        }

        return stats

    except Exception as e:
        logger.error("통계 조회 실패", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"통계 조회 중 오류가 발생했습니다: {str(e)}"
        )


# 헬퍼 함수들


async def _save_grading_result_background(
    grading_repo, grading_result: ExamGradingResult
):
    """
    백그라운드에서 채점 결과 저장

    Args:
        grading_repo: 채점 Repository
        grading_result: 저장할 채점 결과
    """
    try:
        success = await grading_repo.save_grading_result(grading_result)
        if success:
            logger.info(
                "백그라운드 채점 결과 저장 성공",
                result_id=str(grading_result.result_id),
            )
        else:
            logger.error(
                "백그라운드 채점 결과 저장 실패",
                result_id=str(grading_result.result_id),
            )
    except Exception as e:
        logger.error(
            "백그라운드 채점 결과 저장 중 예외",
            result_id=str(grading_result.result_id),
            error=str(e),
        )


def setup_grading_routes(app, settings: Settings):
    """
    채점 시스템 라우터를 FastAPI 앱에 등록

    Args:
        app: FastAPI 애플리케이션 인스턴스
        settings: 애플리케이션 설정
    """
    # 채점 라우터 등록
    app.include_router(router)

    logger.info(
        "채점 시스템 라우터 등록 완료",
        database_enabled=settings.database_enabled,
        max_concurrent_subjective=settings.grading_max_concurrent_subjective,
        ai_model=settings.grading_ai_model,
    )
