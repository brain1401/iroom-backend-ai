"""
글자인식 처리 데이터 모델

한국어 답안지 글자인식 처리용 Pydantic 모델 정의
번호 기반 혼합 문제 유형 지원 (객관식 + 주관식)

주요 모델:
- TextRecognitionAnswerRequest: 답안지 글자인식 요청
- TextRecognitionAnswer: 개별 답안 정보 (번호 기반: 1, 2, 3...)
- TextRecognitionAnswerResponse: 답안지 글자인식 응답
- TextRecognitionMetadata: 글자인식 처리 메타데이터

지원 문제 유형:
- 객관식: A, B, C, D, E (또는 가, 나, 다, 라, 마)
- 주관식: 수학 수식, 텍스트 답안, 숫자 답안
"""

from datetime import datetime
from typing import TYPE_CHECKING

from uuid import UUID, uuid4
from pydantic import BaseModel, Field, model_validator, field_serializer

if TYPE_CHECKING:
    from app.utils.errors import ErrorResponse


class SolutionProcess(BaseModel):
    """
    풀이 과정 영역 모델 (v2.1.0)
    
    답안지의 큰 박스에 작성된 풀이 과정 내용
    여러 줄의 계산 과정이나 설명 포함 가능
    """
    extracted_text: str = Field(
        ...,
        description="풀이 과정 텍스트 (줄바꿈 \\n 포함 가능)"
    )
    latex_formula: str | None = Field(
        default=None,
        description="LaTeX 변환된 풀이 과정 (수식인 경우)"
    )


class FinalAnswer(BaseModel):
    """
    최종 답안 영역 모델 (v2.1.0)
    
    답안지의 작은 박스에 작성된 최종 답안
    일반적으로 한 줄의 간단한 답
    """
    extracted_text: str = Field(
        ...,
        description="최종 답안 텍스트"
    )
    latex_formula: str | None = Field(
        default=None,
        description="LaTeX 변환된 최종 답안 (수식인 경우)"
    )

class TextRecognitionAnswer(BaseModel):
    """
    개별 답안 정보 모델 (v2.1.0 구조 지원)
    
    주요 구조:
    - question_number: 문제 번호 (1-20)
    - question_label: 문제 라벨 ("1", "2", "3"...)
    - solution_process: 풀이 과정 영역 (nested object)
    - final_answer: 최종 답안 영역 (nested object)
    - confidence: 인식 신뢰도 (0.0-1.0)
    
    v2.1.0 변경사항:
    - extracted_text와 latex_formula를 solution_process와 final_answer로 분리
    - 각 영역별로 별도의 텍스트와 LaTeX 변환 제공
    """
    question_number: int = Field(
        ...,
        ge=1, 
        le=20,
        description="문제 번호 (1부터 20까지)"
    )
    question_label: str = Field(
        ...,
        pattern=r"^\d{1,2}$",
        description="문제 라벨 (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20)"
    )
    
    # v2.1.0 새로운 구조: solution_process와 final_answer로 분리
    solution_process: SolutionProcess | None = Field(
        default=None,
        description="풀이 과정 영역의 내용 (여러 줄 가능)"
    )
    final_answer: FinalAnswer | None = Field(
        default=None,
        description="최종 답안 박스의 내용 (단일 답안)"
    )
    
    # 하위 호환성을 위한 필드 (v2.0.0 이하 지원)
    extracted_text: str | None = Field(
        default=None,
        description="[Deprecated] 기존 플랫 구조 지원용 - solution_process와 final_answer 사용 권장"
    )
    latex_formula: str | None = Field(
        default=None,
        description="[Deprecated] 기존 플랫 구조 지원용 - solution_process와 final_answer 사용 권장"
    )
    
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="텍스트 인식 신뢰도 (0.0-1.0)"
    )
    
    @model_validator(mode='after')
    def validate_structure(self) -> 'TextRecognitionAnswer':
        """
        구조 검증 및 하위 호환성 처리
        
        처리 로직:
        1. 새로운 구조 (solution_process/final_answer) 우선
        2. 기존 구조 (extracted_text/latex_formula)만 있으면 자동 변환
        3. 둘 다 없으면 오류
        """
        has_new_structure = self.solution_process is not None or self.final_answer is not None
        has_old_structure = self.extracted_text is not None
        
        if not has_new_structure and not has_old_structure:
            raise ValueError("답안 데이터가 없음: solution_process/final_answer 또는 extracted_text 필요")
        
        # 기존 구조만 있는 경우 새 구조로 변환 (하위 호환성)
        if not has_new_structure and has_old_structure:
            # 기존 텍스트를 final_answer로 이동
            self.final_answer = FinalAnswer(
                extracted_text=self.extracted_text or "",
                latex_formula=self.latex_formula
            )
        
        return self


