"""
채점 서비스

시험 답안 자동/AI 보조 채점 처리 서비스

주요 기능:
- 객관식 자동 채점 (MultipleChoiceGrader)
- 주관식 AI 보조 채점 (SubjectiveGrader)
- 전체 채점 프로세스 관리 (GradingOrchestrator)
- 배치 채점 처리
"""

import asyncio
import time

from decimal import Decimal
from uuid import UUID, uuid4
import structlog
from langchain_google_vertexai import ChatVertexAI

from app.models.grading import (
    QuestionData,
    StudentAnswer,
    QuestionGradingResult,
    ExamGradingResult,

    GradingMetadata,
    GradingMethod,
    GradingStatus,
    QuestionType,
)

logger = structlog.get_logger("grading_service")


class MultipleChoiceGrader:
    """
    객관식 자동 채점 서비스

    기능:
    - 선택 답안과 정답 비교
    - 즉시 채점 (100% 정확도)
    - 배치 처리 지원
    """

    def __init__(self):
        """객관식 채점기 초기화"""
        self.grading_method = GradingMethod.AUTO

    def grade_question(
        self, question: QuestionData, answer: StudentAnswer
    ) -> QuestionGradingResult:
        """
        단일 객관식 문제 채점

        Args:
            question: 문제 정보
            answer: 학생 답안

        Returns:
            QuestionGradingResult: 채점 결과

        Raises:
            ValueError: 문제 유형이 객관식이 아닌 경우
            ValueError: 필수 데이터 누락 시
        """
        # 문제 유형 검증
        if question.question_type != QuestionType.MULTIPLE_CHOICE:
            raise ValueError(f"객관식 문제가 아닙니다: {question.question_type}")

        # 정답 정보 검증
        if question.correct_choice is None:
            raise ValueError(
                f"객관식 문제의 정답이 설정되지 않음: {question.question_id}"
            )

        # 학생 답안 검증
        if answer.selected_choice is None:
            logger.warning(
                "학생이 답안을 선택하지 않음",
                question_id=str(question.question_id),
                answer_id=str(answer.id),
            )
            # 답안 미선택시 0점 처리
            return QuestionGradingResult(
                question_id=question.question_id,
                answer_id=answer.student_answer_sheet_id,
                is_correct=False,
                score=0,
                max_score=question.points,
                grading_method=self.grading_method,
                confidence_score=Decimal("1.00"),  # 자동 채점은 100% 확신
                scoring_comment="답안을 선택하지 않아 0점 처리",
            )

        # 정답 여부 판정
        is_correct = answer.selected_choice == question.correct_choice
        score = question.points if is_correct else 0

        # 채점 코멘트 생성
        correct_choice_text = self._get_choice_text(
            question.choices, question.correct_choice
        )
        selected_choice_text = self._get_choice_text(
            question.choices, answer.selected_choice
        )

        if is_correct:
            comment = f"정답: {correct_choice_text} (선택: {selected_choice_text})"
        else:
            comment = f"오답: 정답은 {correct_choice_text}이지만 {selected_choice_text}을 선택"

        result = QuestionGradingResult(
            question_id=question.question_id,
            answer_id=answer.student_answer_sheet_id,
            is_correct=is_correct,
            score=score,
            max_score=question.points,
            grading_method=self.grading_method,
            confidence_score=Decimal("1.00"),  # 자동 채점은 100% 확신
            scoring_comment=comment,
        )

        logger.info(
            "객관식 문제 채점 완료",
            question_id=str(question.question_id),
            answer_id=str(answer.id),
            is_correct=is_correct,
            score=score,
            max_score=question.points,
        )

        return result

    def _get_choice_text(self, choices: dict | None, choice_num: int) -> str:
        """
        선택지 번호를 텍스트로 변환

        Args:
            choices: 선택지 딕셔너리
            choice_num: 선택지 번호

        Returns:
            str: 선택지 텍스트 (예: "1번", "A")
        """
        if choices is None:
            return f"{choice_num}번"

        # choices가 {1: "A", 2: "B", 3: "C", 4: "D"} 형태라고 가정
        choice_text = choices.get(str(choice_num), choices.get(choice_num))
        if choice_text:
            return f"{choice_num}번({choice_text})"
        return f"{choice_num}번"

    async def batch_grade_questions(
        self, question_answer_pairs: list[tuple[QuestionData, StudentAnswer | None]]
    ) -> list[QuestionGradingResult]:
        """
        객관식 문제 배치 채점
        
        답안이 None인 경우 0점 처리

        Args:
            question_answer_pairs: (문제, 답안) 쌍 목록 (답안은 None일 수 있음)

        Returns:
            list[QuestionGradingResult]: 채점 결과 목록
        """
        results = []

        for question, answer in question_answer_pairs:
            try:
                # 객관식 문제만 처리
                if question.question_type == QuestionType.MULTIPLE_CHOICE:
                    if answer is None:
                        # 답안이 없는 경우 0점 처리
                        result = QuestionGradingResult(
                            question_id=question.question_id,
                            answer_id=None,  # 답안 ID 없음
                            is_correct=False,
                            score=0,
                            max_score=question.points,
                            grading_method=self.grading_method,
                            confidence_score=Decimal("1.00"),
                            scoring_comment="답안 미제출로 0점 처리",
                        )
                        results.append(result)
                        logger.info(
                            "객관식 문제 미답변 처리",
                            question_id=str(question.question_id),
                            score=0,
                            max_score=question.points,
                        )
                    else:
                        result = self.grade_question(question, answer)
                        results.append(result)
                else:
                    logger.warning(
                        "객관식이 아닌 문제는 건너뜀",
                        question_id=str(question.question_id),
                        question_type=question.question_type,
                    )
            except Exception as e:
                logger.error(
                    "객관식 문제 채점 실패",
                    question_id=str(question.question_id),
                    answer_id=str(answer.id) if answer else None,
                    error=str(e),
                )
                # 채점 실패한 문제는 결과에서 제외
                continue

        logger.info(
            "객관식 배치 채점 완료",
            total_pairs=len(question_answer_pairs),
            successful_gradings=len(results),
        )

        return results


