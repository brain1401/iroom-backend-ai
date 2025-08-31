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

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ValidationError

from app.utils.image_processing import encode_image_to_base64
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
    return """
You are an expert Korean exam answer sheet recognition specialist with advanced LaTeX mathematical formatting support, including mixed content partial conversion.

CRITICAL INSTRUCTIONS:
1. This is a Korean exam answer sheet with NUMBERED questions (not Korean labels)
2. Look for various numbering patterns: 1., 2), (1), 1번, ①, etc.
3. Support MIXED QUESTION TYPES including mixed content with partial LaTeX conversion:
   - Multiple Choice: A, B, C, D, E (or 가, 나, 다, 라, 마)
   - Subjective: Mathematical expressions, text answers, numerical values
   - Mixed Content: Text containing mathematical expressions (NEW!)

4. MATHEMATICAL SYMBOLS AND LATEX CONVERSION:
   For mathematical expressions, provide BOTH formats:
   - extracted_text: Simple notation (√2/√3, x²+2x+1)
   - latex_formula: LaTeX notation (\\frac{\\sqrt{2}}{\\sqrt{3}}, x^2+2x+1)

5. LATEX MATHEMATICAL NOTATION RULES:
   - Fractions: \\frac{numerator}{denominator}
     Example: "2/3" → "\\frac{2}{3}", "√2/√3" → "\\frac{\\sqrt{2}}{\\sqrt{3}}"
   - Square roots: \\sqrt{expression}
     Example: "√2" → "\\sqrt{2}", "√(x+1)" → "\\sqrt{x+1}"
   - Nth roots: \\sqrt[n]{expression}
     Example: "∛8" → "\\sqrt[3]{8}", "⁴√16" → "\\sqrt[4]{16}"
   - Superscripts: ^{exponent}
     Example: "x²" → "x^2", "a³" → "a^3", "2ˣ" → "2^x"
   - Subscripts: _{subscript}
     Example: "H₂O" → "H_2O", "x₁" → "x_1"
   - Greek letters: \\alpha, \\beta, \\gamma, \\pi, \\theta, \\sigma, \\omega
   - Trigonometric: \\sin, \\cos, \\tan, \\cot, \\sec, \\csc
   - Logarithmic: \\log, \\ln, \\log_{base}
   - Special symbols: \\infty, \\pm, \\mp, \\neq, \\leq, \\geq, \\approx
   - Degree symbol: ^\\circ
     Example: "sin(30°)" → "\\sin(30^\\circ)"

6. QUESTION DETECTION PATTERNS:
   - "1.", "2.", "3." (period after number)
   - "1)", "2)", "3)" (parenthesis after number)  
   - "(1)", "(2)", "(3)" (number in parentheses)
   - "1번", "2번", "3번" (Korean numbering)
   - "①", "②", "③" (circled numbers)
   - "문제 1", "문제 2" (Korean question labels)

7. ENHANCED ANSWER TYPE RECOGNITION:
   - Multiple Choice: Single letters (A, B, C, D, E) or (가, 나, 다, 라, 마)
     → Only provide extracted_text, latex_formula should be null
   - Pure Numbers: Simple numerical values (19.38, 5, -3)
     → Only provide extracted_text, latex_formula should be null
   - Pure Mathematical: Only mathematical expressions
     → Provide both extracted_text (simple) and latex_formula (LaTeX)
   - Mixed Content: Text containing mathematical expressions (IMPORTANT!)
     → Provide both extracted_text (original) and latex_formula (partial LaTeX conversion)
   - Pure Text: Korean/English text only
     → Only provide extracted_text, latex_formula should be null

8. MIXED CONTENT PROCESSING RULES (CRITICAL FOR PARTIAL LATEX CONVERSION):
   For answers containing both text and mathematical expressions:
   - Preserve all non-mathematical text exactly as written (Korean, English, punctuation)
   - Convert only mathematical parts to LaTeX notation within the text
   - Maintain original text structure, spacing, and word order
   - Apply LaTeX conversion selectively to mathematical symbols embedded in text
   
   Mathematical parts within text include:
   - Fractions: 2/3 → \\frac{2}{3}
   - Roots: √2 → \\sqrt{2}
   - Powers: x² → x^2
   - Trigonometry: sin(30°) → \\sin(30^\\circ)
   - Greek letters: π → \\pi
   - Chemical formulas: H₂O → H_2O

9. CONTENT TYPE DETECTION:
   Mixed content identification criteria:
   - Contains Korean/English text (>=1 word) AND mathematical expressions
   - Text indicators: "답:", "결과는", "공식:", "Answer:", "Result:", "Formula:"
   - Mathematical symbols within text context
   - Combined text-math expressions
   
   Processing priorities:
   1. Detect mixed content first
   2. Identify mathematical components within text
   3. Apply selective LaTeX conversion to math parts only
   4. Preserve text structure completely
   5. Generate latex_formula with partial conversions

Extract all answers from numbered questions. Support 1-20 questions flexibly.

Return results in this EXACT JSON format:
{
    "answers": [
        {
            "question_number": 1,
            "question_label": "1",
            "extracted_text": "A",
            "latex_formula": null,
            "confidence": 0.95
        },
        {
            "question_number": 2,
            "question_label": "2", 
            "extracted_text": "답: √2/√3",
            "latex_formula": "답: \\frac{\\sqrt{2}}{\\sqrt{3}}",
            "confidence": 0.90
        },
        {
            "question_number": 3,
            "question_label": "3",
            "extracted_text": "x²+2x+1",
            "latex_formula": "x^2+2x+1",
            "confidence": 0.88
        }
    ]
}

EXAMPLE CONVERSIONS:

Pure Mathematical → LaTeX:
- "2/3" → "\\frac{2}{3}"
- "√2" → "\\sqrt{2}"
- "∛8" → "\\sqrt[3]{8}"
- "x²+y²" → "x^2+y^2"
- "sin(30°)" → "\\sin(30^\\circ)"

Mixed Content → Partial LaTeX (CRITICAL EXAMPLES):
Korean + Math:
- "답: 2/3" → extracted_text: "답: 2/3", latex_formula: "답: \\frac{2}{3}"
- "결과는 √2입니다" → extracted_text: "결과는 √2입니다", latex_formula: "결과는 \\sqrt{2}입니다"
- "각도 sin(30°) = 0.5" → extracted_text: "각도 sin(30°) = 0.5", latex_formula: "각도 \\sin(30^\\circ) = 0.5"
- "공식: E=mc²" → extracted_text: "공식: E=mc²", latex_formula: "공식: E=mc^2"

English + Math:
- "Answer: x²+1" → extracted_text: "Answer: x²+1", latex_formula: "Answer: x^2+1"
- "Height = 2πr" → extracted_text: "Height = 2πr", latex_formula: "Height = 2\\pi r"
- "Formula: a/b + c" → extracted_text: "Formula: a/b + c", latex_formula: "Formula: \\frac{a}{b} + c"

Complex Mixed:
- "공식은 E=mc²이고 c는 3×10⁸" → extracted_text: "공식은 E=mc²이고 c는 3×10⁸", latex_formula: "공식은 E=mc^2이고 c는 3\\times 10^8"
- "답: (x+1)/(x-1) = 2" → extracted_text: "답: (x+1)/(x-1) = 2", latex_formula: "답: \\frac{x+1}{x-1} = 2"

NON-MATHEMATICAL ANSWERS (latex_formula = null):
- Multiple Choice: "A", "B", "C", "D", "E", "가", "나", "다"
- Pure Numbers: "19.38", "5", "-3", "0"
- Pure Text: "정답", "해당없음", "증명생략", "No answer"

IMPORTANT: 
- question_label should be simple numbers: "1", "2", "3", etc.
- For mixed content, ALWAYS provide partial LaTeX conversion in latex_formula
- Preserve Korean/English text structure completely in mixed content
- Convert only mathematical symbols/expressions to LaTeX within text
- For pure mathematical expressions, convert entire content to LaTeX
- For pure text or multiple choice, set latex_formula to null
"""


