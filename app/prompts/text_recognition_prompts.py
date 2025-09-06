"""
글자인식 프롬프트 중앙 관리 모듈

모든 글자인식 관련 프롬프트를 중앙에서 관리
버전 관리, 컨텍스트별 선택, 템플릿 지원

주요 기능:
- 프롬프트 타입별 관리 (상세/간단/수학특화)
- 프롬프트 버전 관리
- 컨텍스트 기반 자동 선택
- 프롬프트 템플릿 변수 지원
"""

from enum import Enum
from typing import Dict, Optional
import structlog

logger = structlog.get_logger("prompt_manager")


class PromptType(Enum):
    """
    프롬프트 타입 정의
    
    타입별 특징:
    - DETAILED_WITH_LATEX: 완전한 기능 (LaTeX, 혼합 콘텐츠, 다양한 문제 유형)
    - SIMPLE_KOREAN: 단순 한국어 손글씨 인식
    - MATH_FOCUSED: 수학 전용 최적화
    - BATCH_PROCESSING: 배치 처리용 경량 프롬프트
    """
    DETAILED_WITH_LATEX = "detailed_with_latex"
    SIMPLE_KOREAN = "simple_korean"
    MATH_FOCUSED = "math_focused"
    BATCH_PROCESSING = "batch_processing"


