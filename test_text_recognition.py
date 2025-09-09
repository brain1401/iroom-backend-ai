#!/usr/bin/env python3
"""
글자 인식 엔드포인트 디버깅 테스트

이미지 최적화 전후를 비교하고 Gemini 응답을 분석
"""

import asyncio
import base64
import json
import os
from pathlib import Path
from PIL import Image
import io
import sys

# 프로젝트 경로 추가
sys.path.insert(0, str(Path(__file__).parent))

from app.utils.image_processing import optimize_image_for_gemini, encode_image_to_base64
from app.utils.text_recognition_core import (
    create_text_recognition_prompt,
    create_gemini_vision_model,
    process_text_recognition_with_gemini
)
from app.config.settings import get_settings

import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def save_debug_image(image_data: bytes, filename: str):
    """디버깅용 이미지 저장"""
    debug_dir = Path("debug_images")
    debug_dir.mkdir(exist_ok=True)
    
    filepath = debug_dir / filename
    
    # 이미지 정보 추출
    with Image.open(io.BytesIO(image_data)) as img:
        logger.info(f"저장: {filename}")
        logger.info(f"  - 형식: {img.format}")
        logger.info(f"  - 크기: {img.size[0]} x {img.size[1]}")
        logger.info(f"  - 모드: {img.mode}")
        logger.info(f"  - 파일 크기: {len(image_data) / 1024:.2f} KB")
        
        # 이미지 저장
        img.save(filepath, format='JPEG' if img.format == 'MPO' else img.format)
    
    return filepath


async def test_with_simple_prompt(image_data: bytes):
    """단순화된 프롬프트로 테스트"""
    settings = get_settings()
    
    # 간단한 프롬프트
    simple_prompt = """
이미지에서 보이는 모든 텍스트를 찾아주세요.
번호가 있는 문제들을 찾아서 JSON 형식으로 답변해주세요.

{
  "answers": [
    {
      "question_number": "문제 번호",
      "extracted_text": "보이는 텍스트"
    }
  ]
}
"""
    
    # Gemini 모델 생성
    model = create_gemini_vision_model(settings.gemini_api_key)
    
    # Base64 인코딩
    image_base64 = encode_image_to_base64(image_data)
    
    # 메시지 생성
    from langchain_core.messages import HumanMessage
    message = HumanMessage(
        content=[
            {"type": "text", "text": simple_prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
            },
        ]
    )
    
    logger.info("단순 프롬프트로 Gemini API 호출...")
    response = await model.ainvoke([message])
    
    # 응답 로깅
    response_text = str(response.content)
    logger.info(f"Gemini 응답 (단순 프롬프트):\n{response_text}")
    
    return response_text


async def test_text_recognition(image_path: str):
    """글자 인식 테스트"""
    
    if not os.path.exists(image_path):
        logger.error(f"이미지를 찾을 수 없습니다: {image_path}")
        return
    
    logger.info("=" * 70)
    logger.info("📝 글자 인식 엔드포인트 디버깅 테스트")
    logger.info("=" * 70)
    
    # 원본 이미지 읽기
    with open(image_path, 'rb') as f:
        original_data = f.read()
    
    logger.info(f"\n원본 이미지: {image_path}")
    logger.info(f"원본 크기: {len(original_data) / 1024:.2f} KB")
    
    # 원본 이미지 저장
    original_path = save_debug_image(original_data, "1_original.jpg")
    
    # 이미지 최적화
    logger.info("\n이미지 최적화 수행...")
    optimized_data = optimize_image_for_gemini(original_data)
    
    # 최적화된 이미지 저장
    optimized_path = save_debug_image(optimized_data, "2_optimized.jpg")
    
    # 크기 비교
    compression_ratio = len(optimized_data) / len(original_data)
    logger.info(f"\n압축 비율: {compression_ratio:.2%}")
    
    # 1. 단순 프롬프트 테스트
    logger.info("\n" + "=" * 50)
    logger.info("📋 테스트 1: 단순 프롬프트")
    logger.info("=" * 50)
    
    simple_result = await test_with_simple_prompt(optimized_data)
    
    # 2. 원본 프롬프트 테스트
    logger.info("\n" + "=" * 50)
    logger.info("📋 테스트 2: 원본 프롬프트")
    logger.info("=" * 50)
    
    settings = get_settings()
    model = create_gemini_vision_model(settings.gemini_api_key)
    
    try:
        result = await process_text_recognition_with_gemini(optimized_data, model)
        logger.info(f"처리 결과:")
        logger.info(f"  - 감지된 문제 수: {result.detected_questions}")
        logger.info(f"  - 답안 수: {len(result.answers)}")
        
        if result.answers:
            for i, answer in enumerate(result.answers, 1):
                logger.info(f"\n답안 {i}:")
                logger.info(f"  - 문제 번호: {answer.question_number}")
                logger.info(f"  - 텍스트: {answer.extracted_text[:100] if answer.extracted_text else 'None'}")
        else:
            logger.warning("⚠️ 답안이 비어있습니다!")
            
    except Exception as e:
        logger.error(f"오류 발생: {e}")
    
    # 3. 최적화 없이 원본 이미지로 테스트
    logger.info("\n" + "=" * 50)
    logger.info("📋 테스트 3: 최적화 없이 원본 이미지")
    logger.info("=" * 50)
    
    try:
        result_original = await process_text_recognition_with_gemini(original_data, model)
        logger.info(f"원본 이미지 처리 결과:")
        logger.info(f"  - 감지된 문제 수: {result_original.detected_questions}")
        logger.info(f"  - 답안 수: {len(result_original.answers)}")
    except Exception as e:
        logger.error(f"원본 이미지 처리 오류: {e}")
    
    logger.info("\n" + "=" * 70)
    logger.info("✅ 테스트 완료")
    logger.info(f"디버깅 이미지는 debug_images/ 폴더에 저장되었습니다")
    logger.info("=" * 70)


async def main():
    """메인 함수"""
    # 테스트할 이미지 선택
    test_images = [
        "test_img.JPEG",  # MPO 형식
        "BlackMarble_2016_1400m_africa_m_labeled_optimized.jpg"  # 압축된 이미지
    ]
    
    # 사용 가능한 이미지 표시
    print("\n사용 가능한 테스트 이미지:")
    available_images = []
    for img in test_images:
        if os.path.exists(img):
            size = os.path.getsize(img) / 1024
            print(f"  ✅ {img} ({size:.2f} KB)")
            available_images.append(img)
        else:
            print(f"  ❌ {img} (없음)")
    
    if not available_images:
        print("\n⚠️ 테스트할 이미지가 없습니다.")
        return
    
    # 첫 번째 이미지로 테스트
    test_image = available_images[0]
    print(f"\n🚀 {test_image}로 테스트 시작...\n")
    
    await test_text_recognition(test_image)


if __name__ == "__main__":
    asyncio.run(main())