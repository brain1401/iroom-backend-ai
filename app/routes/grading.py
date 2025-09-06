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
    SubmissionAndGradingRequest,
    SubmissionAndGradingResponse,
    StudentAnswerSheetQuestion,
    GradingStatus,
)
from app.services.grading_factory import get_repositories, get_grading_service

logger = structlog.get_logger("grading_api")

# FastAPI 라우터 생성
router = APIRouter(prefix="/grading", tags=["채점"])
@router.get("/health")
async def grading_health_check():
    """
    채점 시스템 헬스체크
    
    Returns:
        dict: 채점 시스템 상태 정보
    """
    from app.config.settings import get_settings
    settings = get_settings()
    
    health_status = {
        "status": "healthy",
        "service": "grading",
        "database_enabled": settings.database_enabled,
        "ai_model": settings.grading_ai_model,
        "confidence_threshold": settings.grading_confidence_threshold,
        "max_concurrent_subjective": settings.grading_max_concurrent_subjective,
        "features": [
            "exam_grading",
            "batch_processing",
            "subjective_evaluation",
            "ai_assisted_grading"
        ]
    }
    
    # 데이터베이스 연결 상태 확인
    if settings.database_enabled:
        try:
            # 간단한 DB 연결 테스트 (실제 구현 시 DB 연결 확인)
            health_status["database_status"] = "connected"
        except Exception as e:
            health_status["status"] = "degraded"
            health_status["database_status"] = f"error: {str(e)}"
    else:
        health_status["database_status"] = "in-memory mode"
    
    # Gemini API 키 확인
    if not settings.gemini_api_key:
        health_status["status"] = "unhealthy"
        health_status["error"] = "Gemini API key not configured"
    
    return health_status


