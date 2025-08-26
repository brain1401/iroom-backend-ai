"""
OCR 모듈 테스트

한국어 답안지 OCR 처리 기능 테스트

테스트 범위:
- 이미지 검증 및 처리
- OCR 모델 생성
- API 엔드포인트
- 오류 처리
"""

import pytest
import io
from PIL import Image
from fastapi.testclient import TestClient

from app.server import create_app
from app.config.settings import Settings
from app.utils.image_processing import (
    validate_image_file,
    assess_image_quality,
    encode_image_to_base64,
    optimize_image_for_gemini,
    ImageValidationError,
    MAX_FILE_SIZE
)


@pytest.fixture
def test_settings():
    """테스트용 설정 생성"""
    return Settings(
        gemini_api_key="test_key_for_testing",
        require_api_key=False,
        rate_limit_enabled=False,
        debug=True
    )


@pytest.fixture
def test_app(test_settings):
    """테스트용 FastAPI 앱 생성"""
    return create_app(test_settings)


@pytest.fixture
def test_client(test_app):
    """테스트 클라이언트 생성"""
    return TestClient(test_app)


@pytest.fixture
def sample_image():
    """테스트용 샘플 이미지 생성"""
    # 800x600 흰색 배경 이미지
    img = Image.new('RGB', (800, 600), color='white')
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=85)
    return buffer.getvalue()


@pytest.fixture
def large_image():
    """크기 제한 테스트용 큰 이미지"""
    # 5000x4000 이미지 (메모리 절약을 위해 실제로는 작게 생성)
    img = Image.new('RGB', (100, 100), color='red')
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=100)
    # 가상으로 큰 데이터 생성 (MAX_FILE_SIZE 초과)
    large_data = b'0' * (MAX_FILE_SIZE + 1)
    return large_data


class TestImageProcessing:
    """이미지 처리 유틸리티 테스트"""
    
    def test_validate_valid_image(self, sample_image):
        """유효한 이미지 검증 테스트"""
        format_name, width, height = validate_image_file(sample_image)
        
        assert format_name == 'JPEG'
        assert width == 800
        assert height == 600
    
    def test_validate_large_image(self, large_image):
        """파일 크기 제한 테스트"""
        with pytest.raises(ImageValidationError, match="파일 크기가 너무 큽니다"):
            validate_image_file(large_image)
    
    def test_validate_empty_image(self):
        """빈 파일 테스트"""
        with pytest.raises(ImageValidationError, match="빈 파일입니다"):
            validate_image_file(b'')
    
    def test_validate_corrupted_image(self):
        """손상된 이미지 테스트"""
        corrupted_data = b'not_an_image_file'
        with pytest.raises(ImageValidationError, match="손상된 이미지 파일입니다"):
            validate_image_file(corrupted_data)
    
    def test_assess_image_quality(self, sample_image):
        """이미지 품질 평가 테스트"""
        quality = assess_image_quality(sample_image, 800, 600)
        assert quality in ['good', 'fair', 'poor']
    
    def test_encode_to_base64(self, sample_image):
        """Base64 인코딩 테스트"""
        encoded = encode_image_to_base64(sample_image)
        assert isinstance(encoded, str)
        assert len(encoded) > 0
        # Base64 문자열 검증
        import base64
        decoded = base64.b64decode(encoded)
        assert decoded == sample_image
    
    def test_optimize_image(self, sample_image):
        """이미지 최적화 테스트"""
        optimized = optimize_image_for_gemini(sample_image)
        assert isinstance(optimized, bytes)
        assert len(optimized) > 0
        # 최적화된 이미지가 유효한지 확인
        validate_image_file(optimized)


