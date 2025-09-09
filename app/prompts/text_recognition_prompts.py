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
    VERSION = "3.0.0"  # 성능 최적화 버전 - 프롬프트 크기 75% 감소
    
    # 권장 Gemini API 설정 (성능 최적화)
    # temperature: 0.1 (0.0보다 빠른 생성)
    # max_output_tokens: 2000 (8000에서 감소)
    # 예상 개선: 응답 시간 50% 단축
    
    # 프롬프트 템플릿 정의
    # 프롬프트 템플릿 정의 (v3.0.0 - 성능 최적화 버전)
    PROMPTS: Dict[PromptType, str] = {
        # 최적화된 상세 프롬프트 (2500자 → 600자)
        PromptType.DETAILED_WITH_LATEX: """
Extract handwritten answers from Korean math exam sheet.

**Sheet Structure:**
Each question has two areas:
- Solution process area: Large box for work/calculations
- Final answer box: Small box at bottom for conclusive answer

**Extraction Rules:**
- Identify question number (13, 14, 15, etc.)
- Extract solution_process: All work lines (preserve \\n)
- Extract final_answer: Content in bottom box only
- Ignore crossed-out content
- LaTeX: fractions→\\frac{a}{b}, sqrt→\\sqrt{x}, power→x^2

**Output JSON:**
{
  "answers": [{
    "question_number": 13,
    "question_label": "13",
    "solution_process": {
      "extracted_text": "10-6=4\\n4+21=25",
      "latex_formula": "10-6=4\\n4+21=25"
    },
    "final_answer": {
      "extracted_text": "25",
      "latex_formula": null
    },
    "confidence": 0.98
  }]
}
""",

        # 퀴즈/간단한 답안용 프롬프트 (신규 - 가장 빠름)
        PromptType.SIMPLE_KOREAN: """
Extract handwritten Korean answers from quiz sheet.

**Rules:**
- Find question numbers
- Extract answer from box below "답안:" label
- Ignore printed placeholder text
- Multiple lines: use \\n

**Output:**
{
  "answers": [{
    "question_number": 1,
    "question_label": "1",
    "extracted_text": "검은 조직",
    "confidence": 0.98
  }]
}
""",

        # 수학 특화 프롬프트 (간소화)
        PromptType.MATH_FOCUSED: """
Extract mathematical expressions with LaTeX conversion.

Focus: Math symbols, formulas, equations
LaTeX priority: fractions, integrals, matrices, derivatives

Output:
{
  "answers": [{
    "question_number": 1,
    "question_label": "1",
    "extracted_text": "∫₀^∞ e^(-x²) dx",
    "latex_formula": "\\int_0^\\infty e^{-x^2} dx",
    "confidence": 0.92
  }]
}
""",

        # 배치 처리용 프롬프트 (개선 - 정확도 향상)
        PromptType.BATCH_PROCESSING: """
Quick extraction from Korean answer sheet.

For each numbered question:
- Extract visible answer or selected option
- Skip uncertain content
- Focus on speed

Output:
{
  "answers": [{
    "question_number": 1,
    "question_label": "1",
    "extracted_text": "답안 내용",
    "confidence": 0.80
  }]
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