def create_gemini_vision_model(api_key: str) -> ChatGoogleGenerativeAI:
    """
    Gemini Vision 모델 생성

    Args:
        api_key: Gemini API 키

    Returns:
        ChatGoogleGenerativeAI: 구성된 Gemini Vision 모델

    Raises:
        HTTPException: API 키가 설정되지 않은 경우
    """
    if not api_key:
        raise HTTPException(status_code=503, detail="Gemini API key not configured")

    return ChatGoogleGenerativeAI(
        model="gemini-2.5-pro",  # Vision 지원 모델
        google_api_key=api_key,
        temperature=0.0,  # 최대 정확성 (수학 기호 인식)
        max_output_tokens=8000,
    )


async def process_text_recognition_with_gemini(
    image_data: bytes, model: ChatGoogleGenerativeAI
) -> TextRecognitionParsingResponse:
    """
    Gemini Vision API를 통한 글자인식 처리

    Args:
        image_data: 최적화된 이미지 데이터
        model: Gemini Vision 모델 인스턴스

    Returns:
        TextRecognitionParsingResponse: 파싱된 글자인식 결과

    Raises:
        HTTPException: 글자인식 처리 실패 시
    """
    try:
        # Base64 인코딩
        image_base64 = encode_image_to_base64(image_data)

        # 프롬프트 구성
        prompt = create_text_recognition_prompt()

        # Gemini Vision API 호출
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                },
            ]
        )

        logger.info("Gemini Vision API 호출 시작")
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

        logger.info("Gemini 응답 수신", response_length=len(response_text))

        # JSON 파싱
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

            # Pydantic 모델로 검증
            ocr_result = TextRecognitionParsingResponse(**parsed_data)

            logger.info(
                "글자인식 결과 파싱 완료",
                detected_questions=ocr_result.detected_questions,
                extracted_answers=len(ocr_result.answers),
            )

            return ocr_result

        except (json.JSONDecodeError, ValidationError) as parse_error:
            logger.error(
                "Gemini 응답 파싱 실패",
                response=(
                    response_text[:200] + "..."
                    if len(response_text) > 200
                    else response_text
                ),
                error=str(parse_error),
            )

            # 파싱 실패 시 기본값 반환
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
    empty_answers = len([a for a in answers if not a.extracted_text.strip()])

    return {
        "total_answers": len(answers),
        "average_confidence": calculate_average_confidence(answers),
        "high_confidence_count": high_confidence,
        "medium_confidence_count": medium_confidence,
        "low_confidence_count": low_confidence,
        "empty_answers_count": empty_answers,
    }
