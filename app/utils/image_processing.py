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
            
            # MPO 형식 경고 (iPhone 멀티 이미지)
            if image_format == "MPO":
                logger.warning(
                    "MPO 형식 감지 (iPhone 멀티 이미지)",
                    format=image_format,
                    resolution=f"{width}x{height}",
                    recommendation="JPEG 변환 권장"
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


def compress_image_to_target_size(
    image_data: bytes,
    target_size_mb: float = 10.0,
    max_width: int = 2048,
    max_height: int = 2048,
    min_quality: int = 70
) -> bytes:
    """
    이미지를 목표 크기로 압축 (Pillow 최적화 v2.0)
    
    Pillow best practices:
    - thumbnail()로 효율적인 리사이징
    - optimize=True로 파일 크기 최소화
    - 이진 탐색으로 빠른 품질 수렴
    - progressive=False로 빠른 로딩
    
    Args:
        image_data: 원본 이미지 데이터
        target_size_mb: 목표 크기 (MB), 기본 10MB
        max_width: 최대 너비 제한
        max_height: 최대 높이 제한
        min_quality: 최소 품질 (기본 70)
        
    Returns:
        압축된 이미지 데이터
    """
    target_bytes = int(target_size_mb * 1024 * 1024)
    current_size_mb = len(image_data) / (1024 * 1024)
    
    # 이미 목표 크기 이하면 원본 반환
    if current_size_mb <= target_size_mb:
        logger.info(
            "압축 불필요 - 이미 목표 크기 이하",
            current_mb=round(current_size_mb, 2),
            target_mb=target_size_mb
        )
        return image_data
    
    try:
        with Image.open(io.BytesIO(image_data)) as img:
            # RGB 변환 (JPEG 호환성)
            if img.mode in ('RGBA', 'LA', 'P'):
                if img.mode == 'P':
                    img = img.convert('RGBA')
                    
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode in ('RGBA', 'LA'):
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            width, height = img.size
            
            # 1단계: 해상도 조정 (필요시)
            if width > max_width or height > max_height:
                # thumbnail 메서드로 비율 유지 리사이징
                img_resized = img.copy()
                img_resized.thumbnail(
                    (max_width, max_height),
                    Image.Resampling.LANCZOS,
                    reducing_gap=2.0  # 2단계 리사이징 최적화
                )
                
                logger.info(
                    "해상도 조정",
                    original=f"{width}x{height}",
                    resized=f"{img_resized.size[0]}x{img_resized.size[1]}"
                )
                img = img_resized
            
            # 2단계: 품질 조정으로 목표 크기 달성
            # 이진 탐색으로 최적 품질 찾기
            low_quality = min_quality
            high_quality = 95
            best_quality = high_quality
            best_data = None
            
            # 초기 추정: 크기 비율로 품질 예측
            size_ratio = target_size_mb / current_size_mb
            if size_ratio < 0.5:
                # 50% 이상 압축 필요
                high_quality = 85
                best_quality = 80
            elif size_ratio < 0.7:
                # 30% 압축 필요
                best_quality = 90
            
            attempts = 0
            max_attempts = 7  # 최대 시도 횟수
            
            while low_quality <= high_quality and attempts < max_attempts:
                attempts += 1
                mid_quality = (low_quality + high_quality) // 2
                
                # 압축 시도
                output_buffer = io.BytesIO()
                save_params = {
                    'format': 'JPEG',
                    'quality': mid_quality,
                    'optimize': True,  # 파일 크기 최적화
                    'progressive': False,  # 빠른 로딩
                }
                
                # 품질이 낮을수록 더 aggressive한 subsampling
                if mid_quality < 85:
                    save_params['subsampling'] = 2  # 4:2:0
                else:
                    save_params['subsampling'] = 1  # 4:2:2
                
                img.save(output_buffer, **save_params)
                compressed_data = output_buffer.getvalue()
                compressed_size = len(compressed_data)
                
                logger.debug(
                    f"압축 시도 {attempts}/{max_attempts}",
                    quality=mid_quality,
                    size_mb=round(compressed_size / (1024 * 1024), 2),
                    target_mb=target_size_mb
                )
                
                if compressed_size <= target_bytes:
                    # 목표 크기 이하 - 더 높은 품질 시도
                    best_data = compressed_data
                    best_quality = mid_quality
                    
                    # 90% 이상 달성시 종료
                    if compressed_size > target_bytes * 0.9:
                        logger.info(
                            "최적 품질 발견",
                            quality=best_quality,
                            size_mb=round(compressed_size / (1024 * 1024), 2)
                        )
                        break
                    
                    low_quality = mid_quality + 1
                else:
                    # 목표 크기 초과 - 품질 낮춤
                    high_quality = mid_quality - 1
            
            # 최종 결과
            if best_data:
                final_size_mb = len(best_data) / (1024 * 1024)
                compression_ratio = len(best_data) / len(image_data)
                
                logger.info(
                    "이미지 압축 성공",
                    original_mb=round(current_size_mb, 2),
                    final_mb=round(final_size_mb, 2),
                    quality=best_quality,
                    compression_ratio=round(compression_ratio, 3),
                    attempts=attempts
                )
                return best_data
            else:
                # 목표 달성 실패 - 최소 품질로 재시도
                output_buffer = io.BytesIO()
                img.save(
                    output_buffer,
                    format='JPEG',
                    quality=min_quality,
                    optimize=True,
                    progressive=False,
                    subsampling=2  # 최대 압축
                )
                fallback_data = output_buffer.getvalue()
                
                logger.warning(
                    "목표 크기 달성 실패 - 최소 품질 적용",
                    quality=min_quality,
                    size_mb=round(len(fallback_data) / (1024 * 1024), 2),
                    target_mb=target_size_mb
                )
                return fallback_data
                
    except Exception as e:
        logger.error(
            "이미지 압축 실패",
            error=str(e),
            original_size_mb=round(current_size_mb, 2)
        )
        # 실패시 원본 반환
        return image_data


def is_supported_format(format: str) -> bool:
    """
    Gemini API가 지원하는 이미지 형식인지 확인
    
    Args:
        format: 이미지 형식 (JPEG, PNG, WebP, GIF 등)
        
    Returns:
        지원 여부
    """
    supported_formats = {'JPEG', 'PNG', 'WEBP', 'GIF'}
    return format.upper() in supported_formats

def optimize_image_for_gemini(image_data: bytes) -> bytes:
    """
    Gemini API 최적화를 위한 고성능 이미지 전처리 (v5.1 - 개선된 압축)
    
    Pillow best practices 적용:
    - thumbnail() 메서드로 단계적 리사이징
    - draft() 메서드로 JPEG 디코딩 최적화
    - LANCZOS 필터로 고품질 리샘플링
    - optimize=True로 파일 크기 최소화
    
    처리 정책:
    - MPO/HEIC → JPEG 변환 (iPhone 호환성)
    - 10MB 미만: 압축/리사이징 안 함
    - 10MB 이상: 10MB로 압축 (해상도는 가능한 유지)
    
    Args:
        image_data: 원본 이미지 데이터
        
    Returns:
        bytes: 최적화된 이미지 데이터
    """
    original_size_mb = len(image_data) / (1024 * 1024)
    
    try:
        # BytesIO로 이미지 열기
        img_buffer = io.BytesIO(image_data)
        
        with Image.open(img_buffer) as img:
            # JPEG인 경우 draft 모드로 빠른 디코딩 (10MB 초과시)
            original_format = img.format
            width, height = img.size
            
            if original_format == 'JPEG' and original_size_mb > 10.0:
                # draft 모드로 대략적인 크기 조정 (JPEG 최적화)
                img.draft('RGB', (4096, 4096))  # 더 큰 크기 유지
                logger.debug(
                    "JPEG draft 모드 적용",
                    original=f"{width}x{height}",
                    draft=f"{img.size[0]}x{img.size[1]}"
                )
            
            # MPO 형식 처리 (iPhone 멀티 프레임)
            format_needs_conversion = False
            if original_format == 'MPO':
                logger.warning(
                    "MPO 형식 감지 - JPEG로 변환",
                    resolution=f"{width}x{height}"
                )
                img.seek(0)  # 첫 프레임
                img = img.copy()
                format_needs_conversion = True
            
            # HEIC/HEIF 형식 처리
            elif original_format in ['HEIC', 'HEIF']:
                logger.warning(
                    "HEIC/HEIF 형식 감지 - JPEG로 변환",
                    original_format=original_format
                )
                format_needs_conversion = True
            
            # 미지원 형식 처리
            elif original_format not in ['JPEG', 'PNG', 'WEBP', 'GIF']:
                logger.warning(
                    "미지원 형식 - JPEG로 변환",
                    original_format=original_format or "UNKNOWN"
                )
                format_needs_conversion = True
            
            # RGB 모드 변환 (JPEG 호환성)
            if img.mode in ('RGBA', 'LA', 'P'):
                # 투명 배경을 흰색으로
                if img.mode == 'P':
                    img = img.convert('RGBA')
                
                if img.mode in ('RGBA', 'LA'):
                    # 알파 채널이 있는 경우 흰색 배경과 합성
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    # 알파 채널을 마스크로 사용
                    background.paste(img, mask=img.split()[-1] if 'A' in img.mode else None)
                    img = background
                else:
                    img = img.convert('RGB')
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 10MB 이하 처리
            if original_size_mb <= 10.0:
                if format_needs_conversion or original_format not in ['JPEG', 'PNG', 'WEBP', 'GIF']:
                    # 형식 변환만 필요한 경우
                    output_buffer = io.BytesIO()
                    save_format = 'JPEG' if format_needs_conversion else original_format
                    
                    # 품질 설정
                    save_kwargs = {
                        'format': save_format,
                        'optimize': True  # Pillow 최적화
                    }
                    
                    if save_format == 'JPEG':
                        save_kwargs['quality'] = 95
                        save_kwargs['progressive'] = False  # 빠른 로딩
                    
                    img.save(output_buffer, **save_kwargs)
                    optimized_data = output_buffer.getvalue()
                    
                    logger.info(
                        "형식 변환 완료 (10MB 이하)",
                        original_format=original_format,
                        final_format=save_format,
                        size_mb=round(len(optimized_data) / (1024 * 1024), 2)
                    )
                    return optimized_data
                else:
                    # 변환 불필요 - 원본 반환
                    logger.info(
                        "최적화 불필요 - 원본 유지",
                        size_mb=round(original_size_mb, 2),
                        format=original_format
                    )
                    return image_data
            
            # 10MB 초과 - 압축 필요
            logger.info(
                "대용량 이미지 압축 시작",
                original_size_mb=round(original_size_mb, 2),
                target_size_mb=10.0
            )
            
            # 단계별 압축 전략
            # 1. 먼저 품질로만 압축 시도 (해상도 유지)
            target_bytes = 10 * 1024 * 1024
            
            # 품질만 조정해서 압축 시도
            output_buffer = io.BytesIO()
            best_data = None
            best_size = float('inf')
            current_data: bytes = b''  # 타입 안전성을 위한 초기화
            
            # 높은 품질부터 시작
            for quality in [95, 90, 85, 80, 75, 70]:
                output_buffer.seek(0)
                output_buffer.truncate()
                
                img.save(
                    output_buffer,
                    format='JPEG',
                    quality=quality,
                    optimize=True,
                    progressive=False,
                    subsampling=2 if quality < 85 else 1
                )
                
                current_data = output_buffer.getvalue()
                current_size = len(current_data)
                
                logger.debug(
                    f"품질 압축 시도",
                    quality=quality,
                    size_mb=round(current_size / (1024 * 1024), 2)
                )
                
                if current_size <= target_bytes:
                    # 목표 달성
                    best_data = current_data
                    best_size = current_size
                    
                    if current_size > target_bytes * 0.7:
                        # 70% 이상이면 충분
                        logger.info(
                            "품질 조정으로 목표 달성",
                            quality=quality,
                            size_mb=round(best_size / (1024 * 1024), 2)
                        )
                        return best_data
                    # 더 높은 품질 시도 가능
                else:
                    # 목표 초과 - 리사이징 필요
                    break
            
            # 2. 품질로만 안 되면 리사이징 + 품질 조정
            if not best_data or best_size > target_bytes:
                # 적절한 리사이즈 비율 계산
                # 목표: 파일 크기를 10MB로 줄이기
                size_ratio = target_bytes / len(image_data)
                
                # 리사이즈 비율 추정 (보수적으로)
                # 파일 크기는 대략 픽셀 수에 비례
                resize_ratio = min(1.0, (size_ratio * 2) ** 0.5)  # 보수적 추정
                
                # 최소 해상도 보장
                max_dimension = max(width, height)
                if max_dimension * resize_ratio < 2048:
                    resize_ratio = 2048 / max_dimension
                
                # 최대 해상도 제한
                if max_dimension * resize_ratio > 4096:
                    resize_ratio = 4096 / max_dimension
                
                new_width = int(width * resize_ratio)
                new_height = int(height * resize_ratio)
                
                logger.info(
                    "리사이징 수행",
                    original=f"{width}x{height}",
                    resized=f"{new_width}x{new_height}",
                    ratio=round(resize_ratio, 3)
                )
                
                # 리사이징
                img_resized = img.resize(
                    (new_width, new_height),
                    Image.Resampling.LANCZOS
                )
                
                # 리사이징 후 품질 조정으로 미세 조정
                for quality in [95, 90, 85, 80, 75]:
                    output_buffer.seek(0)
                    output_buffer.truncate()
                    
                    img_resized.save(
                        output_buffer,
                        format='JPEG',
                        quality=quality,
                        optimize=True,
                        progressive=False,
                        subsampling=2 if quality < 85 else 1
                    )
                    
                    current_data = output_buffer.getvalue()
                    current_size = len(current_data)
                    
                    logger.debug(
                        f"리사이징 후 품질 조정",
                        quality=quality,
                        size_mb=round(current_size / (1024 * 1024), 2)
                    )
                    
                    if current_size <= target_bytes:
                        best_data = current_data
                        best_size = current_size
                        
                        if current_size > target_bytes * 0.7:
                            # 70% 이상이면 충분
                            break
                    else:
                        # 이전 best_data 사용
                        if best_data:
                            break
            
            # 최종 결과
            if best_data:
                final_size_mb = best_size / (1024 * 1024)
                logger.info(
                    "이미지 압축 완료",
                    original_size_mb=round(original_size_mb, 2),
                    final_size_mb=round(final_size_mb, 2),
                    compression_ratio=round(best_size / len(image_data), 3)
                )
                return best_data
            else:
                # 압축 실패시 최소 품질로 재시도
                logger.warning(
                    "목표 크기 달성 실패 - 최선의 결과 반환",
                    size_mb=round(len(current_data) / (1024 * 1024), 2)
                )
                return current_data
            
    except Exception as e:
        logger.error(
            "이미지 최적화 실패",
            error=str(e),
            traceback=True
        )
        return image_data