class TextRecognitionPromptManager:
    """
    글자인식 프롬프트 관리자
    
    책임:
    - 프롬프트 타입별 템플릿 제공
    - 컨텍스트 기반 프롬프트 선택
    - 프롬프트 버전 관리
    - 프롬프트 성능 메트릭 수집 준비
    """
    
    # 프롬프트 버전 (향후 A/B 테스트용)
    VERSION = "2.1.0"  # Updated Version for new template
    
    # 프롬프트 템플릿 정의
    PROMPTS: Dict[PromptType, str] = {
        PromptType.DETAILED_WITH_LATEX: """
You are an AI expert specializing in recognizing handwritten answers on structured Korean math exam sheets.

**CRITICAL INSTRUCTIONS - READ CAREFULLY:**

1.  **Answer Sheet Structure:** This answer sheet has a specific two-part structure for each question.
    * **Solution Process Area:** A large, multi-line box for showing the steps and calculations.
    * **Final Answer Box:** A smaller, single-line box at the very bottom for the final, conclusive answer.
    * Your primary task is to extract content from these two distinct areas for each question number.

2.  **Extraction Rules:**
    * Identify the question number (e.g., 13, 14, 15) printed on the left.
    * For the **'solution_process'**, extract all lines of handwritten work. Preserve line breaks using `\n`.
    * For the **'final_answer'**, extract the content written *only* inside the bottom-most box.
    * **Ignore any scratched-out or crossed-out markings.** Do not include them in the output.

3.  **LaTeX Conversion:**
    * Provide both the simple text (`extracted_text`) and its LaTeX equivalent (`latex_formula`).
    * Apply LaTeX conversion to both the `solution_process` and the `final_answer` fields.
    * If a field contains only a plain number (e.g., "25"), its `latex_formula` should be `null`.
    * **LaTeX Rules:**
        * Fractions: `a/b` → `\\frac{a}{b}`
        * Square Roots: `√x` → `\\sqrt{x}`
        * Exponents: `x²` → `x^2`
    * **Important:** Do NOT correct mathematical errors. Transcribe exactly what is written.

4.  **Output Format:** Return the results in this **EXACT JSON format**. Note the nested objects for `solution_process` and `final_answer`.

{
    "answers": [
        {
            "question_number": 13,
            "question_label": "13",
            "solution_process": {
                "extracted_text": "10-6=4\n4+21=25",
                "latex_formula": "10-6=4\n4+21=25"
            },
            "final_answer": {
                "extracted_text": "25",
                "latex_formula": null
            },
            "confidence": 0.98
        },
        {
            "question_number": 14,
            "question_label": "14",
            "solution_process": {
                "extracted_text": "6/24 + 2/24 = 8/24",
                "latex_formula": "\\frac{6}{24} + \\frac{2}{24} = \\frac{8}{24}"
            },
            "final_answer": {
                "extracted_text": "8/24",
                "latex_formula": "\\frac{8}{24}"
            },
            "confidence": 0.95
        },
        {
            "question_number": 15,
            "question_label": "15",
            "solution_process": {
                "extracted_text": "2x+4=10\n2x=6\nx=2+6\nx=4",
                "latex_formula": "2x+4=10\n2x=6\nx=2+6\nx=4"
            },
            "final_answer": {
                "extracted_text": "x=4",
                "latex_formula": "x=4"
            },
            "confidence": 0.96
        }
    ]
}
""",

        PromptType.SIMPLE_KOREAN: """
You are an expert Korean handwriting recognition specialist for exam answer sheets.

Extract all handwritten Korean text from subjective question areas in this image.

Return the results in this exact JSON format:
{
    "answers": [
        {
            "question_number": 1,
            "question_label": "1",
            "extracted_text": "handwritten Korean text",
            "latex_formula": null,
            "confidence": 0.85
        },
        {
            "question_number": 2,
            "question_label": "2",
            "extracted_text": "handwritten Korean text",
            "latex_formula": null,
            "confidence": 0.85
        }
    ]
}
""",

        PromptType.MATH_FOCUSED: """
You are a mathematical expression recognition specialist focused on accurate LaTeX conversion.

PRIMARY FOCUS: Mathematical expressions and formulas
- Prioritize accuracy in mathematical symbol recognition
- Full LaTeX conversion for all mathematical content
- Support complex nested expressions

MATHEMATICAL NOTATION PRIORITIES:
1. Complex fractions and nested expressions
2. Matrix and vector notation
3. Calculus notation (derivatives, integrals)
4. Set theory and logic symbols
5. Advanced mathematical operators

Return results in this EXACT JSON format:
{
    "answers": [
        {
            "question_number": 1,
            "question_label": "1",
            "extracted_text": "∫₀^∞ e^(-x²) dx",
            "latex_formula": "\\int_0^\\infty e^{-x^2} dx",
            "confidence": 0.92
        }
    ]
}
""",

        PromptType.BATCH_PROCESSING: """
You are a fast Korean answer sheet recognition system optimized for batch processing.

QUICK EXTRACTION RULES:
1. Identify numbered questions (1., 2., etc.)
2. Extract visible text or selected options
3. Focus on speed over perfect formatting
4. Skip uncertain content rather than guess

Return results in this simplified JSON format:
{
    "answers": [
        {
            "question_number": 1,
            "question_label": "1",
            "extracted_text": "detected answer",
            "confidence": 0.80
        }
    ]
}
"""
    }
    
    def __init__(self):
        """프롬프트 관리자 초기화"""
        self.usage_stats: Dict[PromptType, int] = {pt: 0 for pt in PromptType}
        logger.info(
            "글자인식 프롬프트 관리자 초기화",
            version=self.VERSION,
            available_types=[pt.value for pt in PromptType]
        )
    
    def get_prompt(
        self,
        prompt_type: PromptType = PromptType.DETAILED_WITH_LATEX,
        **kwargs
    ) -> str:
        """
        프롬프트 반환
        
        Args:
            prompt_type: 요청할 프롬프트 타입
            **kwargs: 템플릿 변수 (향후 확장용)
            
        Returns:
            str: 요청된 프롬프트 텍스트
        """
        # 사용 통계 업데이트
        self.usage_stats[prompt_type] += 1
        
        # 프롬프트 반환
        prompt = self.PROMPTS.get(prompt_type)
        
        if not prompt:
            logger.warning(
                "알 수 없는 프롬프트 타입, 기본값 사용",
                requested_type=prompt_type.value,
                fallback_type=PromptType.DETAILED_WITH_LATEX.value
            )
            prompt = self.PROMPTS[PromptType.DETAILED_WITH_LATEX]
        
        logger.debug(
            "프롬프트 제공",
            type=prompt_type.value,
            usage_count=self.usage_stats[prompt_type]
        )
        
        # 템플릿 변수 적용 (향후 확장)
        if kwargs:
            try:
                prompt = prompt.format(**kwargs)
            except KeyError as e:
                logger.error(f"프롬프트 템플릿 변수 오류: {e}")
        
        return prompt
    
    def get_prompt_for_context(
        self,
        is_batch: bool = False,
        is_math_heavy: bool = False,
        needs_latex: bool = True,
        **kwargs
    ) -> str:
        """
        컨텍스트 기반 자동 프롬프트 선택
        
        Args:
            is_batch: 배치 처리 여부
            is_math_heavy: 수학 중심 콘텐츠 여부
            needs_latex: LaTeX 변환 필요 여부
            **kwargs: 추가 템플릿 변수
            
        Returns:
            str: 컨텍스트에 최적화된 프롬프트
        """
        # 컨텍스트 기반 프롬프트 타입 결정
        if is_batch:
            prompt_type = PromptType.BATCH_PROCESSING
        elif is_math_heavy:
            prompt_type = PromptType.MATH_FOCUSED
        elif not needs_latex:
            prompt_type = PromptType.SIMPLE_KOREAN
        else:
            prompt_type = PromptType.DETAILED_WITH_LATEX
        
        logger.info(
            "컨텍스트 기반 프롬프트 선택",
            is_batch=is_batch,
            is_math_heavy=is_math_heavy,
            needs_latex=needs_latex,
            selected_type=prompt_type.value
        )
        
        return self.get_prompt(prompt_type, **kwargs)
    
    def get_usage_stats(self) -> Dict[str, int]:
        """
        프롬프트 사용 통계 반환
        
        Returns:
            Dict[str, int]: 프롬프트 타입별 사용 횟수
        """
        return {pt.value: count for pt, count in self.usage_stats.items()}
    
    def reset_stats(self):
        """사용 통계 초기화"""
        self.usage_stats = {pt: 0 for pt in PromptType}
        logger.info("프롬프트 사용 통계 초기화")


# 싱글톤 인스턴스
_prompt_manager_instance: Optional[TextRecognitionPromptManager] = None


def get_prompt_manager() -> TextRecognitionPromptManager:
    """
    프롬프트 관리자 싱글톤 인스턴스 반환
    
    Returns:
        TextRecognitionPromptManager: 프롬프트 관리자 인스턴스
    """
    global _prompt_manager_instance
    if _prompt_manager_instance is None:
        _prompt_manager_instance = TextRecognitionPromptManager()
    return _prompt_manager_instance


# 편의 함수들
def get_detailed_prompt() -> str:
    """상세 LaTeX 지원 프롬프트 반환"""
    return get_prompt_manager().get_prompt(PromptType.DETAILED_WITH_LATEX)


def get_simple_prompt() -> str:
    """단순 한국어 프롬프트 반환"""
    return get_prompt_manager().get_prompt(PromptType.SIMPLE_KOREAN)


def get_batch_prompt() -> str:
    """배치 처리용 프롬프트 반환"""
    return get_prompt_manager().get_prompt(PromptType.BATCH_PROCESSING)


def get_math_prompt() -> str:
    """수학 특화 프롬프트 반환"""
    return get_prompt_manager().get_prompt(PromptType.MATH_FOCUSED)