class TextRecognitionMetadata(BaseModel):
    """
    글자인식 처리 메타데이터
    
    필드:
    - image_quality: 이미지 품질 평가
    - processing_time_ms: 처리 시간 (밀리초)
    - total_questions_detected: 감지된 총 문제 수
    - model_version: 사용된 Gemini 모델 버전
    """
    image_quality: str = Field(
        ...,
        description="이미지 품질 (good/fair/poor)"
    )
    processing_time_ms: int = Field(
        ...,
        ge=0,
        description="글자인식 처리 시간 (밀리초)"
    )
    total_questions_detected: int = Field(
        ...,
        ge=0,
        description="감지된 총 문제 수"
    )
    model_version: str = Field(
        default="gemini-2.5-pro",
        description="사용된 Gemini 모델 버전"
    )


class TextRecognitionAnswerResponse(BaseModel):
    """
    답안지 글자인식 처리 응답 모델
    
    필드:
    - sheet_id: 답안지 고유 식별자
    - processing_timestamp: 처리 완료 시각
    - answers: 추출된 답안 목록 (번호 기반 혼합 문제 유형 지원)
    - metadata: 처리 메타데이터
    """
    sheet_id: UUID = Field(
        default_factory=uuid4,
        description="답안지 고유 식별자"
    )
    processing_timestamp: datetime = Field(
        default_factory=datetime.now,
        description="처리 완료 시각"
    )
    answers: list[TextRecognitionAnswer] = Field(
        ...,
        description="추출된 답안 목록 - 번호 기반(1,2,3...) 혼합 문제 유형 지원",
        min_length=0,
        max_length=20
    )
    metadata: TextRecognitionMetadata = Field(
        ...,
        description="글자인식 처리 메타데이터"
    )


class TextRecognitionErrorResponse(BaseModel):
    """
    글자인식 처리 오류 응답 모델 (호환성 래퍼)
    
    통합된 ErrorResponse 모델을 기반으로 하되,
    기존 API 호환성을 유지하기 위한 래퍼 클래스
    
    필드:
    - error_code: 오류 코드
    - error_message: 오류 메시지  
    - details: 상세 오류 정보
    - timestamp: 오류 발생 시각
    """
    error_code: str = Field(
        ...,
        description="오류 코드 (IMAGE_TOO_LARGE, UNSUPPORTED_FORMAT, PROCESSING_FAILED 등)"
    )
    error_message: str = Field(
        ...,
        description="사용자 친화적 오류 메시지"
    )
    details: str | None = Field(
        default=None,
        description="개발자용 상세 오류 정보"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="오류 발생 시각"
    )
    
    @classmethod
    def from_error_response(
        cls, 
        error_response: "ErrorResponse",
        error_code: str | None = None
    ) -> "TextRecognitionErrorResponse":
        """
        통합 ErrorResponse에서 TextRecognitionErrorResponse 생성
        
        Args:
            error_response: 통합 오류 응답 모델
            error_code: 글자인식 전용 오류 코드 (선택적)
        
        Returns:
            TextRecognitionErrorResponse: 호환성을 위한 응답 모델
        """
        from datetime import datetime
        
        return cls(
            error_code=error_code or error_response.error.code or "PROCESSING_ERROR",
            error_message=error_response.error.message,
            details=str(error_response.error.details) if error_response.error.details else None,
            timestamp=datetime.fromisoformat(error_response.error.timestamp.replace('Z', '+00:00'))
        )
    
    def to_error_response(self) -> "ErrorResponse":
        """
        통합 ErrorResponse로 변환
        
        Returns:
            ErrorResponse: 표준화된 오류 응답
        """
        from app.utils.errors import ErrorResponse, ErrorDetail
        from datetime import timezone
        
        return ErrorResponse(
            error=ErrorDetail(
                message=self.error_message,
                status_code=422,  # 기본값 
                timestamp=self.timestamp.replace(tzinfo=timezone.utc).isoformat(),
                code=self.error_code,
                details=self.details
            )
        )


class AsyncTextRecognitionRequest(BaseModel):
    """
    비동기 글자인식 처리 요청 모델
    
    Spring Boot에서 전송하는 비동기 처리 요청
    
    필드:
    - callback_url: 완료 시 결과를 전송받을 URL
    - priority: 처리 우선순위 (1=highest, 5=lowest)
    - use_cache: 캐시 사용 여부
    - use_content_hash: 내용 기반 해시 사용 여부
    - metadata: 추가 메타데이터
    """
    callback_url: str = Field(
        ...,
        description="처리 완료 시 결과를 전송받을 콜백 URL",
        pattern=r"^https?://.+"
    )
    priority: int = Field(
        default=1,
        ge=1,
        le=5,
        description="처리 우선순위 (1=highest, 5=lowest)"
    )
    use_cache: bool = Field(
        default=True,
        description="캐시 사용 여부"
    )
    use_content_hash: bool = Field(
        default=False,
        description="내용 기반 해시 사용 여부"
    )
    metadata: dict[str, str] | None = Field(
        default=None,
        description="추가 메타데이터 (선택적)"
    )


