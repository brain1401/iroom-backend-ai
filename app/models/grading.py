"""
채점 시스템 데이터 모델

시험 답안 자동/AI 보조 채점을 위한 Pydantic 모델 정의
객관식 자동 채점 및 주관식 AI 채점 지원

주요 모델:
- GradingRequest: 채점 요청
- QuestionData: 문제 정보 (DB question 테이블 기반)
- StudentAnswer: 학생 답안 (DB student_answer_sheet 테이블 기반)
- QuestionGradingResult: 문제별 채점 결과
- ExamGradingResult: 전체 시험 채점 결과
- GradingProgress: 채점 진행 상태
- GradingMetadata: 채점 처리 메타데이터

채점 유형:
- AUTO: 객관식 자동 채점
- AI_ASSISTED: 주관식 AI 보조 채점
- MANUAL: 수동 채점
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    """문제 유형"""
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"  # 객관식
    SUBJECTIVE = "SUBJECTIVE"           # 주관식


class Difficulty(str, Enum):
    """문제 난이도"""
    LOW = "하"      # 쉬움
    MEDIUM = "중"   # 보통
    HIGH = "상"     # 어려움


class GradingMethod(str, Enum):
    """채점 방식"""
    AUTO = "AUTO"                    # 자동 채점 (객관식)
    AI_ASSISTED = "AI_ASSISTED"      # AI 보조 채점 (주관식)
    MANUAL = "MANUAL"                # 수동 채점


class GradingStatus(str, Enum):
    """채점 상태"""
    PENDING = "PENDING"              # 대기 중
    IN_PROGRESS = "IN_PROGRESS"      # 진행 중
    COMPLETED = "COMPLETED"          # 완료
    FAILED = "FAILED"                # 실패
    REGRADED = "REGRADED"           # 재채점


class QuestionData(BaseModel):
    """
    문제 정보 모델 (DB question 테이블 기반)
    
    필드:
    - question_id: 문제 ID
    - question_text: 문제 텍스트
    - question_type: 문제 유형 (객관식/주관식)
    - difficulty: 난이도 (하/중/상)
    - points: 배점
    - answer_text: 주관식 정답
    - choices: 객관식 선택지 (JSON)
    - correct_choice: 객관식 정답 번호
    - scoring_rubric: 채점 기준
    """
    question_id: UUID = Field(..., description="문제 고유 ID")
    question_text: str = Field(..., description="문제 텍스트")
    question_type: QuestionType = Field(..., description="문제 유형")
    difficulty: Difficulty = Field(..., description="문제 난이도")
    points: int = Field(..., ge=1, description="문제 배점")
    answer_text: str | None = Field(default=None, description="주관식 문제 정답")
    choices: dict | None = Field(default=None, description="객관식 선택지 (JSON)")
    correct_choice: int | None = Field(default=None, description="객관식 정답 번호")
    scoring_rubric: str | None = Field(default=None, description="채점 기준 텍스트")


class StudentAnswer(BaseModel):
    """
    학생 답안 모델 (DB student_answer_sheet 테이블 기반)
    
    필드:
    - answer_id: 답안 ID
    - question_id: 문제 ID
    - answer_text: 답안 텍스트
    - answer_image_url: 답안 이미지 URL
    - selected_choice: 객관식 선택 답안
    - ai_solution_process: AI가 추출한 풀이 과정
    """
    answer_id: UUID = Field(..., description="답안 고유 ID")
    question_id: UUID = Field(..., description="문제 ID")
    answer_text: str | None = Field(default=None, description="답안 텍스트")
    answer_image_url: str | None = Field(default=None, description="답안 이미지 URL")
    selected_choice: int | None = Field(default=None, description="객관식 선택 답안")
    ai_solution_process: str | None = Field(default=None, description="AI 추출 풀이 과정")


class QuestionGradingResult(BaseModel):
    """
    문제별 채점 결과
    
    필드:
    - question_id: 문제 ID
    - answer_id: 답안 ID
    - is_correct: 정답 여부
    - score: 획득 점수
    - max_score: 만점
    - grading_method: 채점 방식
    - confidence_score: AI 채점 신뢰도 (0.00-1.00)
    - grading_comment: 채점 코멘트/피드백
    """
    question_id: UUID = Field(..., description="문제 ID")
    answer_id: UUID = Field(..., description="답안 ID")
    is_correct: bool | None = Field(default=None, description="정답 여부")
    score: int | None = Field(default=None, description="획득 점수")
    max_score: int = Field(..., ge=1, description="문제 만점")
    grading_method: GradingMethod = Field(..., description="채점 방식")
    confidence_score: Decimal | None = Field(
        default=None,
        ge=0,
        le=1,
        decimal_places=2,
        description="AI 채점 신뢰도 (0.00-1.00)"
    )
    grading_comment: str | None = Field(default=None, description="채점 코멘트/피드백")
    created_at: datetime = Field(default_factory=datetime.now, description="채점 시각")


class GradingMetadata(BaseModel):
    """
    채점 처리 메타데이터
    
    필드:
    - total_questions: 총 문제 수
    - multiple_choice_count: 객관식 문제 수
    - subjective_count: 주관식 문제 수
    - processing_time_ms: 총 처리 시간 (밀리초)
    - ai_model_version: 사용된 AI 모델 버전
    """
    total_questions: int = Field(..., ge=0, description="총 문제 수")
    multiple_choice_count: int = Field(..., ge=0, description="객관식 문제 수")
    subjective_count: int = Field(..., ge=0, description="주관식 문제 수")
    processing_time_ms: int = Field(..., ge=0, description="총 처리 시간 (밀리초)")
    ai_model_version: str = Field(default="gemini-2.0-flash-exp", description="AI 모델 버전")


class ExamGradingResult(BaseModel):
    """
    전체 시험 채점 결과
    
    필드:
    - result_id: 채점 결과 ID
    - submission_id: 제출 ID
    - exam_sheet_id: 시험지 ID
    - status: 채점 상태
    - total_score: 총점
    - max_total_score: 만점
    - question_results: 문제별 채점 결과 목록
    - metadata: 채점 처리 메타데이터
    - grading_comment: 전체 채점 코멘트
    - graded_at: 채점 완료 시각
    """
    result_id: UUID = Field(default_factory=uuid4, description="채점 결과 고유 ID")
    submission_id: UUID = Field(..., description="제출 ID")
    exam_sheet_id: UUID = Field(..., description="시험지 ID")
    status: GradingStatus = Field(default=GradingStatus.PENDING, description="채점 상태")
    total_score: int | None = Field(default=None, description="총 획득 점수")
    max_total_score: int | None = Field(default=None, description="총 만점")
    question_results: list[QuestionGradingResult] = Field(
        default_factory=list,
        description="문제별 채점 결과 목록"
    )
    metadata: GradingMetadata | None = Field(default=None, description="채점 처리 메타데이터")
    grading_comment: str | None = Field(default=None, description="전체 채점 코멘트")
    graded_at: datetime | None = Field(default=None, description="채점 완료 시각")
    version: int = Field(default=1, description="재채점 버전")


class GradingProgress(BaseModel):
    """
    채점 진행 상태 (배치 채점용)
    
    필드:
    - batch_id: 배치 ID
    - submission_id: 제출 ID
    - total_questions: 총 문제 수
    - graded_questions: 채점 완료된 문제 수
    - failed_questions: 채점 실패한 문제 수
    - started_at: 채점 시작 시각
    - estimated_completion: 예상 완료 시각
    """
    batch_id: UUID = Field(default_factory=uuid4, description="배치 채점 고유 ID")
    submission_id: UUID = Field(..., description="제출 ID")
    total_questions: int = Field(..., ge=0, description="총 문제 수")
    graded_questions: int = Field(default=0, ge=0, description="채점 완료된 문제 수")
    failed_questions: int = Field(default=0, ge=0, description="채점 실패한 문제 수")
    started_at: datetime = Field(default_factory=datetime.now, description="채점 시작 시각")
    estimated_completion: datetime | None = Field(default=None, description="예상 완료 시각")
    
    @property
    def progress_percentage(self) -> float:
        """진행률 계산 (0-100)"""
        if self.total_questions == 0:
            return 100.0
        completed = self.graded_questions + self.failed_questions
        return (completed / self.total_questions) * 100
    
    @property
    def remaining_questions(self) -> int:
        """남은 문제 수"""
        return self.total_questions - self.graded_questions - self.failed_questions


class GradingRequest(BaseModel):
    """
    채점 요청 모델
    
    필드:
    - submission_id: 채점할 제출 ID
    - force_regrade: 강제 재채점 여부
    - grading_options: 채점 옵션
    """
    submission_id: UUID = Field(..., description="채점할 제출 ID")
    force_regrade: bool = Field(default=False, description="강제 재채점 여부")
    grading_options: dict = Field(
        default_factory=dict,
        description="채점 옵션 (AI 모델 설정, 엄격도 등)"
    )


class GradingErrorResponse(BaseModel):
    """
    채점 오류 응답 모델
    
    필드:
    - error_code: 오류 코드
    - error_message: 오류 메시지
    - details: 상세 오류 정보
    - submission_id: 관련 제출 ID
    - timestamp: 오류 발생 시각
    """
    error_code: str = Field(
        ...,
        description="오류 코드 (SUBMISSION_NOT_FOUND, GRADING_FAILED, DATABASE_ERROR 등)"
    )
    error_message: str = Field(..., description="사용자 친화적 오류 메시지")
    details: str | None = Field(default=None, description="개발자용 상세 오류 정보")
    submission_id: UUID | None = Field(default=None, description="관련 제출 ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="오류 발생 시각")


class BatchGradingRequest(BaseModel):
    """
    배치 채점 요청 모델
    
    필드:
    - submission_ids: 채점할 제출 ID 목록
    - force_regrade: 강제 재채점 여부
    - grading_options: 채점 옵션
    - priority: 처리 우선순위 (1-5, 1=highest)
    """
    submission_ids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="채점할 제출 ID 목록 (최대 50개)"
    )
    force_regrade: bool = Field(default=False, description="강제 재채점 여부")
    grading_options: dict = Field(
        default_factory=dict,
        description="채점 옵션"
    )
    priority: int = Field(default=3, ge=1, le=5, description="처리 우선순위 (1=highest, 5=lowest)")


class BatchGradingResult(BaseModel):
    """
    배치 채점 결과
    
    필드:
    - batch_id: 배치 ID
    - total_submissions: 총 제출 수
    - successful_gradings: 성공한 채점 수
    - failed_gradings: 실패한 채점 수
    - results: 개별 채점 결과 목록
    - total_processing_time_ms: 총 처리 시간
    - average_processing_time_ms: 평균 처리 시간
    """
    batch_id: UUID = Field(..., description="배치 채점 고유 ID")
    total_submissions: int = Field(..., ge=0, description="총 제출 수")
    successful_gradings: int = Field(..., ge=0, description="성공한 채점 수")
    failed_gradings: int = Field(..., ge=0, description="실패한 채점 수")
    results: list[ExamGradingResult] = Field(
        default_factory=list,
        description="개별 채점 결과 목록"
    )
    total_processing_time_ms: int = Field(..., ge=0, description="총 처리 시간")
    average_processing_time_ms: float = Field(..., ge=0, description="평균 처리 시간")
    completed_at: datetime = Field(default_factory=datetime.now, description="완료 시각")