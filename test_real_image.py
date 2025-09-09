#!/usr/bin/env python3
"""
실제 이미지로 최적화 테스트

test_img.JPEG 파일을 사용하여 이미지 최적화 기능 검증
"""

import os
import sys
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

# 로깅 설정은 위에서 완료


def test_real_image():
    """실제 이미지로 최적화 테스트"""
    
    # 테스트 이미지 경로
    test_image_path = "test_img.JPEG"
    
    if not os.path.exists(test_image_path):
        print(f"❌ 테스트 이미지를 찾을 수 없습니다: {test_image_path}")
        return
    
    # 원본 이미지 읽기
    with open(test_image_path, 'rb') as f:
        original_data = f.read()
    
    original_size = len(original_data)
    original_size_mb = original_size / (1024 * 1024)
    
    print("=" * 60)
    print("📷 원본 이미지 정보")
    print("=" * 60)
    
    # PIL로 이미지 정보 확인
    with Image.open(test_image_path) as img:
        print(f"• 파일명: {test_image_path}")
        print(f"• 형식: {img.format}")
        print(f"• 모드: {img.mode}")
        print(f"• 크기: {img.size[0]} x {img.size[1]} 픽셀")
        print(f"• 파일 크기: {original_size_mb:.2f} MB ({original_size:,} bytes)")
        print(f"• Gemini 지원 형식: {is_supported_format(img.format)}")
        
        # EXIF 정보 확인
        exif = img.getexif()
        if exif:
            print(f"• EXIF 데이터: {len(exif)} 항목")
    
    print("\n" + "=" * 60)
    print("🔧 이미지 최적화 수행")
    print("=" * 60)
    
    # 최적화 수행
    optimized_data = optimize_image_for_gemini(original_data)
    
    optimized_size = len(optimized_data)
    optimized_size_mb = optimized_size / (1024 * 1024)
    
    # 최적화된 이미지 정보
    with Image.open(io.BytesIO(optimized_data)) as img:
        print(f"• 최적화 후 형식: {img.format}")
        print(f"• 최적화 후 모드: {img.mode}")
        print(f"• 최적화 후 크기: {img.size[0]} x {img.size[1]} 픽셀")
        print(f"• 최적화 후 파일 크기: {optimized_size_mb:.2f} MB ({optimized_size:,} bytes)")
    
    # 압축 결과
    compression_ratio = (1 - optimized_size / original_size) * 100
    
    print("\n" + "=" * 60)
    print("📊 최적화 결과")
    print("=" * 60)
    print(f"• 원본 크기: {original_size_mb:.2f} MB")
    print(f"• 최적화 크기: {optimized_size_mb:.2f} MB")
    print(f"• 압축률: {compression_ratio:.1f}%")
    print(f"• 크기 비율: {optimized_size / original_size:.2%}")
    
    # 검증
    print("\n" + "=" * 60)
    print("✅ 검증 결과")
    print("=" * 60)
    
    # 10MB 이하 이미지는 압축하지 않아야 함
    if original_size_mb <= 10.0:
        if optimized_size == original_size:
            print("✅ 10MB 이하 이미지 - 압축 안 함 (정상)")
        elif abs(optimized_size - original_size) / original_size < 0.1:
            print("✅ 10MB 이하 이미지 - 형식 변환만 수행 (정상)")
        else:
            print(f"⚠️ 10MB 이하 이미지인데 크기가 크게 변경됨: {compression_ratio:.1f}% 압축")
    else:
        if optimized_size_mb <= 10.5:
            print("✅ 10MB 초과 이미지 - 10MB로 압축 (정상)")
        else:
            print(f"❌ 10MB 초과 이미지인데 압축 실패: {optimized_size_mb:.2f} MB")
    
    # 최적화된 이미지 저장 (선택적)
    save_optimized = input("\n💾 최적화된 이미지를 저장하시겠습니까? (y/n): ")
    if save_optimized.lower() == 'y':
        output_path = "test_img_optimized.jpg"
        with open(output_path, 'wb') as f:
            f.write(optimized_data)
        print(f"✅ 최적화된 이미지 저장: {output_path}")
    
    print("\n" + "=" * 60)
    print("🎉 테스트 완료")
    print("=" * 60)


def test_large_image_simulation():
    """대용량 이미지 시뮬레이션 테스트"""
    print("\n" + "=" * 60)
    print("🔬 대용량 이미지 시뮬레이션 테스트")
    print("=" * 60)
    
    # 15MB 크기의 이미지 생성
    print("• 15MB 테스트 이미지 생성 중...")
    
    # 고해상도 이미지 생성 (약 15MB)
    width, height = 5000, 5000
    img = Image.new('RGB', (width, height), color='blue')
    
    # JPEG로 저장하여 크기 조절
    buffer = io.BytesIO()
    quality = 95
    
    # 목표 크기에 도달할 때까지 품질 조정
    target_size = 15 * 1024 * 1024  # 15MB
    
    while quality > 50:
        buffer.seek(0)
        buffer.truncate()
        img.save(buffer, format='JPEG', quality=quality)
        current_size = len(buffer.getvalue())
        
        if current_size >= target_size:
            break
        quality -= 5
    
    large_image_data = buffer.getvalue()
    large_size_mb = len(large_image_data) / (1024 * 1024)
    
    print(f"• 생성된 이미지 크기: {large_size_mb:.2f} MB")
    print(f"• 해상도: {width} x {height}")
    
    # 최적화 수행
    print("• 최적화 수행 중...")
    optimized_data = optimize_image_for_gemini(large_image_data)
    optimized_size_mb = len(optimized_data) / (1024 * 1024)
    
    # 결과 확인
    with Image.open(io.BytesIO(optimized_data)) as img:
        print(f"• 최적화 후 크기: {optimized_size_mb:.2f} MB")
        print(f"• 최적화 후 해상도: {img.size[0]} x {img.size[1]}")
    
    # 검증
    if optimized_size_mb <= 10.5:
        print("✅ 대용량 이미지 압축 성공")
    else:
        print(f"❌ 압축 실패: {optimized_size_mb:.2f} MB (목표: 10MB)")
    
    compression_ratio = (1 - len(optimized_data) / len(large_image_data)) * 100
    print(f"• 압축률: {compression_ratio:.1f}%")


if __name__ == "__main__":
    try:
        # 실제 이미지 테스트
        test_real_image()
        
        # 대용량 이미지 시뮬레이션 테스트
        simulate = input("\n🔬 대용량 이미지 시뮬레이션 테스트를 수행하시겠습니까? (y/n): ")
        if simulate.lower() == 'y':
            test_large_image_simulation()
            
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()