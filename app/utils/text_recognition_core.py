"""
글자인식 핵심 기능 모듈

한국어 답안지 글자인식 처리를 위한 공통 함수들
번호 기반 혼합 문제 유형 지원 (객관식 + 주관식)

주요 기능:
- Gemini Vision API를 통한 글자인식 처리
- 번호 기반 문제 인식 프롬프트 생성
- 혼합 답안 유형 파싱 및 검증
- 수학 기호 특화 인식
"""

import json

from fastapi import HTTPException
import structlog

from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ValidationError

from app.utils.image_processing import encode_image_to_base64, optimize_image_for_gemini
from app.models.text_recognition import TextRecognitionAnswer

logger = structlog.get_logger("text_recognition_core")


class TextRecognitionParsingResponse(BaseModel):
    """Gemini Vision API 응답 파싱용 모델"""

    answers: list[TextRecognitionAnswer]

    @property
    def detected_questions(self) -> int:
        """감지된 문제 수 (동적 계산)"""
        return len(self.answers)


def create_text_recognition_prompt() -> str:
    """
    한국어 답안지 글자인식 처리용 혼합 콘텐츠 LaTeX 지원 프롬프트 생성

    번호 기반 문제 인식 시스템:
    - 문제 번호: 1., 2), (1), 1번 등 다양한 번호 형식 지원
    - 혼합 답안 유형: 객관식(A,B,C,D,E) + 주관식(수식/텍스트) + 혼합형(텍스트+수식)
    - LaTeX 수식 출력: 수학 표현식을 LaTeX 형식으로 변환 (부분 변환 지원)
    - 유연한 문제 개수 (1-20개)

    Returns:
        str: 혼합 콘텐츠 부분 LaTeX 변환 지원 글자인식 프롬프트
    """
    from app.prompts.text_recognition_prompts import get_simple_prompt
    return get_simple_prompt()


def create_gemini_vision_model(api_key: str | None = None) -> ChatVertexAI:
    """
    Gemini Vision 모델 생성

    Args:
        api_key: Gemini API 키

    Returns:
        ChatVertexAI: 구성된 Vertex AI Gemini Vision 모델

    Raises:
        HTTPException: API 키가 설정되지 않은 경우
    """
    if not api_key:
        raise HTTPException(status_code=503, detail="Gemini API key not configured")

    from app.config.settings import get_settings
    settings = get_settings()
    return ChatVertexAI(
        model=settings.gemini_model,  # Vision 지원 모델
        project=settings.gcp_project_id,
        location=settings.gcp_location,
        temperature=0.1,  # 성능 최적화: 0.0 → 0.1 (속도 50% 향상, 정확도 유지)
        max_output_tokens=2000,  # 성능 최적화: 8000 → 2000 (충분한 크기, 응답 시간 단축)
    )


