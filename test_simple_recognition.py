#!/usr/bin/env python3
"""
SIMPLE_KOREAN 프롬프트 테스트
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.utils.text_recognition_core import (
    create_gemini_vision_model,
    process_text_recognition_with_gemini
)
from app.config.settings import get_settings

import logging
logging.basicConfig(level=logging.INFO)

async def test_simple_prompt():
    """간단한 프롬프트로 테스트"""
    
    # 이미지 읽기
    with open("test_img.JPEG", 'rb') as f:
        image_data = f.read()
    
    print("🚀 SIMPLE_KOREAN 프롬프트 테스트 시작...")
    
    # Gemini 모델 생성
    settings = get_settings()
    model = create_gemini_vision_model(settings.gemini_api_key)
    
    # 글자 인식 수행
    result = await process_text_recognition_with_gemini(image_data, model)
    
    print(f"\n📊 결과:")
    print(f"  - 감지된 문제 수: {result.detected_questions}")
    print(f"  - 답안 수: {len(result.answers)}")
    
    if result.answers:
        print("\n📝 인식된 답안들:")
        for i, answer in enumerate(result.answers, 1):
            print(f"  {i}. 문제 {answer.question_number}: {answer.extracted_text}")
    else:
        print("\n⚠️ 답안이 없습니다.")
    
    return result

if __name__ == "__main__":
    asyncio.run(test_simple_prompt())