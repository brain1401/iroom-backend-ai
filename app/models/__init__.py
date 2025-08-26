"""
데이터 모델 패키지

Pydantic 기반 데이터 모델 정의

포함 모듈:
- text_recognition: 글자인식 처리 관련 모델
"""

from .text_recognition import (
    TextRecognitionAnswer,
    TextRecognitionAnswerResponse, 
    TextRecognitionErrorResponse,
    TextRecognitionMetadata
)

__all__ = [
    "TextRecognitionAnswer",
    "TextRecognitionAnswerResponse", 
    "TextRecognitionErrorResponse",
    "TextRecognitionMetadata"
]