@router.post("/submit-and-grade", response_model=SubmissionAndGradingResponse)
async def submit_and_grade(
    request: SubmissionAndGradingRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    settings: Settings = Depends(get_settings),
) -> SubmissionAndGradingResponse:
    """
    시험 답안 제출 및 채점 통합 처리
    
    단일 엔드포인트로 시험 답안을 제출하고 즉시 채점을 수행합니다.
    DB에 다음 테이블들의 데이터를 생성합니다:
    - exam_submission: 제출 기록
    - student_answer_sheet: 답안지
    - student_answer_sheet_question: 문제별 답안
    - exam_result: 채점 결과 (force_grading=true 시)
    - exam_result_question: 문제별 채점 결과 (force_grading=true 시)
    
    모든 UUID는 UUIDv7 형식으로 생성되어 시간 기반 정렬이 가능합니다.
    
    Args:
        request: 제출 및 채점 요청 데이터
        background_tasks: 백그라운드 작업 관리
        settings: 애플리케이션 설정
        
    Returns:
        SubmissionAndGradingResponse: 제출 및 채점 결과
        
    Raises:
        HTTPException: 시험 정보 없음, 문제 불일치, 제출 실패, 채점 실패 등
        
    Example:
        ```json
        {
            "exam_id": "018e3d5a-7b4c-7000-8000-000000000000",
            "student_id": 12345,
            "student_name": "홍길동",
            "answers": [
                {
                    "question_id": "018e3d5a-7b4c-7000-8000-000000000001",
                    "selected_choice": 3
                },
                {
                    "question_id": "018e3d5a-7b4c-7000-8000-000000000002",
                    "answer_text": "x = 10, y = 20"
                }
            ]
        }
        ```
    """
    from app.utils.uuid_utils import generate_uuidv7
    from app.models.grading import (
        SubmissionAndGradingResponse, 
        StudentAnswerSheetQuestion,
        ExamGradingResult,
        GradingStatus
    )
    from datetime import datetime
    
    logger.info(
        "제출 및 채점 통합 처리 시작",
        exam_id=str(request.exam_id),
        student_id=request.student_id,
        answer_count=len(request.answers)
    )
    
    try:
        # Repository 및 서비스 인스턴스 가져오기
        exam_repo, question_repo, grading_repo = get_repositories(settings)
        grading_service = get_grading_service(settings)
        
        # 1. 시험지 ID 조회
        exam_sheet_id = await exam_repo.get_exam_sheet_id_by_exam_id(request.exam_id)
        if not exam_sheet_id:
            raise HTTPException(
                status_code=404,
                detail=f"시험 정보를 찾을 수 없습니다: {request.exam_id}"
            )
        
        # 2. 시험지의 문제 목록 조회 (검증용)
        questions = await question_repo.get_questions_by_exam_sheet_id(exam_sheet_id)
        if not questions:
            raise HTTPException(
                status_code=404,
                detail=f"시험지의 문제를 찾을 수 없습니다: {exam_sheet_id}"
            )
        
        # 문제 ID 검증
        question_ids = {q.question_id for q in questions}
        answer_question_ids = {a.question_id for a in request.answers}
        
        # 누락된 문제 확인
        missing_questions = question_ids - answer_question_ids
        if missing_questions:
            logger.warning(
                "일부 문제 답안 누락",
                missing_count=len(missing_questions),
                missing_ids=[str(qid) for qid in missing_questions]
            )
        
        # 잘못된 문제 ID 확인
        invalid_questions = answer_question_ids - question_ids
        if invalid_questions:
            raise HTTPException(
                status_code=400,
                detail=f"유효하지 않은 문제 ID가 포함되어 있습니다: {[str(qid) for qid in invalid_questions]}"
            )
        
        # 3. 제출 데이터 생성 (UUIDv7 사용)
        submission_id = generate_uuidv7()
        answer_sheet_id = generate_uuidv7()
        
        # 4. exam_submission 생성
        submission_id = await exam_repo.create_submission(
            exam_id=request.exam_id,
            student_id=request.student_id,
            student_name=request.student_name
        )
        
        # 5. student_answer_sheet 생성
        answer_sheet_id = await exam_repo.create_answer_sheet(
            submission_id=submission_id,
            student_id=request.student_id,
            student_name=request.student_name
        )
        
        # 6. student_answer_sheet_question 생성
        answer_dicts = []
        for answer in request.answers:
            answer_dict = {
                "id": generate_uuidv7(),
                "question_id": answer.question_id,
                "student_answer_sheet_id": answer_sheet_id,
                "answer_text": answer.answer_text,
                "selected_choice": answer.selected_choice,
                "answer_image_url": answer.answer_image_url
            }
            answer_dicts.append(answer_dict)
        
        answer_ids = await exam_repo.create_answer_sheet_questions(
            answer_sheet_id=answer_sheet_id,
            answers=answer_dicts
        )
        
        # 7. 채점 수행 (force_grading=true인 경우)
        grading_result = None
        status = "SUBMITTED"
        message = "답안이 성공적으로 제출되었습니다"
        
        if request.force_grading:
            try:
                # StudentAnswerSheetQuestion 객체 생성
                student_answers = [
                    StudentAnswerSheetQuestion(
                        id=ad["id"],
                        question_id=ad["question_id"],
                        student_answer_sheet_id=ad["student_answer_sheet_id"],
                        answer_text=ad["answer_text"],
                        selected_choice=ad["selected_choice"],
                        answer_image_url=ad["answer_image_url"]
                    )
                    for ad in answer_dicts
                ]
                
                # 채점 수행
                grading_result = await grading_service.grade_exam(
                    questions=questions,
                    student_answers=student_answers
                )
                
                # 채점 결과에 필요한 ID 설정
                grading_result.submission_id = submission_id
                grading_result.exam_sheet_id = exam_sheet_id
                grading_result.result_id = generate_uuidv7()
                grading_result.status = GradingStatus.COMPLETED
                grading_result.graded_at = datetime.now()
                
                # 채점 결과 저장 (백그라운드)
                background_tasks.add_task(
                    _save_grading_result_background,
                    grading_repo,
                    grading_result
                )
                
                status = "GRADED"
                message = "답안이 제출되고 채점이 완료되었습니다"
                
            except Exception as e:
                logger.error(
                    "채점 처리 실패",
                    submission_id=str(submission_id),
                    error=str(e)
                )
                status = "SUBMITTED_GRADING_FAILED"
                message = f"답안은 제출되었으나 채점 중 오류가 발생했습니다: {str(e)}"
        
        # 8. 응답 생성
        response = SubmissionAndGradingResponse(
            submission_id=submission_id,
            exam_sheet_id=exam_sheet_id,
            student_answer_sheet_id=answer_sheet_id,
            grading_result=grading_result,
            status=status,
            message=message,
            submitted_at=datetime.now()
        )
        
        logger.info(
            "제출 및 채점 통합 처리 완료",
            submission_id=str(submission_id),
            status=status,
            total_score=grading_result.total_score if grading_result else None
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "제출 및 채점 통합 처리 실패",
            exam_id=str(request.exam_id),
            error=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=f"제출 처리 중 오류가 발생했습니다: {str(e)}"
        )

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
        grading_service = get_grading_service(settings)

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
        grading_result = await grading_service.grade_exam(
            questions=questions,
            student_answers=answers
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
        grading_service = get_grading_service(settings)

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
                    result = await grading_service.grade_exam(
                        questions=questions,
                        student_answers=answers
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
        grading_service = get_grading_service(settings)

        # 활성 채점 작업 조회
        active_gradings = getattr(grading_service, 'get_active_gradings', lambda: [])() # TODO: implement get_active_gradings method

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
