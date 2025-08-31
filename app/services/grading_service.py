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
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import structlog
from langchain_google_genai import ChatGoogleGenerativeAI

from app.models.grading import (
    QuestionData,
    StudentAnswer,
    QuestionGradingResult,
    ExamGradingResult,
    GradingProgress,
    GradingMetadata,
    GradingMethod,
    GradingStatus,
    QuestionType
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
        self,
        question: QuestionData,
        answer: StudentAnswer
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
            raise ValueError(f"객관식 문제의 정답이 설정되지 않음: {question.question_id}")
        
        # 학생 답안 검증
        if answer.selected_choice is None:
            logger.warning(
                "학생이 답안을 선택하지 않음",
                question_id=str(question.question_id),
                answer_id=str(answer.answer_id)
            )
            # 답안 미선택시 0점 처리
            return QuestionGradingResult(
                question_id=question.question_id,
                answer_id=answer.answer_id,
                is_correct=False,
                score=0,
                max_score=question.points,
                grading_method=self.grading_method,
                confidence_score=Decimal("1.00"),  # 자동 채점은 100% 확신
                grading_comment="답안을 선택하지 않아 0점 처리"
            )
        
        # 정답 여부 판정
        is_correct = answer.selected_choice == question.correct_choice
        score = question.points if is_correct else 0
        
        # 채점 코멘트 생성
        correct_choice_text = self._get_choice_text(question.choices, question.correct_choice)
        selected_choice_text = self._get_choice_text(question.choices, answer.selected_choice)
        
        if is_correct:
            comment = f"정답: {correct_choice_text} (선택: {selected_choice_text})"
        else:
            comment = f"오답: 정답은 {correct_choice_text}이지만 {selected_choice_text}을 선택"
        
        result = QuestionGradingResult(
            question_id=question.question_id,
            answer_id=answer.answer_id,
            is_correct=is_correct,
            score=score,
            max_score=question.points,
            grading_method=self.grading_method,
            confidence_score=Decimal("1.00"),  # 자동 채점은 100% 확신
            grading_comment=comment
        )
        
        logger.info(
            "객관식 문제 채점 완료",
            question_id=str(question.question_id),
            answer_id=str(answer.answer_id),
            is_correct=is_correct,
            score=score,
            max_score=question.points
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
        self,
        question_answer_pairs: list[tuple[QuestionData, StudentAnswer]]
    ) -> list[QuestionGradingResult]:
        """
        객관식 문제 배치 채점
        
        Args:
            question_answer_pairs: (문제, 답안) 쌍 목록
            
        Returns:
            list[QuestionGradingResult]: 채점 결과 목록
        """
        results = []
        
        for question, answer in question_answer_pairs:
            try:
                # 객관식 문제만 처리
                if question.question_type == QuestionType.MULTIPLE_CHOICE:
                    result = self.grade_question(question, answer)
                    results.append(result)
                else:
                    logger.warning(
                        "객관식이 아닌 문제는 건너뜀",
                        question_id=str(question.question_id),
                        question_type=question.question_type
                    )
            except Exception as e:
                logger.error(
                    "객관식 문제 채점 실패",
                    question_id=str(question.question_id),
                    answer_id=str(answer.answer_id),
                    error=str(e)
                )
                # 채점 실패한 문제는 결과에서 제외
                continue
        
        logger.info(
            "객관식 배치 채점 완료",
            total_pairs=len(question_answer_pairs),
            successful_gradings=len(results)
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
        model_name: str = "gemini-2.0-flash-exp",
        max_concurrent: int = 3
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
        self._gemini_model: ChatGoogleGenerativeAI | None = None
    
    def _get_gemini_model(self) -> ChatGoogleGenerativeAI:
        """Gemini 모델 인스턴스 생성/재사용"""
        if self._gemini_model is None:
            self._gemini_model = ChatGoogleGenerativeAI(
                model=self.model_name,
                google_api_key=self.gemini_api_key,
                temperature=0.1,
                max_output_tokens=4000,
            )
        return self._gemini_model
    
    async def grade_question(
        self,
        question: QuestionData,
        answer: StudentAnswer
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
            raise ValueError(f"주관식 문제의 정답이 설정되지 않음: {question.question_id}")
        
        # 학생 답안 검증
        if not answer.answer_text and not answer.ai_solution_process:
            logger.warning(
                "학생 답안이 없음",
                question_id=str(question.question_id),
                answer_id=str(answer.answer_id)
            )
            # 답안 없음 시 0점 처리
            return QuestionGradingResult(
                question_id=question.question_id,
                answer_id=answer.answer_id,
                is_correct=False,
                score=0,
                max_score=question.points,
                grading_method=self.grading_method,
                confidence_score=Decimal("1.00"),
                grading_comment="답안을 작성하지 않아 0점 처리"
            )
        
        async with self.semaphore:  # 동시성 제어
            try:
                # AI 채점 수행
                grading_result = await self._call_gemini_grading(question, answer)
                
                logger.info(
                    "주관식 문제 AI 채점 완료",
                    question_id=str(question.question_id),
                    answer_id=str(answer.answer_id),
                    score=grading_result.score,
                    confidence=float(grading_result.confidence_score or 0)
                )
                
                return grading_result
                
            except Exception as e:
                logger.error(
                    "주관식 문제 AI 채점 실패",
                    question_id=str(question.question_id),
                    answer_id=str(answer.answer_id),
                    error=str(e)
                )
                # AI 채점 실패 시 수동 채점 필요로 표시
                return QuestionGradingResult(
                    question_id=question.question_id,
                    answer_id=answer.answer_id,
                    is_correct=None,  # 미정
                    score=None,       # 미정
                    max_score=question.points,
                    grading_method=GradingMethod.MANUAL,  # 수동 채점 필요
                    confidence_score=None,
                    grading_comment=f"AI 채점 실패 - 수동 채점 필요: {str(e)}"
                )
    
    async def _call_gemini_grading(
        self,
        question: QuestionData,
        answer: StudentAnswer
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
        student_answer_text = answer.ai_solution_process or answer.answer_text or ""
        
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
                lines = response_text.split('\n')
                json_lines = []
                in_json = False
                for line in lines:
                    if line.strip().startswith("```"):
                        in_json = not in_json
                        continue
                    if in_json:
                        json_lines.append(line)
                response_text = '\n'.join(json_lines)
            
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
                answer_id=answer.answer_id,
                is_correct=is_correct,
                score=score,
                max_score=question.points,
                grading_method=self.grading_method,
                confidence_score=Decimal(str(confidence)),
                grading_comment=comment
            )
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(
                "AI 채점 응답 파싱 실패",
                question_id=str(question.question_id),
                response_text=response_text[:200],
                error=str(e)
            )
            # 파싱 실패시 수동 채점 필요로 처리
            raise ValueError(f"AI 채점 응답 파싱 실패: {str(e)}")
    
    async def batch_grade_questions(
        self,
        question_answer_pairs: list[tuple[QuestionData, StudentAnswer]]
    ) -> list[QuestionGradingResult]:
        """
        주관식 문제 배치 AI 채점
        
        Args:
            question_answer_pairs: (문제, 답안) 쌍 목록
            
        Returns:
            list[QuestionGradingResult]: 채점 결과 목록
        """
        results = []
        
        # 주관식 문제만 필터링
        subjective_pairs = [
            (q, a) for q, a in question_answer_pairs
            if q.question_type == QuestionType.SUBJECTIVE
        ]
        
        if not subjective_pairs:
            logger.info("주관식 문제가 없어서 배치 채점 건너뜀")
            return results
        
        # 비동기 채점 태스크 생성
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
            total_pairs=len(subjective_pairs),
            successful_gradings=len(results)
        )
        
        return results


class GradingOrchestrator:
    """
    전체 채점 프로세스 관리자
    
    기능:
    - 객관식/주관식 채점 통합 관리
    - 제출물별 전체 채점 수행
    - 진행률 추적 및 결과 집계
    - 배치 채점 처리
    """
    
    def __init__(
        self,
        gemini_api_key: str,
        max_concurrent_subjective: int = 3
    ):
        """
        채점 관리자 초기화
        
        Args:
            gemini_api_key: Gemini API 키
            max_concurrent_subjective: 주관식 최대 동시 처리 수
        """
        self.multiple_choice_grader = MultipleChoiceGrader()
        self.subjective_grader = SubjectiveGrader(
            gemini_api_key=gemini_api_key,
            max_concurrent=max_concurrent_subjective
        )
        
        # 진행 상태 추적
        self._progress_tracker: dict[UUID, GradingProgress] = {}
    
    async def grade_submission(
        self,
        submission_id: UUID,
        questions: list[QuestionData],
        answers: list[StudentAnswer],
        exam_sheet_id: UUID
    ) -> ExamGradingResult:
        """
        단일 제출물 전체 채점
        
        Args:
            submission_id: 제출 ID
            questions: 문제 목록
            answers: 답안 목록
            exam_sheet_id: 시험지 ID
            
        Returns:
            ExamGradingResult: 전체 채점 결과
        """
        start_time = time.time()
        
        # 진행 상태 초기화
        progress = GradingProgress(
            submission_id=submission_id,
            total_questions=len(questions)
        )
        self._progress_tracker[submission_id] = progress
        
        logger.info(
            "제출물 채점 시작",
            submission_id=str(submission_id),
            total_questions=len(questions),
            objective_count=sum(1 for q in questions if q.question_type == QuestionType.MULTIPLE_CHOICE),
            subjective_count=sum(1 for q in questions if q.question_type == QuestionType.SUBJECTIVE)
        )
        
        # 문제-답안 매칭
        question_answer_pairs = self._match_questions_and_answers(questions, answers)
        
        # 객관식과 주관식 분리
        mc_pairs = [(q, a) for q, a in question_answer_pairs if q.question_type == QuestionType.MULTIPLE_CHOICE]
        subj_pairs = [(q, a) for q, a in question_answer_pairs if q.question_type == QuestionType.SUBJECTIVE]
        
        # 병렬 채점 실행
        gather_results = await asyncio.gather(
            self.multiple_choice_grader.batch_grade_questions(mc_pairs),
            self.subjective_grader.batch_grade_questions(subj_pairs),
            return_exceptions=True
        )
        
        # 예외 처리 및 타입 보장
        mc_results: list[QuestionGradingResult] = []
        subj_results: list[QuestionGradingResult] = []
        
        if isinstance(gather_results[0], Exception):
            logger.error("객관식 채점 실패", error=str(gather_results[0]))
        elif isinstance(gather_results[0], list):
            mc_results = gather_results[0]
            
        if isinstance(gather_results[1], Exception):
            logger.error("주관식 채점 실패", error=str(gather_results[1]))
        elif isinstance(gather_results[1], list):
            subj_results = gather_results[1]
        
        # 결과 통합
        all_results = mc_results + subj_results
        
        # 통계 계산
        total_score = sum(r.score or 0 for r in all_results)
        max_total_score = sum(r.max_score for r in all_results)
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        # 메타데이터 생성
        metadata = GradingMetadata(
            total_questions=len(questions),
            multiple_choice_count=len(mc_pairs),
            subjective_count=len(subj_pairs),
            processing_time_ms=processing_time_ms
        )
        
        # 채점 결과 생성
        result = ExamGradingResult(
            submission_id=submission_id,
            exam_sheet_id=exam_sheet_id,
            status=GradingStatus.COMPLETED,
            total_score=total_score,
            max_total_score=max_total_score,
            question_results=all_results,
            metadata=metadata,
            grading_comment=f"자동/AI 보조 채점 완료 - 총 {len(all_results)}문제 채점",
            graded_at=datetime.now()
        )
        
        # 진행 추적 정리
        del self._progress_tracker[submission_id]
        
        logger.info(
            "제출물 채점 완료",
            submission_id=str(submission_id),
            total_score=total_score,
            max_total_score=max_total_score,
            processing_time_ms=processing_time_ms,
            successful_questions=len(all_results)
        )
        
        return result
    
    def _match_questions_and_answers(
        self,
        questions: list[QuestionData],
        answers: list[StudentAnswer]
    ) -> list[tuple[QuestionData, StudentAnswer]]:
        """
        문제와 답안을 question_id로 매칭
        
        Args:
            questions: 문제 목록
            answers: 답안 목록
            
        Returns:
            list[tuple[QuestionData, StudentAnswer]]: 매칭된 (문제, 답안) 쌍 목록
        """
        # 답안을 question_id로 인덱싱
        answer_dict = {answer.question_id: answer for answer in answers}
        
        # 문제별로 해당 답안 찾기
        matched_pairs = []
        for question in questions:
            answer = answer_dict.get(question.question_id)
            if answer:
                matched_pairs.append((question, answer))
            else:
                logger.warning(
                    "문제에 해당하는 답안이 없음",
                    question_id=str(question.question_id)
                )
        
        return matched_pairs
    
    def get_grading_progress(self, submission_id: UUID) -> GradingProgress | None:
        """채점 진행 상태 조회"""
        return self._progress_tracker.get(submission_id)
    
    def get_active_gradings(self) -> list[GradingProgress]:
        """활성 채점 목록 조회"""
        return list(self._progress_tracker.values())