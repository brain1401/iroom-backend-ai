"""
글자인식 처리 데이터 모델

한국어 답안지 글자인식 처리용 Pydantic 모델 정의

주요 모델:
- TextRecognitionAnswerRequest: 답안지 글자인식 요청
- TextRecognitionAnswer: 개별 답안 정보
- TextRecognitionAnswerResponse: 답안지 글자인식 응답
- TextRecognitionMetadata: 글자인식 처리 메타데이터
"""

from datetime import datetime

from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class TextRecognitionAnswer(BaseModel):
    """
    개별 답안 정보 모델
    
    필드:
    - question_number: 문제 번호 (1-7)
    - question_label: 문제 라벨 ("주1", "주2", ...)
    - extracted_text: 추출된 텍스트 내용
    - confidence: 인식 신뢰도 (0.0-1.0)
    """
    question_number: int = Field(
        ...,
        ge=1, 
        le=7,
        description="문제 번호 (1부터 7까지)"
    )
    question_label: str = Field(
        ...,
        description="문제 라벨 (주1, 주2, 주3, 주4, 주5, 주6, 주7)"
    )
    extracted_text: str = Field(
        ...,
        description="글자인식으로 추출된 한국어 텍스트"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="텍스트 인식 신뢰도 (0.0-1.0)"
    )


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
    - answers: 추출된 답안 목록
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
        description="추출된 답안 목록",
        min_length=0,
        max_length=7
    )
    metadata: TextRecognitionMetadata = Field(
        ...,
        description="글자인식 처리 메타데이터"
    )


class TextRecognitionErrorResponse(BaseModel):
    """
    글자인식 처리 오류 응답 모델
    
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