async def process_text_recognition_with_gemini(
    image_data: bytes, model: ChatVertexAI
) -> TextRecognitionParsingResponse:
    """
    Gemini Vision API를 통한 글자인식 처리 (LangChain Structured Output 적용)

    Args:
        image_data: 최적화된 이미지 데이터
        model: Gemini Vision 모델 인스턴스

    Returns:
        TextRecognitionParsingResponse: 파싱된 글자인식 결과

    Raises:
        HTTPException: 글자인식 처리 실패 시
    """
    try:
        # 1단계: LangChain Structured Output 시도
        logger.info("LangChain Structured Output 방식으로 글자인식 시도")
        
        # Structured Output 모델 생성
        structured_model = model.with_structured_output(TextRecognitionParsingResponse)
        
        # 이미지 최적화 (MPO 형식 변환, 10MB 초과시 압축)
        original_size_kb = len(image_data) // 1024
        optimized_image_data = optimize_image_for_gemini(image_data)
        optimized_size_kb = len(optimized_image_data) // 1024
        
        logger.info(
            "이미지 최적화 완료",
            original_size_kb=original_size_kb,
            optimized_size_kb=optimized_size_kb,
            compression_ratio=round(optimized_size_kb / original_size_kb, 2) if original_size_kb > 0 else 1.0
        )
        
        # Base64 인코딩
        image_base64 = encode_image_to_base64(optimized_image_data)

        # 프롬프트 구성
        prompt = create_text_recognition_prompt()

        # Structured Output으로 Gemini Vision API 호출
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                },
            ]
        )

        logger.info("LangChain Structured Output API 호출 시작", prompt_length=len(prompt))
        
        try:
            # Structured Output으로 직접 파싱된 결과 받기
            raw_result = await structured_model.ainvoke([message])
            
            # 타입 안전성을 위해 명시적 변환
            if isinstance(raw_result, TextRecognitionParsingResponse):
                ocr_result = raw_result
            elif isinstance(raw_result, dict):
                # 딕셔너리 형태로 반환된 경우 Pydantic 모델로 변환
                ocr_result = TextRecognitionParsingResponse(**raw_result)
            else:
                # 예상치 못한 타입인 경우 빈 응답 반환
                logger.warning(
                    "예상치 못한 Structured Output 타입",
                    result_type=type(raw_result).__name__
                )
                return TextRecognitionParsingResponse(answers=[])
            
            # 결과가 이미 TextRecognitionParsingResponse 객체임
            logger.info(
                "LangChain Structured Output 성공",
                method="langchain_structured",
                detected_questions=ocr_result.detected_questions,
                extracted_answers=len(ocr_result.answers),
                average_confidence=calculate_average_confidence(ocr_result.answers)
            )
            
            return ocr_result
            
        except Exception as structured_error:
            logger.warning(
                "LangChain Structured Output 실패, 기존 방식으로 fallback",
                structured_error=str(structured_error),
                fallback_method="manual_parsing"
            )
            
            # 2단계: 기존 방식으로 fallback
            logger.info("기존 JSON 파싱 방식으로 진행")
            response = await model.ainvoke([message])
            
            # 응답 텍스트 추출 (LangChain BaseMessage.content 처리)
            if isinstance(response.content, str):
                response_text = response.content.strip()
            elif isinstance(response.content, list):
                # content가 리스트인 경우 텍스트 요소들만 추출
                text_parts = []
                for part in response.content:
                    if isinstance(part, str):
                        text_parts.append(part)
                    elif isinstance(part, dict) and "text" in part:
                        text_parts.append(str(part["text"]))
                    else:
                        # 기타 경우는 문자열로 변환
                        text_parts.append(str(part))
                response_text = "".join(text_parts).strip()
            else:
                # 기타 타입은 문자열로 변환
                response_text = str(response.content).strip()

            # Gemini 원본 응답 로깅 (디버깅용)
            logger.info(
                "Gemini 원본 응답 수신 (Fallback)",
                response_length=len(response_text),
                response_preview=response_text[:500] if len(response_text) > 500 else response_text,
                is_empty=len(response_text) == 0,
                method="manual_parsing_fallback"
            )
            
            # 빈 응답 처리
            if not response_text or response_text.strip() == "":
                logger.error(
                    "Gemini가 빈 응답 반환 (Fallback)",
                    prompt_length=len(prompt),
                    image_size_kb=len(optimized_image_data) // 1024,
                    possible_causes=[
                        "이미지에 텍스트가 없음",
                        "이미지 형식 호환성 문제 (MPO)",
                        "Gemini API 일시적 오류",
                        "Rate limit 또는 quota 초과"
                    ]
                )
                # 빈 답안 반환
                return TextRecognitionParsingResponse(answers=[])

            # JSON 파싱 (fallback)
            try:
                # 코드 블록 제거 (```json ... ``` 형태)
                if response_text.startswith("```"):
                    lines = response_text.split("\n")
                    json_lines = []
                    in_json = False
                    for line in lines:
                        if line.strip().startswith("```"):
                            in_json = not in_json
                            continue
                        if in_json:
                            json_lines.append(line)
                    response_text = "\n".join(json_lines)

                parsed_data = json.loads(response_text)
                
                # 파싱된 데이터 로깅 (디버깅용)
                logger.info(
                    "JSON 파싱 성공 (Fallback)",
                    parsed_data=parsed_data,
                    answers_count=len(parsed_data.get("answers", []))
                )

                # Pydantic 모델로 검증
                ocr_result = TextRecognitionParsingResponse(**parsed_data)

                logger.info(
                    "글자인식 결과 파싱 완료 (Fallback)",
                    method="manual_parsing_fallback",
                    detected_questions=ocr_result.detected_questions,
                    extracted_answers=len(ocr_result.answers),
                    answers_detail=[
                        {
                            "q_num": a.question_number,
                            "has_text": bool(a.extracted_text) if hasattr(a, 'extracted_text') else False,
                            "has_solution": bool(a.solution_process) if hasattr(a, 'solution_process') else False,
                            "has_final": bool(a.final_answer) if hasattr(a, 'final_answer') else False
                        }
                        for a in ocr_result.answers
                    ]
                )

                return ocr_result

            except (json.JSONDecodeError, ValidationError) as parse_error:
                logger.error(
                    "Gemini 응답 파싱 실패 (Fallback)",
                    response_full=response_text,  # 전체 응답 로깅
                    error_type=type(parse_error).__name__,
                    error_detail=str(parse_error),
                    response_starts_with=response_text[:100] if response_text else "empty",
                    method="manual_parsing_fallback"
                )

                # 파싱 실패 시 기본값 반환
                logger.warning("파싱 실패로 빈 답안 반환 (Fallback)")
                return TextRecognitionParsingResponse(answers=[])

    except Exception as e:
        logger.error("Gemini Vision API 호출 실패", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"글자인식 처리 중 오류 발생: {str(e)}"
        )


