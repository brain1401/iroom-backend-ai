"""
프롬프트 관리 모듈

글자인식, 채점 등 AI 프롬프트 중앙 관리
"""

from app.prompts.text_recognition_prompts import (
    TextRecognitionPromptManager,
    PromptType,
)

__all__ = [
    "TextRecognitionPromptManager",
    "PromptType",
]