class AsyncTextRecognitionSubmitResponse(BaseModel):
    """
    비동기 글자인식 처리 제출 응답 모델
    
    Spring Boot로 즉시 반환되는 응답
    
    필드:
    - job_id: 작업 고유 식별자
    - status: 현재 상태
    - estimated_completion_time: 예상 완료 시간 
    - callback_url: 등록된 콜백 URL
    - submitted_at: 제출 시각
    """
    job_id: UUID = Field(
        default_factory=uuid4,
        description="작업 고유 식별자"
    )
    status: str = Field(
        default="submitted",
        description="현재 상태 (submitted, processing, completed, failed)"
    )
    estimated_completion_time: datetime | None = Field(
        default=None,
        description="예상 완료 시간"
    )
    callback_url: str = Field(
        ...,
        description="등록된 콜백 URL"
    )
    submitted_at: datetime = Field(
        default_factory=datetime.now,
        description="제출 시각"
    )


class AsyncTextRecognitionCallbackData(BaseModel):
    """
    비동기 글자인식 완료 콜백 데이터 모델
    
    Spring Boot로 전송되는 완료 알림 데이터
    
    필드:
    - job_id: 작업 식별자
    - status: 최종 상태
    - result: 글자인식 결과 (성공 시)
    - error: 오류 정보 (실패 시)
    - processing_time_ms: 총 처리 시간
    - completed_at: 완료 시각
    """
    job_id: UUID = Field(
        ...,
        description="작업 식별자"
    )
    status: str = Field(
        ...,
        description="최종 상태 (completed, failed)"
    )
    result: TextRecognitionAnswerResponse | None = Field(
        default=None,
        description="글자인식 결과 (성공 시만 포함)"
    )
    error: TextRecognitionErrorResponse | None = Field(
        default=None,
        description="오류 정보 (실패 시만 포함)"
    )
    processing_time_ms: int = Field(
        ...,
        ge=0,
        description="총 처리 시간 (밀리초)"
    )
    completed_at: datetime = Field(
        default_factory=datetime.now,
        description="완료 시각"
    )
    metadata: dict[str, str] | None = Field(
        default=None,
        description="추가 메타데이터 (원본 요청에서 전달된 데이터)"
    )
    
    @field_serializer('job_id')
    def serialize_uuid(self, value: UUID) -> str:
        """UUID를 문자열로 직렬화"""
        return str(value)
    
    @field_serializer('completed_at')
    def serialize_datetime(self, value: datetime) -> str:
        """datetime을 ISO 형식 문자열로 직렬화"""
        return value.isoformat()


class AsyncJobStatus(BaseModel):
    """
    비동기 작업 상태 모델
    
    내부 상태 관리용 모델
    
    필드:
    - job_id: 작업 식별자
    - status: 현재 상태
    - callback_url: 콜백 URL
    - submitted_at: 제출 시각
    - started_at: 처리 시작 시각
    - completed_at: 완료 시각
    - result: 처리 결과
    - error: 오류 정보
    - retry_count: 콜백 재시도 횟수
    """
    job_id: UUID = Field(..., description="작업 식별자")
    status: str = Field(..., description="현재 상태")
    callback_url: str = Field(..., description="콜백 URL")
    priority: int = Field(default=1, description="처리 우선순위")
    use_cache: bool = Field(default=True, description="캐시 사용 여부")
    use_content_hash: bool = Field(default=False, description="내용 기반 해시 사용 여부")
    
    submitted_at: datetime = Field(default_factory=datetime.now, description="제출 시각")
    started_at: datetime | None = Field(default=None, description="처리 시작 시각")
    completed_at: datetime | None = Field(default=None, description="완료 시각")
    
    result: TextRecognitionAnswerResponse | None = Field(default=None, description="처리 결과")
    error: TextRecognitionErrorResponse | None = Field(default=None, description="오류 정보")
    
    retry_count: int = Field(default=0, description="콜백 재시도 횟수")
    last_callback_attempt: datetime | None = Field(default=None, description="마지막 콜백 시도 시각")
    
    original_metadata: dict[str, str] | None = Field(default=None, description="원본 요청 메타데이터")