class TestOCRAPI:
    """OCR API 엔드포인트 테스트"""
    
    def test_ocr_health_without_api_key(self, test_client):
        """OCR 헬스체크 테스트 (API 키 없음)"""
        response = test_client.get("/text-recognition/v2/health")
        
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["service"] == "ocr_v2"
    
    def test_ocr_health_with_mock_key(self, test_client):
        """OCR 헬스체크 테스트 (모의 API 키)"""
        # 실제 API 키가 없으므로 실패 예상
        response = test_client.get("/text-recognition/v2/health")
        assert response.status_code == 503
    
    def test_upload_valid_image_without_api_key(self, test_client, sample_image):
        """유효한 이미지 업로드 테스트 (API 키 없음)"""
        files = {"file": ("test.jpg", sample_image, "image/jpeg")}
        response = test_client.post("/text-recognition/v2/answer-sheet", files=files)
        
        # API 키가 없어서 503 에러 예상
        assert response.status_code == 503
        data = response.json()
        assert data["error_code"] == "GEMINI_API_UNAVAILABLE"
    
    def test_upload_large_image(self, test_client, large_image):
        """큰 이미지 업로드 테스트"""
        files = {"file": ("large.jpg", large_image, "image/jpeg")}
        response = test_client.post("/text-recognition/v2/answer-sheet", files=files)
        
        assert response.status_code == 400
        data = response.json()
        assert data["error_code"] == "IMAGE_VALIDATION_FAILED"
        assert "파일 크기가 너무 큽니다" in data["error_message"]
    
    def test_upload_invalid_file(self, test_client):
        """잘못된 파일 형식 업로드 테스트"""
        invalid_data = b'This is not an image file'
        files = {"file": ("test.txt", invalid_data, "text/plain")}
        response = test_client.post("/text-recognition/v2/answer-sheet", files=files)
        
        assert response.status_code == 400
        data = response.json()
        assert data["error_code"] == "IMAGE_VALIDATION_FAILED"
    
    def test_upload_no_file(self, test_client):
        """파일 없이 업로드 테스트"""
        response = test_client.post("/text-recognition/v2/answer-sheet")
        
        assert response.status_code == 422  # FastAPI 검증 오류
    
    def test_api_endpoints_exist(self, test_client):
        """OCR API 엔드포인트 존재 확인"""
        # OpenAPI 스키마 확인
        response = test_client.get("/openapi.json")
        assert response.status_code == 200
        
        openapi_data = response.json()
        paths = openapi_data["paths"]
        
        # OCR 엔드포인트 존재 확인
        assert "/text-recognition/v2/answer-sheet" in paths
        assert "/text-recognition/v2/health" in paths
        
        # POST 메서드 확인
        assert "post" in paths["/text-recognition/v2/answer-sheet"]
        assert "get" in paths["/text-recognition/v2/health"]


class TestOCRModels:
    """OCR 데이터 모델 테스트"""
    
    def test_ocr_answer_model(self):
        """OCRAnswer 모델 테스트"""
        from app.models.ocr import OCRAnswer
        
        answer = OCRAnswer(
            question_number=1,
            question_label="주1",
            extracted_text="테스트 답안",
            confidence=0.95
        )
        
        assert answer.question_number == 1
        assert answer.question_label == "주1"
        assert answer.extracted_text == "테스트 답안"
        assert answer.confidence == 0.95
    
    def test_ocr_answer_validation(self):
        """OCRAnswer 모델 검증 테스트"""
        from app.models.ocr import OCRAnswer
        import pytest
        from pydantic import ValidationError
        
        # 잘못된 question_number (범위 초과)
        with pytest.raises(ValidationError):
            OCRAnswer(
                question_number=8,  # 1-7 범위 초과
                question_label="주8",
                extracted_text="테스트",
                confidence=0.5
            )
        
        # 잘못된 confidence (범위 초과)
        with pytest.raises(ValidationError):
            OCRAnswer(
                question_number=1,
                question_label="주1",
                extracted_text="테스트",
                confidence=1.5  # 0.0-1.0 범위 초과
            )
    
    def test_ocr_response_model(self):
        """OCRAnswerResponse 모델 테스트"""
        from app.models.ocr import OCRAnswerResponse, OCRAnswer, OCRMetadata
        
        answers = [
            OCRAnswer(
                question_number=1,
                question_label="주1", 
                extracted_text="답안1",
                confidence=0.9
            )
        ]
        
        metadata = OCRMetadata(
            image_quality="good",
            processing_time_ms=1500,
            total_questions_detected=1  # answers 배열 길이와 일치
        )
        
        response = OCRAnswerResponse(
            answers=answers,
            metadata=metadata
        )
        
        assert len(response.answers) == 1
        assert response.answers[0].extracted_text == "답안1"
        assert response.metadata.image_quality == "good"
        assert response.sheet_id is not None
        assert response.processing_timestamp is not None
    
    def test_ocr_error_response(self):
        """OCRErrorResponse 모델 테스트"""
        from app.models.ocr import OCRErrorResponse
        
        error = OCRErrorResponse(
            error_code="IMAGE_TOO_LARGE",
            error_message="파일 크기가 너무 큽니다.",
            details="최대 20MB까지 지원됩니다."
        )
        
        assert error.error_code == "IMAGE_TOO_LARGE"
        assert error.error_message == "파일 크기가 너무 큽니다."
        assert error.details == "최대 20MB까지 지원됩니다."
        assert error.timestamp is not None