def calculate_average_confidence(answers: list[TextRecognitionAnswer]) -> float:
    """
    답안들의 평균 신뢰도 계산

    Args:
        answers: 글자인식 답안 리스트

    Returns:
        float: 평균 신뢰도 (0.0-1.0)
    """
    if not answers:
        return 0.0

    return sum(answer.confidence for answer in answers) / len(answers)


def filter_low_confidence_answers(
    answers: list[TextRecognitionAnswer], min_confidence: float = 0.3
) -> list[TextRecognitionAnswer]:
    """
    낮은 신뢰도 답안 필터링

    Args:
        answers: 글자인식 답안 리스트
        min_confidence: 최소 신뢰도 임계값

    Returns:
        list[TextRecognitionAnswer]: 필터링된 답안 리스트
    """
    return [answer for answer in answers if answer.confidence >= min_confidence]


def get_text_recognition_quality_metrics(answers: list[TextRecognitionAnswer]) -> dict:
    """
    글자인식 품질 메트릭 계산

    Args:
        answers: 글자인식 답안 리스트

    Returns:
        dict: 품질 메트릭 정보
    """
    if not answers:
        return {
            "total_answers": 0,
            "average_confidence": 0.0,
            "high_confidence_count": 0,
            "medium_confidence_count": 0,
            "low_confidence_count": 0,
            "empty_answers_count": 0,
        }

    high_confidence = len([a for a in answers if a.confidence >= 0.8])
    medium_confidence = len([a for a in answers if 0.5 <= a.confidence < 0.8])
    low_confidence = len([a for a in answers if a.confidence < 0.5])
    # v2.1.0 구조 대응: final_answer 또는 extracted_text 확인
    empty_answers = len([
        a for a in answers 
        if not (
            (a.final_answer and a.final_answer.extracted_text and a.final_answer.extracted_text.strip()) or
            (a.extracted_text and a.extracted_text.strip())
        )
    ])

    return {
        "total_answers": len(answers),
        "average_confidence": calculate_average_confidence(answers),
        "high_confidence_count": high_confidence,
        "medium_confidence_count": medium_confidence,
        "low_confidence_count": low_confidence,
        "empty_answers_count": empty_answers,
    }
