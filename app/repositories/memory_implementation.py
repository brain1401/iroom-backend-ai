"""
인메모리 Repository 구현체

DB 없이 메모리에서 데이터를 저장/조회하는 구현체들
테스트 환경이나 프로토타입에서 사용

주요 구현체:
- InMemoryExamRepository: 시험 제출/답안 메모리 저장
- InMemoryQuestionRepository: 문제 정보 메모리 저장
- InMemoryGradingRepository: 채점 결과 메모리 저장

특징:
- 프로세스 재시작시 데이터 소실
- 단일 인스턴스에서만 동작
- 동시성 제어 없음 (단순 구현)
"""

from datetime import datetime
from typing import Dict, List
from uuid import UUID
import structlog

from app.models.grading import (
    QuestionData,
    StudentAnswerSheet,
    StudentAnswerSheetQuestion,
    ExamGradingResult, 
    QuestionGradingResult,
    GradingStatus
)
from .interfaces import (
    ExamRepositoryInterface,
    QuestionRepositoryInterface,
    GradingRepositoryInterface
)

logger = structlog.get_logger("memory_repository")


class InMemoryStorage:
    """
    메모리 기반 데이터 저장소
    
    다양한 테이블 데이터를 메모리에 저장하는 싱글톤 클래스
    실제 DB 구조를 모방한 딕셔너리 기반 저장
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_storage()
        return cls._instance
    
    def _initialize_storage(self):
        """메모리 저장소 초기화"""
        # 시험 제출 데이터 (exam_submission 테이블 모방)
        self.submissions: Dict[UUID, dict] = {}
        
        # 학생 답안 데이터 (student_answer_sheet 테이블 모방)
        self.student_answer_sheets: Dict[UUID, StudentAnswerSheet] = {}
        
        # 학생 답안 상세 데이터 (student_answer_sheet_question 테이블 모방)
        self.student_answers: Dict[UUID, StudentAnswerSheetQuestion] = {}
        
        # 문제 데이터 (question 테이블 모방)
        self.questions: Dict[UUID, QuestionData] = {}
        
        # 시험지-문제 매핑 (exam_sheet_question 테이블 모방)
        self.exam_sheet_questions: Dict[UUID, List[UUID]] = {}  # exam_sheet_id -> [question_id]
        
        # 채점 결과 데이터 (exam_result 테이블 모방)
        self.grading_results: Dict[UUID, ExamGradingResult] = {}
        
        # 제출 ID -> 시험지 ID 매핑
        self.submission_to_exam_sheet: Dict[UUID, UUID] = {}
        
        # 제출 ID -> 답안 ID 목록 매핑
        self.submission_to_answers: Dict[UUID, List[UUID]] = {}
        
        # 시험 ID -> 시험지 ID 매핑 (exam 테이블 모방)
        self.exam_to_exam_sheet: Dict[UUID, UUID] = {}
        
        logger.info("인메모리 저장소 초기화 완료")
    
    def clear_all(self):
        """모든 데이터 초기화 (테스트용)"""
        self._initialize_storage()
        logger.info("인메모리 저장소 전체 초기화")
    
    def get_stats(self) -> dict:
        """저장소 통계 정보"""
        return {
            "submissions": len(self.submissions),
            "student_answers": len(self.student_answers),
            "questions": len(self.questions),
            "exam_sheet_questions": len(self.exam_sheet_questions),
            "grading_results": len(self.grading_results)
        }


# 전역 저장소 인스턴스
storage = InMemoryStorage()


class InMemoryExamRepository(ExamRepositoryInterface):
    """
    인메모리 기반 시험 제출 및 답안 데이터 접근 구현체
    
    메모리에 저장된 제출 정보와 답안을 관리
    테스트나 프로토타입 환경에서 사용
    """
    
    def __init__(self):
        """인메모리 시험 Repository 초기화"""
        self.storage = storage
    
    async def get_submission_by_id(self, submission_id: UUID) -> dict | None:
        """
        제출 ID로 시험 제출 정보 조회
        
        Args:
            submission_id: 제출 고유 ID
            
        Returns:
            dict | None: 제출 정보 또는 None
        """
        submission = self.storage.submissions.get(submission_id)
        
        if submission:
            logger.info("시험 제출 정보 조회 성공 (메모리)", submission_id=str(submission_id))
        else:
            logger.warning("시험 제출 정보 없음 (메모리)", submission_id=str(submission_id))
        
        return submission
    
    async def get_answers_by_submission_id(self, submission_id: UUID) -> list[StudentAnswerSheetQuestion]:
        """
        제출 ID로 해당 제출의 모든 답안 조회
        
        수정: student_answer_sheet 연결 후 student_answer_sheet_question 조회
        
        Args:
            submission_id: 제출 고유 ID
            
        Returns:
            list[StudentAnswerSheetQuestion]: 학생 답안 목록
        """
        # 1. submission_id로 answer_sheet 찾기
        answer_sheet = None
        for _, sheet in self.storage.student_answer_sheets.items():
            if sheet.submission_id == submission_id:
                answer_sheet = sheet
                break
        
        if not answer_sheet:
            logger.warning(
                "답안지 없음 (메모리)",
                submission_id=str(submission_id)
            )
            return []
        
        # 2. answer_sheet_id로 실제 답안들 찾기
        answers = []
        for _, answer in self.storage.student_answers.items():
            if answer.student_answer_sheet_id == answer_sheet.id:
                answers.append(answer)
        
        logger.info(
            "학생 답안 조회 완료 (메모리)",
            submission_id=str(submission_id),
            answer_count=len(answers)
        )
        
        return answers
    
    async def get_exam_sheet_id_by_submission_id(self, submission_id: UUID) -> UUID | None:
        """
        제출 ID로 시험지 ID 조회
        
        Args:
            submission_id: 제출 고유 ID
            
        Returns:
            UUID | None: 시험지 ID 또는 None
        """
        exam_sheet_id = self.storage.submission_to_exam_sheet.get(submission_id)
        
        if exam_sheet_id:
            logger.info(
                "시험지 ID 조회 성공 (메모리)",
                submission_id=str(submission_id),
                exam_sheet_id=str(exam_sheet_id)
            )
        else:
            logger.warning("시험지 ID 조회 실패 (메모리)", submission_id=str(submission_id))
        
        return exam_sheet_id
    
    # 데이터 추가 메서드 (테스트용)
    def add_submission(
        self,
        submission_id: UUID,
        user_id: UUID,
        exam_id: UUID,
        exam_sheet_id: UUID,
        submitted_at: datetime | None = None
    ):
        """테스트용 제출 데이터 추가"""
        submission_data = {
            "id": str(submission_id),
            "user_id": str(user_id), 
            "exam_id": str(exam_id),
            "submitted_at": submitted_at or datetime.now(),
            "total_score": None
        }
        
        self.storage.submissions[submission_id] = submission_data
        self.storage.submission_to_exam_sheet[submission_id] = exam_sheet_id
        self.storage.submission_to_answers[submission_id] = []
        
        logger.info("테스트용 제출 데이터 추가", submission_id=str(submission_id))
    
    def add_student_answer(
        self,
        answer: StudentAnswerSheetQuestion,
        submission_id: UUID,
        answer_sheet_id: UUID | None = None
    ):
        """테스트용 학생 답안 추가
        
        수정: StudentAnswerSheetQuestion 사용 및 answer_sheet 관계 처리
        """
        # answer_sheet가 없으면 생성
        if answer_sheet_id is None:
            answer_sheet_id = answer.student_answer_sheet_id
        
        # answer_sheet가 없으면 생성
        if answer_sheet_id not in self.storage.student_answer_sheets:
            sheet = StudentAnswerSheet(
                id=answer_sheet_id,
                submission_id=submission_id,
                student_name="Test Student"
            )
            self.storage.student_answer_sheets[answer_sheet_id] = sheet
        
        # 실제 답안 저장
        self.storage.student_answers[answer.id] = answer
        
        logger.info(
            "테스트용 학생 답안 추가",
            answer_id=str(answer.id),
            submission_id=str(submission_id),
            answer_sheet_id=str(answer_sheet_id)
        )

    
    async def create_submission(
        self, 
        exam_id: UUID, 
        student_id: int,
        submission_id: UUID | None = None
    ) -> UUID:
        """
        새로운 제출 생성
        
        Args:
            exam_id: 시험 ID
            student_id: 학생 ID  
            submission_id: 제출 ID (없으면 자동 생성)
            
        Returns:
            UUID: 생성된 제출 ID
        """
        from app.utils.uuid_utils import generate_uuidv7
        
        submission_id = submission_id or generate_uuidv7()
        
        # 제출 데이터 생성
        submission = {
            'id': submission_id,
            'exam_id': exam_id,
            'student_id': student_id,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }
        
        self.storage.submissions[submission_id] = submission
        return submission_id
    
    async def create_answer_sheet(
        self,
        submission_id: UUID,
        student_name: str,
        answer_sheet_id: UUID | None = None
    ) -> UUID:
        """
        학생 답안지 생성
        
        Args:
            submission_id: 제출 ID
            student_name: 학생 이름
            answer_sheet_id: 답안지 ID (없으면 자동 생성)
            
        Returns:
            UUID: 생성된 답안지 ID
        """
        from app.utils.uuid_utils import generate_uuidv7
        
        sheet_id = answer_sheet_id or generate_uuidv7()
        
        # StudentAnswerSheet 객체 생성
        answer_sheet = StudentAnswerSheet(
            id=sheet_id,
            submission_id=submission_id,
            student_name=student_name
        )
        
        self.storage.student_answer_sheets[sheet_id] = answer_sheet
        return sheet_id
    
    async def create_answer_sheet_questions(
        self,
        answer_sheet_id: UUID,
        answers: list[dict]
    ) -> list[UUID]:
        """
        답안지 문제별 답안 생성
        
        Args:
            answer_sheet_id: 답안지 ID
            answers: 답안 리스트 (question_id, answer_text, selected_choice 포함)
            
        Returns:
            list[UUID]: 생성된 답안 ID 리스트
        """
        from app.utils.uuid_utils import generate_uuidv7
        
        answer_ids = []
        
        for answer_dict in answers:
            # UUID 처리 (dict에서 UUID로 변환)
            answer_id = answer_dict.get("id")
            if answer_id is None:
                answer_id = generate_uuidv7()
            elif isinstance(answer_id, str):
                answer_id = UUID(answer_id)
            
            # StudentAnswerSheetQuestion 객체 생성
            answer_obj = StudentAnswerSheetQuestion(
                id=answer_id,
                question_id=answer_dict["question_id"],
                student_answer_sheet_id=answer_sheet_id,
                answer_text=answer_dict.get("answer_text"),
                selected_choice=answer_dict.get("selected_choice"),

            )
            
            self.storage.student_answers[answer_id] = answer_obj
            answer_ids.append(answer_id)
        
        logger.info(
            "답안 생성 완료 (메모리)",
            answer_sheet_id=str(answer_sheet_id),
            answer_count=len(answer_ids)
        )
        
        return answer_ids
    
    async def get_exam_sheet_id_by_exam_id(self, exam_id: UUID) -> UUID | None:
        """
        시험 ID로 시험지 ID 조회
        
        Args:
            exam_id: 시험 ID
            
        Returns:
            UUID | None: 시험지 ID 또는 None
        """
        # 메모리 구현에서는 간단히 매핑 테이블 사용
        # 실제 DB에서는 exam 테이블 조회
        exam_sheet_id = self.storage.exam_to_exam_sheet.get(exam_id)
        
        if exam_sheet_id:
            logger.info(
                "시험지 ID 조회 성공 (메모리)",
                exam_id=str(exam_id),
                exam_sheet_id=str(exam_sheet_id)
            )
        else:
            logger.warning(
                "시험지 ID 조회 실패 (메모리)",
                exam_id=str(exam_id)
            )
        
        return exam_sheet_id


class InMemoryQuestionRepository(QuestionRepositoryInterface):
    """
    인메모리 기반 문제 정보 데이터 접근 구현체
    
    메모리에 저장된 문제 정보를 관리
    """
    
    def __init__(self):
        """인메모리 문제 Repository 초기화"""
        self.storage = storage
    
    async def get_questions_by_exam_sheet_id(self, exam_sheet_id: UUID) -> list[QuestionData]:
        """
        시험지 ID로 해당 시험지의 모든 문제 조회
        
        Args:
            exam_sheet_id: 시험지 고유 ID
            
        Returns:
            list[QuestionData]: 문제 정보 목록
        """
        question_ids = self.storage.exam_sheet_questions.get(exam_sheet_id, [])
        questions = []
        
        for question_id in question_ids:
            question = self.storage.questions.get(question_id)
            if question:
                questions.append(question)
        
        logger.info(
            "시험지 문제 조회 완료 (메모리)",
            exam_sheet_id=str(exam_sheet_id),
            question_count=len(questions)
        )
        
        return questions
    
    async def get_question_by_id(self, question_id: UUID) -> QuestionData | None:
        """
        문제 ID로 개별 문제 정보 조회
        
        Args:
            question_id: 문제 고유 ID
            
        Returns:
            QuestionData | None: 문제 정보 또는 None
        """
        question = self.storage.questions.get(question_id)
        
        if question:
            logger.info("문제 정보 조회 성공 (메모리)", question_id=str(question_id))
        else:
            logger.warning("문제 정보 없음 (메모리)", question_id=str(question_id))
        
        return question
    
    # 데이터 추가 메서드 (테스트용)
    def add_question(self, question: QuestionData):
        """테스트용 문제 추가"""
        self.storage.questions[question.question_id] = question
        logger.info("테스트용 문제 추가", question_id=str(question.question_id))
    
    def add_exam_sheet_questions(self, exam_sheet_id: UUID, question_ids: List[UUID]):
        """테스트용 시험지-문제 매핑 추가"""
        self.storage.exam_sheet_questions[exam_sheet_id] = question_ids
        logger.info(
            "테스트용 시험지-문제 매핑 추가",
            exam_sheet_id=str(exam_sheet_id),
            question_count=len(question_ids)
        )


class InMemoryGradingRepository(GradingRepositoryInterface):
    """
    인메모리 기반 채점 결과 데이터 저장/조회 구현체
    
    메모리에 채점 결과를 저장하고 관리
    """
    
    def __init__(self):
        """인메모리 채점 Repository 초기화"""
        self.storage = storage
    
    async def create_exam_result(
        self,
        submission_id: UUID,
        exam_sheet_id: UUID,
        status: str = "PENDING"
    ) -> UUID:
        """
        시험 결과 레코드 생성 (채점 전 상태)
        
        Args:
            submission_id: 제출 ID
            exam_sheet_id: 시험지 ID
            status: 초기 상태 (기본값: PENDING)
            
        Returns:
            UUID: 생성된 exam_result ID
        """
        from app.utils.uuid_utils import generate_uuidv7
        from datetime import datetime
        
        result_id = generate_uuidv7()
        
        # 기본 채점 결과 객체 생성
        grading_result = ExamGradingResult(
            result_id=result_id,
            submission_id=submission_id,
            exam_sheet_id=exam_sheet_id,
            graded_at=datetime.now(),
            total_score=0,
            status=GradingStatus(status),
            question_results=[],
            version=1
        )
        
        # 저장소에 저장
        self.storage.grading_results[submission_id] = grading_result
        
        logger.info(
            "시험 결과 레코드 생성 완료",
            result_id=str(result_id),
            submission_id=str(submission_id),
            status=status
        )
        
        return result_id
    
    async def save_grading_result(self, grading_result: ExamGradingResult) -> bool:
        """
        전체 시험 채점 결과 저장
        
        Args:
            grading_result: 저장할 채점 결과
            
        Returns:
            bool: 저장 성공 여부 (항상 True)
        """
        try:
            # 메모리에 채점 결과 저장
            self.storage.grading_results[grading_result.result_id] = grading_result
            
            logger.info(
                "채점 결과 저장 성공 (메모리)",
                result_id=str(grading_result.result_id),
                submission_id=str(grading_result.submission_id),
                total_score=grading_result.total_score,
                question_count=len(grading_result.question_results)
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "채점 결과 저장 실패 (메모리)",
                result_id=str(grading_result.result_id),
                error=str(e)
            )
            return False
    
    async def get_grading_result_by_submission_id(
        self, 
        submission_id: UUID
    ) -> ExamGradingResult | None:
        """
        제출 ID로 채점 결과 조회
        
        Args:
            submission_id: 제출 고유 ID
            
        Returns:
            ExamGradingResult | None: 채점 결과 또는 None
        """
        # 모든 채점 결과에서 submission_id가 일치하는 것을 찾기
        for grading_result in self.storage.grading_results.values():
            if grading_result.submission_id == submission_id:
                logger.info(
                    "채점 결과 조회 성공 (메모리)",
                    submission_id=str(submission_id),
                    result_id=str(grading_result.result_id)
                )
                return grading_result
        
        logger.warning("채점 결과 없음 (메모리)", submission_id=str(submission_id))
        return None
    
    async def update_grading_status(
        self,
        result_id: UUID,
        status: str
    ) -> bool:
        """
        채점 상태 업데이트
        
        Args:
            result_id: 채점 결과 ID
            status: 새로운 상태
            
        Returns:
            bool: 업데이트 성공 여부
        """
        grading_result = self.storage.grading_results.get(result_id)
        
        if grading_result:
            try:
                grading_result.status = GradingStatus(status)
                logger.info(
                    "채점 상태 업데이트 성공 (메모리)",
                    result_id=str(result_id),
                    status=status
                )
                return True
            except ValueError as e:
                logger.error(
                    "잘못된 채점 상태",
                    result_id=str(result_id),
                    status=status,
                    error=str(e)
                )
                return False
        else:
            logger.warning(
                "채점 결과 없어서 상태 업데이트 실패 (메모리)",
                result_id=str(result_id)
            )
            return False
    
    async def get_grading_results_by_exam_id(
        self,
        exam_id: UUID
    ) -> list[ExamGradingResult]:
        """
        시험 ID로 모든 채점 결과 조회 (배치 채점용)
        
        메모리 구현에서는 exam_id 직접 매핑이 어려우므로
        submission_id 기반으로 필터링하는 간단한 구현
        
        Args:
            exam_id: 시험 고유 ID
            
        Returns:
            list[ExamGradingResult]: 채점 결과 목록
        """
        # 실제 구현에서는 submission과 exam 연결을 통해 필터링해야 하지만
        # 메모리 구현에서는 단순화하여 모든 결과를 반환
        results = list(self.storage.grading_results.values())
        
        logger.info(
            "시험별 채점 결과 조회 완료 (메모리)",
            exam_id=str(exam_id),
            result_count=len(results)
        )
        
        return results
    
    async def save_question_grading_result(
        self,
        result_id: UUID,
        question_result: QuestionGradingResult
    ) -> bool:
        """
        개별 문제 채점 결과 저장/업데이트
        
        메모리 구현에서는 전체 결과 내의 question_results를 수정
        
        Args:
            result_id: 전체 채점 결과 ID
            question_result: 문제별 채점 결과
            
        Returns:
            bool: 저장 성공 여부
        """
        grading_result = self.storage.grading_results.get(result_id)
        
        if not grading_result:
            logger.warning(
                "채점 결과 없어서 문제별 결과 저장 실패 (메모리)",
                result_id=str(result_id)
            )
            return False
        
        try:
            # 기존 문제 결과 중에서 같은 question_id를 찾아서 업데이트
            updated = False
            for i, existing_result in enumerate(grading_result.question_results):
                if existing_result.question_id == question_result.question_id:
                    grading_result.question_results[i] = question_result
                    updated = True
                    break
            
            # 기존에 없으면 새로 추가
            if not updated:
                grading_result.question_results.append(question_result)
            
            logger.info(
                "문제별 채점 결과 저장 성공 (메모리)",
                result_id=str(result_id),
                question_id=str(question_result.question_id),
                action="updated" if updated else "added"
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "문제별 채점 결과 저장 실패 (메모리)",
                result_id=str(result_id),
                question_id=str(question_result.question_id),
                error=str(e)
            )
            return False