class SubjectiveGrader:
    """
    주관식 AI 보조 채점 서비스

    기능:
    - Gemini AI를 활용한 주관식 답안 채점
    - 정답과의 유사도 분석
    - 신뢰도 점수 제공
    - 채점 근거 및 피드백 생성
    """

    def __init__(
        self,
        gemini_api_key: str,
        model_name: str = "gemini-2.5-pro",
        max_concurrent: int = 3,
    ):
        """
        주관식 채점기 초기화

        Args:
            gemini_api_key: Gemini API 키
            model_name: 사용할 Gemini 모델명
            max_concurrent: 최대 동시 처리 수
        """
        self.gemini_api_key = gemini_api_key
        self.model_name = model_name
        self.max_concurrent = max_concurrent
        self.grading_method = GradingMethod.AI_ASSISTED

        # 동시성 제어
        self.semaphore = asyncio.Semaphore(max_concurrent)

        # Gemini 모델 (재사용)
        self._gemini_model: ChatVertexAI | None = None

    def _get_gemini_model(self) -> ChatVertexAI:
        """Gemini 모델 인스턴스 생성/재사용"""
        if self._gemini_model is None:
            from app.config.settings import get_settings
            settings = get_settings()
            self._gemini_model = ChatVertexAI(
                model=self.model_name,
                project=settings.gcp_project_id,
                location=settings.gcp_location,
                temperature=0.1,
                max_output_tokens=4000,
            )
        return self._gemini_model

    async def grade_question(
        self, question: QuestionData, answer: StudentAnswer
    ) -> QuestionGradingResult:
        """
        단일 주관식 문제 AI 채점

        Args:
            question: 문제 정보
            answer: 학생 답안

        Returns:
            QuestionGradingResult: 채점 결과

        Raises:
            ValueError: 문제 유형이 주관식이 아닌 경우
            ValueError: 필수 데이터 누락 시
        """
        # 문제 유형 검증
        if question.question_type != QuestionType.SUBJECTIVE:
            raise ValueError(f"주관식 문제가 아닙니다: {question.question_type}")

        # 정답 정보 검증
        if not question.answer_text:
            raise ValueError(
                f"주관식 문제의 정답이 설정되지 않음: {question.question_id}"
            )

        # 학생 답안 검증
        if not answer.answer_text:
            logger.warning(
                "학생 답안이 없음",
                question_id=str(question.question_id),
                answer_id=str(answer.id),
            )
            # 답안 없음 시 0점 처리
            return QuestionGradingResult(
                question_id=question.question_id,
                answer_id=answer.student_answer_sheet_id,
                is_correct=False,
                score=0,
                max_score=question.points,
                grading_method=self.grading_method,
                confidence_score=Decimal("1.00"),
                scoring_comment="답안을 작성하지 않아 0점 처리",
            )

        async with self.semaphore:  # 동시성 제어
            try:
                # AI 채점 수행
                grading_result = await self._call_gemini_grading(question, answer)

                logger.info(
                    "주관식 문제 AI 채점 완료",
                    question_id=str(question.question_id),
                    answer_id=str(answer.id),
                    score=grading_result.score,
                    confidence=float(grading_result.confidence_score or 0),
                )

                return grading_result

            except Exception as e:
                logger.error(
                    "주관식 문제 AI 채점 실패",
                    question_id=str(question.question_id),
                    answer_id=str(answer.id),
                    error=str(e),
                )
                # AI 채점 실패 시 수동 채점 필요로 표시
                return QuestionGradingResult(
                    question_id=question.question_id,
                    answer_id=answer.student_answer_sheet_id,
                    is_correct=None,  # 미정
                    score=None,  # 미정
                    max_score=question.points,
                    grading_method=GradingMethod.MANUAL,  # 수동 채점 필요
                    confidence_score=None,
                    scoring_comment=f"AI 채점 실패 - 수동 채점 필요: {str(e)}",
                )

    async def _call_gemini_grading(
        self, question: QuestionData, answer: StudentAnswer
    ) -> QuestionGradingResult:
        """
        Gemini AI를 이용한 주관식 채점 수행

        Args:
            question: 문제 정보
            answer: 학생 답안

        Returns:
            QuestionGradingResult: 채점 결과
        """
        import json
        from langchain_core.messages import HumanMessage

        # 학생 답안 텍스트 추출 (OCR 결과 우선 사용)
        student_answer_text = answer.answer_text or ""

        # AI 채점 프롬프트 구성
        prompt = f"""
한국어 수학 시험 주관식 답안을 채점해주세요.

**문제 정보:**
문제: {question.question_text}
정답: {question.answer_text}
배점: {question.points}점
난이도: {question.difficulty}
채점 기준: {question.scoring_rubric or "표준 채점 기준 적용"}

**학생 답안:**
{student_answer_text}

**채점 요구사항:**
1. 수학적 정확성을 우선적으로 평가
2. 풀이 과정의 논리적 타당성 검토
3. 부분 점수 적절히 부여
4. 한국어 수학 교육과정 기준 적용

다음 JSON 형식으로 응답해주세요:
{{
    "is_correct": true/false,
    "score": 획득점수(정수),
    "confidence_score": 신뢰도점수(0.00-1.00),
    "grading_comment": "구체적인 채점 근거 및 피드백"
}}
"""

        # Gemini 모델로 채점 요청
        model = self._get_gemini_model()
        message = HumanMessage(content=prompt)

        response = await model.ainvoke([message])
        response_text = str(response.content).strip()

        # JSON 파싱
        try:
            # 마크다운 코드 블록 제거
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

            grading_data = json.loads(response_text)

            # 결과 검증 및 정규화
            is_correct = bool(grading_data.get("is_correct", False))
            score = int(grading_data.get("score", 0))
            confidence = float(grading_data.get("confidence_score", 0.0))
            comment = str(grading_data.get("grading_comment", "AI 채점 완료"))

            # 점수 범위 검증
            score = max(0, min(score, question.points))
            confidence = max(0.0, min(confidence, 1.0))

            return QuestionGradingResult(
                question_id=question.question_id,
                answer_id=answer.student_answer_sheet_id,
                is_correct=is_correct,
                score=score,
                max_score=question.points,
                grading_method=self.grading_method,
                confidence_score=Decimal(str(confidence)),
                scoring_comment=comment,
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(
                "AI 채점 응답 파싱 실패",
                question_id=str(question.question_id),
                response_text=response_text[:200],
                error=str(e),
            )
            # 파싱 실패시 수동 채점 필요로 처리
            raise ValueError(f"AI 채점 응답 파싱 실패: {str(e)}")

    async def batch_grade_questions(
        self, question_answer_pairs: list[tuple[QuestionData, StudentAnswer | None]]
    ) -> list[QuestionGradingResult]:
        """
        주관식 문제 배치 AI 채점
        
        답안이 None인 경우 0점 처리

        Args:
            question_answer_pairs: (문제, 답안) 쌍 목록 (답안은 None일 수 있음)

        Returns:
            list[QuestionGradingResult]: 채점 결과 목록
        """
        results = []

        # 주관식 문제만 필터링
        subjective_pairs = []
        for q, a in question_answer_pairs:
            if q.question_type == QuestionType.SUBJECTIVE:
                if a is None:
                    # 답안이 없는 경우 즉시 0점 처리
                    result = QuestionGradingResult(
                        question_id=q.question_id,
                        answer_id=None,  # 답안 ID 없음
                        is_correct=False,
                        score=0,
                        max_score=q.points,
                        grading_method=GradingMethod.AI_ASSISTED,
                        confidence_score=Decimal("1.00"),
                        scoring_comment="답안 미제출로 0점 처리",
                    )
                    results.append(result)
                    logger.info(
                        "주관식 문제 미답변 처리",
                        question_id=str(q.question_id),
                        score=0,
                        max_score=q.points,
                    )
                else:
                    subjective_pairs.append((q, a))

        if not subjective_pairs:
            logger.info("채점할 주관식 답안이 없어서 배치 채점 건너뜀")
            return results

        # 비동기 채점 태스크 생성 (답안이 있는 경우만)
        tasks = [
            self.grade_question(question, answer)
            for question, answer in subjective_pairs
        ]

        # 병렬 처리 실행
        completed_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 결과 수집 (예외는 로그 출력 후 제외)
        for result in completed_results:
            if isinstance(result, Exception):
                logger.error("주관식 배치 채점 중 예외 발생", error=str(result))
                continue
            results.append(result)

        logger.info(
            "주관식 배치 AI 채점 완료",
            total_pairs=len(question_answer_pairs),
            subjective_with_answers=len(subjective_pairs),
            successful_gradings=len(results),
        )

        return results


class GradingService:
    """
    통합 채점 서비스 (이전 GradingOrchestrator)
    
    객관식 자동 채점과 주관식 AI 보조 채점을 통합 관리:
    - 문제 유형별 적절한 채점기 선택
    - 병렬 채점 처리 및 성능 최적화
    - 채점 결과 검증 및 품질 관리
    - 진행 상황 모니터링 및 보고
    """
    
    def __init__(
        self,
        gemini_api_key: str,
        max_concurrent_subjective: int = 3,
    ):
        """
        채점 서비스 초기화
        
        Args:
            gemini_api_key: Gemini API 키
            max_concurrent_subjective: 주관식 동시 채점 최대 수
        """
        from app.config.settings import get_settings
        
        self.gemini_api_key = gemini_api_key
        self.max_concurrent_subjective = max_concurrent_subjective
        self.settings = get_settings()
        
        # 채점기 인스턴스들
        self.mc_grader = MultipleChoiceGrader()
        self.subjective_grader = SubjectiveGrader(
            gemini_api_key=gemini_api_key,
            max_concurrent=max_concurrent_subjective
        )
        
        logger.info(
            "채점 서비스 초기화 완료",
            max_concurrent_subjective=max_concurrent_subjective
        )
    
    async def grade_exam(
        self, 
        questions: list[QuestionData], 
        student_answers: list[StudentAnswer]
    ) -> ExamGradingResult:
        """
        전체 시험 채점 수행
        
        Args:
            questions: 문제 목록
            student_answers: 학생 답안 목록
            
        Returns:
            ExamGradingResult: 통합 채점 결과
        """
        if not questions:
            raise ValueError("채점할 문제가 없습니다")
        if not student_answers:
            raise ValueError("채점할 답안이 없습니다")
        
        start_time = time.time()
        
        # 문제-답안 매칭
        question_answer_pairs = self._match_questions_with_answers(questions, student_answers)
        
        # 문제 유형별 그룹핑
        mc_pairs, subjective_pairs = self._group_by_question_type(question_answer_pairs)
        
        logger.info(
            "시험 채점 시작",
            total_questions=len(questions),
            multiple_choice=len(mc_pairs),
            subjective=len(subjective_pairs)
        )
        
        # 병렬 채점 수행
        async def empty_task():
            return []
            
        mc_task = self.mc_grader.batch_grade_questions(mc_pairs) if mc_pairs else empty_task()
        subjective_task = self.subjective_grader.batch_grade_questions(subjective_pairs) if subjective_pairs else empty_task()
        
        mc_results, subjective_results = await asyncio.gather(
            mc_task, 
            subjective_task, 
            return_exceptions=True
        )
        
        # 예외 처리 및 결과 타입 보장
        final_mc_results: list[QuestionGradingResult] = []
        final_subjective_results: list[QuestionGradingResult] = []
        
        if isinstance(mc_results, Exception):
            logger.error("객관식 채점 실패", error=str(mc_results))
            final_mc_results = []
        else:
            # 타입 체커를 위한 명시적 캐스팅
            final_mc_results = mc_results  # type: ignore[assignment]
            
        if isinstance(subjective_results, Exception):
            logger.error("주관식 채점 실패", error=str(subjective_results))
            final_subjective_results = []
        else:
            # 타입 체커를 위한 명시적 캐스팅
            final_subjective_results = subjective_results  # type: ignore[assignment]
        
        # 결과 통합
        all_results = final_mc_results + final_subjective_results
        
        # 전체 채점 결과 생성
        total_score = sum(r.score for r in all_results if r.score is not None)
        max_possible_score = sum(q.points for q in questions)
        
        processing_time = time.time() - start_time
        
        exam_result = ExamGradingResult(
            submission_id=uuid4(),  # 임시 UUID, 실제로는 매개변수로 받아야 함
            exam_sheet_id=uuid4(),  # 임시 UUID, 실제로는 매개변수로 받아야 함
            question_results=all_results,
            total_score=total_score,
            max_total_score=max_possible_score,
            status=GradingStatus.COMPLETED,
            metadata=GradingMetadata(
                processing_time_ms=int(processing_time * 1000),
                total_questions=len(questions),
                multiple_choice_count=len(mc_pairs),
                subjective_count=len(subjective_pairs),
                ai_model_version=self.settings.grading_ai_model
            )
        )
        
        logger.info(
            "시험 채점 완료",
            submission_id=str(exam_result.submission_id),
            total_score=total_score,
            max_score=max_possible_score,
            processing_time_seconds=round(processing_time, 2)
        )
        
        return exam_result
    
    def _match_questions_with_answers(
        self, 
        questions: list[QuestionData], 
        student_answers: list[StudentAnswer]
    ) -> list[tuple[QuestionData, StudentAnswer | None]]:
        """
        문제와 답안 매칭
        
        답안이 없는 문제도 포함하여 모든 문제를 반환
        누락된 답안은 None으로 표시
        """
        answer_map = {a.question_id: a for a in student_answers}
        pairs = []
        
        for question in questions:
            if question.question_id in answer_map:
                pairs.append((question, answer_map[question.question_id]))
            else:
                # 답안이 없는 문제도 포함 (None으로 표시)
                logger.warning(
                    "답안이 없는 문제 발견",
                    question_id=str(question.question_id)
                )
                pairs.append((question, None))
        
        return pairs
    
    def _group_by_question_type(
        self, 
        pairs: list[tuple[QuestionData, StudentAnswer | None]]
    ) -> tuple[list[tuple[QuestionData, StudentAnswer | None]], list[tuple[QuestionData, StudentAnswer | None]]]:
        """
        문제 유형별 그룹핑
        
        답안이 None인 경우도 적절히 처리
        """
        mc_pairs = []
        subjective_pairs = []
        
        for question, answer in pairs:
            if question.question_type == QuestionType.MULTIPLE_CHOICE:
                mc_pairs.append((question, answer))
            elif question.question_type == QuestionType.SUBJECTIVE:
                subjective_pairs.append((question, answer))
            else:
                logger.warning(
                    "알 수 없는 문제 유형",
                    question_id=str(question.question_id),
                    question_type=question.question_type
                )
        
        return mc_pairs, subjective_pairs

    
    def get_active_gradings(self) -> list[dict]:
        """
        현재 활성 채점 작업 목록 조회
        
        Returns:
            list[dict]: 활성 채점 작업 정보 목록
        """
        # TODO: 실제 활성 작업 추적 구현
        # 현재는 빈 목록 반환 (추후 개선 필요)
        return []
    
    async def grade_submission(
        self,
        submission_id: UUID,
        questions: list[QuestionData],
        answers: list[StudentAnswer],
        exam_sheet_id: UUID
    ) -> ExamGradingResult:
        """
        이전 GradingOrchestrator와의 호환성을 위한 래퍼 메서드
        
        Args:
            submission_id: 제출 ID (메타데이터용)
            questions: 문제 목록
            answers: 학생 답안 목록
            exam_sheet_id: 시험지 ID (메타데이터용)
            
        Returns:
            ExamGradingResult: 채점 결과
        """
        logger.info(
            "호환성 메서드를 통한 채점 수행",
            submission_id=str(submission_id),
            exam_sheet_id=str(exam_sheet_id)
        )
        
        # 새로운 grade_exam 메서드 사용
        result = await self.grade_exam(questions, answers)
        
        # 호환성을 위해 전달받은 submission_id와 exam_sheet_id 사용
        result.submission_id = submission_id
        result.exam_sheet_id = exam_sheet_id
        
        # 결과에 추가 정보 로깅 (메타데이터는 이미 설정됨)
        logger.debug(
            "채점 결과 메타데이터",
            submission_id=str(submission_id),
            exam_sheet_id=str(exam_sheet_id),
            processing_time=result.metadata.processing_time_ms if result.metadata else None
        )
        
        return result
