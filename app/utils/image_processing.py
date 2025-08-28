"""
이미지 처리 유틸리티

답안지 OCR 처리를 위한 이미지 전처리 및 검증 기능

주요 기능:
- 이미지 형식 검증
- 파일 크기 제한 확인  
- 이미지 품질 평가
- Base64 인코딩/디코딩
- 이미지 최적화 처리
"""

import base64
import io
from typing import Tuple, Literal
from PIL import Image
import structlog

logger = structlog.get_logger("image_processing")

# 지원되는 이미지 형식 (대소문자 무관)
# MPO: iPhone에서 사용하는 Multi-Picture Object 형식 (스테레오/다중 이미지)
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "MPO"}

# 파일 크기 제한 (20MB)
MAX_FILE_SIZE = 20 * 1024 * 1024

# 이미지 해상도 제한
MAX_WIDTH = 8000
MAX_HEIGHT = 8000
MIN_WIDTH = 100
MIN_HEIGHT = 100


class ImageValidationError(Exception):
    """이미지 검증 오류"""
    pass


def validate_image_file(image_data: bytes) -> Tuple[str, int, int]:
    """
    이미지 파일 검증
    
    검증 항목:
    1. 파일 크기 제한 확인
    2. 이미지 형식 지원 여부  
    3. 이미지 해상도 제한 확인
    4. 손상된 이미지 파일 검사
    
    Args:
        image_data: 이미지 바이너리 데이터
        
    Returns:
        Tuple[str, int, int]: (형식, 너비, 높이)
        
    Raises:
        ImageValidationError: 검증 실패 시
    """
    # 1. 파일 크기 검사
    if len(image_data) > MAX_FILE_SIZE:
        raise ImageValidationError(
            f"파일 크기가 너무 큽니다. 최대 {MAX_FILE_SIZE // 1024 // 1024}MB까지 지원됩니다."
        )
    
    if len(image_data) == 0:
        raise ImageValidationError("빈 파일입니다.")
    
    try:
        # 2. 이미지 열기 및 형식 확인
        with Image.open(io.BytesIO(image_data)) as img:
            image_format = img.format
            width, height = img.size
            
            # 3. 지원 형식 확인 (대소문자 무관)
            if image_format is None or image_format.upper() not in SUPPORTED_FORMATS:
                raise ImageValidationError(
                    f"지원되지 않는 이미지 형식입니다. "
                    f"지원 형식: {', '.join(SUPPORTED_FORMATS)}"
                )
            
            # 4. 해상도 제한 확인
            if width > MAX_WIDTH or height > MAX_HEIGHT:
                raise ImageValidationError(
                    f"이미지 해상도가 너무 큽니다. "
                    f"최대 해상도: {MAX_WIDTH}x{MAX_HEIGHT}"
                )
            
            if width < MIN_WIDTH or height < MIN_HEIGHT:
                raise ImageValidationError(
                    f"이미지 해상도가 너무 작습니다. "
                    f"최소 해상도: {MIN_WIDTH}x{MIN_HEIGHT}"
                )
            
            logger.info(
                "이미지 검증 완료",
                format=image_format,
                size_kb=len(image_data) // 1024,
                resolution=f"{width}x{height}",
                is_mpo=image_format == "MPO"
            )
            
            return image_format.upper() if image_format else "UNKNOWN", width, height
    
    except IOError as e:
        raise ImageValidationError(f"손상된 이미지 파일입니다: {str(e)}")
    except Exception as e:
        raise ImageValidationError(f"이미지 처리 중 오류 발생: {str(e)}")


def assess_image_quality(
    image_data: bytes, 
    width: int, 
    height: int
) -> Literal["good", "fair", "poor"]:
    """
    이미지 품질 평가
    
    평가 기준:
    - 해상도 기반 평가
    - 파일 크기 대비 해상도 비율
    - 압축률 추정
    
    Args:
        image_data: 이미지 바이너리 데이터
        width: 이미지 너비
        height: 이미지 높이
        
    Returns:
        str: 품질 등급 ("good", "fair", "poor")
    """
    file_size_kb = len(image_data) / 1024
    pixel_count = width * height
    
    # 해상도 기반 평가
    if width >= 2000 and height >= 1500:
        resolution_score = 3  # 고해상도
    elif width >= 1200 and height >= 900:
        resolution_score = 2  # 중간 해상도
    else:
        resolution_score = 1  # 저해상도
    
    # 압축률 추정 (KB당 픽셀 수)
    pixels_per_kb = pixel_count / file_size_kb if file_size_kb > 0 else 0
    
    if pixels_per_kb > 1000:  # 고압축 (품질 저하 가능)
        compression_score = 1
    elif pixels_per_kb > 300:  # 적절한 압축
        compression_score = 2  
    else:  # 저압축 (고품질)
        compression_score = 3
    
    # 종합 점수 계산
    total_score = resolution_score + compression_score
    
    if total_score >= 5:
        quality = "good"
    elif total_score >= 3:
        quality = "fair" 
    else:
        quality = "poor"
    
    logger.info(
        "이미지 품질 평가 완료",
        quality=quality,
        resolution_score=resolution_score,
        compression_score=compression_score,
        pixels_per_kb=round(pixels_per_kb, 1),
        file_size_kb=round(file_size_kb, 1)
    )
    
    return quality


def encode_image_to_base64(image_data: bytes) -> str:
    """
    이미지를 Base64로 인코딩
    
    Args:
        image_data: 이미지 바이너리 데이터
        
    Returns:
        str: Base64 인코딩된 문자열
    """
    return base64.b64encode(image_data).decode('utf-8')


def optimize_image_for_gemini(image_data: bytes) -> bytes:
    """
    Gemini API 최적화를 위한 이미지 전처리
    
    최적화 작업:
    1. JPEG 형식으로 변환 (API 효율성)
    2. 과도한 해상도 축소 (토큰 절약)
    3. 품질 최적화 (인식률 vs 파일크기)
    
    Args:
        image_data: 원본 이미지 데이터
        
    Returns:
        bytes: 최적화된 이미지 데이터
    """
    try:
        with Image.open(io.BytesIO(image_data)) as img:
            # RGB 모드로 변환 (JPEG 호환성)
            if img.mode in ('RGBA', 'LA', 'P'):
                # 투명도가 있는 경우 흰색 배경과 합성
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 해상도 최적화 (Gemini API 효율성)
            width, height = img.size
            if width > 2048 or height > 2048:
                # 종횡비 유지하며 축소
                ratio = min(2048 / width, 2048 / height)
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                logger.info(
                    "이미지 해상도 최적화",
                    original=f"{width}x{height}",
                    optimized=f"{new_width}x{new_height}",
                    ratio=round(ratio, 3)
                )
            
            # JPEG로 저장 (품질 85% - 인식률과 파일크기 균형)
            output_buffer = io.BytesIO()
            img.save(output_buffer, format='JPEG', quality=85, optimize=True)
            optimized_data = output_buffer.getvalue()
            
            compression_ratio = len(optimized_data) / len(image_data)
            logger.info(
                "이미지 최적화 완료",
                original_size_kb=len(image_data) // 1024,
                optimized_size_kb=len(optimized_data) // 1024,
                compression_ratio=round(compression_ratio, 3)
            )
            
            return optimized_data
            
    except Exception as e:
        logger.warning("이미지 최적화 실패, 원본 사용", error=str(e))
        return image_data