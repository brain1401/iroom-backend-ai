#!/usr/bin/env python3
"""
대용량 이미지 압축 테스트

19MB PNG 이미지를 10MB로 압축하는 테스트
"""

import os
import sys
import time
from pathlib import Path
from PIL import Image
import io

# 프로젝트 경로 추가
sys.path.insert(0, str(Path(__file__).parent))

from app.utils.image_processing import optimize_image_for_gemini, is_supported_format

import logging

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def format_size(bytes_size):
    """바이트를 사람이 읽기 쉬운 형식으로 변환"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"


def test_large_image(image_path):
    """대용량 이미지 압축 테스트"""
    
    if not os.path.exists(image_path):
        print(f"❌ 이미지를 찾을 수 없습니다: {image_path}")
        return
    
    print("=" * 70)
    print("🖼️  대용량 이미지 압축 테스트")
    print("=" * 70)
    
    # 원본 이미지 정보
    print("\n📊 원본 이미지 정보")
    print("-" * 70)
    
    with open(image_path, 'rb') as f:
        original_data = f.read()
    
    original_size = len(original_data)
    
    with Image.open(image_path) as img:
        print(f"• 파일명: {os.path.basename(image_path)}")
        print(f"• 형식: {img.format}")
        print(f"• 모드: {img.mode}")
        print(f"• 해상도: {img.size[0]:,} x {img.size[1]:,} 픽셀")
        print(f"• 총 픽셀: {img.size[0] * img.size[1]:,}")
        print(f"• 파일 크기: {format_size(original_size)}")
        print(f"• Gemini 지원: {'✅' if is_supported_format(img.format) else '❌'}")
        
        # 추가 정보
        if hasattr(img, 'info'):
            info = img.info
            if info:
                print(f"• 메타데이터: {len(info)} 항목")
    
    # 압축 수행
    print("\n⚙️  이미지 최적화 진행")
    print("-" * 70)
    
    start_time = time.time()
    print("• 최적화 시작...")
    
    optimized_data = optimize_image_for_gemini(original_data)
    
    elapsed_time = time.time() - start_time
    optimized_size = len(optimized_data)
    
    print(f"• 처리 시간: {elapsed_time:.2f}초")
    
    # 최적화 결과 분석
    print("\n📈 최적화 결과")
    print("-" * 70)
    
    with Image.open(io.BytesIO(optimized_data)) as img:
        print(f"• 최종 형식: {img.format}")
        print(f"• 최종 모드: {img.mode}")
        print(f"• 최종 해상도: {img.size[0]:,} x {img.size[1]:,} 픽셀")
        print(f"• 최종 크기: {format_size(optimized_size)}")
    
    # 압축 통계
    compression_ratio = (1 - optimized_size / original_size) * 100
    size_reduction = original_size - optimized_size
    
    print("\n📉 압축 통계")
    print("-" * 70)
    print(f"• 원본 크기: {format_size(original_size)}")
    print(f"• 압축 크기: {format_size(optimized_size)}")
    print(f"• 크기 감소: {format_size(size_reduction)}")
    print(f"• 압축률: {compression_ratio:.1f}%")
    print(f"• 크기 비율: {optimized_size / original_size:.1%}")
    
    # 성능 지표
    if elapsed_time > 0:
        mb_per_sec = (original_size / (1024 * 1024)) / elapsed_time
        print(f"• 처리 속도: {mb_per_sec:.2f} MB/초")
    
    # 검증
    print("\n✅ 검증 결과")
    print("-" * 70)
    
    original_size_mb = original_size / (1024 * 1024)
    optimized_size_mb = optimized_size / (1024 * 1024)
    
    if original_size_mb > 10.0:
        # 10MB 초과 이미지
        if optimized_size_mb <= 10.5:
            print(f"✅ 성공: 10MB 초과 이미지를 {optimized_size_mb:.2f}MB로 압축")
            if optimized_size_mb >= 9.0:
                print("✅ 최적: 목표 크기(10MB)에 근접하게 압축됨")
            else:
                print("⚠️  주의: 과도하게 압축됨 (목표: 10MB)")
        else:
            print(f"❌ 실패: 압축 후에도 {optimized_size_mb:.2f}MB (목표: 10MB)")
    else:
        # 10MB 이하 이미지
        if abs(optimized_size - original_size) / original_size < 0.1:
            print("✅ 성공: 10MB 이하 이미지 - 최소한의 변경만 수행")
        else:
            print(f"⚠️  주의: 10MB 이하인데 크기가 크게 변경됨")
    
    # 최적화된 이미지 저장 옵션
    print("\n💾 저장 옵션")
    print("-" * 70)
    
    save = input("최적화된 이미지를 저장하시겠습니까? (y/n): ")
    if save.lower() == 'y':
        base_name = os.path.splitext(image_path)[0]
        output_path = f"{base_name}_optimized.jpg"
        
        with open(output_path, 'wb') as f:
            f.write(optimized_data)
        
        print(f"✅ 저장 완료: {output_path}")
        print(f"   크기: {format_size(optimized_size)}")
    
    print("\n" + "=" * 70)
    print("🎉 테스트 완료!")
    print("=" * 70)


if __name__ == "__main__":
    # 테스트할 이미지 목록
    test_images = [
        "BlackMarble_2016_1400m_africa_m_labeled.png",  # 19MB 대용량 이미지
        "test_img.JPEG"  # 2MB MPO 이미지
    ]
    
    print("🔍 사용 가능한 테스트 이미지:")
    for i, img in enumerate(test_images, 1):
        if os.path.exists(img):
            size = os.path.getsize(img)
            print(f"  {i}. {img} ({format_size(size)})")
        else:
            print(f"  {i}. {img} (파일 없음)")
    
    # 대용량 이미지 우선 테스트
    large_image = "BlackMarble_2016_1400m_africa_m_labeled.png"
    
    if os.path.exists(large_image):
        print(f"\n🚀 {large_image} 테스트 시작...\n")
        test_large_image(large_image)
    else:
        print(f"\n⚠️  {large_image} 파일을 찾을 수 없습니다.")
        
        # 다른 이미지로 테스트
        if os.path.exists("test_img.JPEG"):
            test_another = input("\ntest_img.JPEG로 테스트하시겠습니까? (y/n): ")
            if test_another.lower() == 'y':
                test_large_image("test_img.JPEG")