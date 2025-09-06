"""
Gemini API Routes

LangServe 기반 Gemini Runnable 공개.
"""

from fastapi import FastAPI, Depends
from fastapi.responses import RedirectResponse
import structlog
from pydantic import BaseModel, Field


from langserve import add_routes, CustomUserType
from langchain_google_vertexai import ChatVertexAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, Runnable

from app.config.settings import Settings, get_settings
from app.middleware.auth import require_api_key


logger = structlog.get_logger("gemini_routes")


# LangServe OpenAPI 스키마 생성을 위한 명시적 타입 정의
class GeminiInput(CustomUserType):
    """Gemini API 입력 모델"""
    input: str = Field(..., description="처리할 텍스트 입력")


class GeminiOutput(CustomUserType):
    """Gemini API 출력 모델"""
    output: str = Field(..., description="처리된 텍스트 출력")


class GeminiHealthResponse(BaseModel):
    """Gemini 헬스체크 응답 모델"""

    status: str
    service: str
    error: str | None = None


def _build_gemini_runnable(settings: Settings) -> Runnable:
    """Gemini Runnable 생성 함수"""
    # GCP 프로젝트 미설정 시 요청마다 명확한 오류 발생 처리
    if not settings.gcp_project_id:

        def _raise_on_call(input_dict: dict) -> dict:
            raise RuntimeError("GCP project not configured")

        return RunnableLambda(_raise_on_call)

    # LangServe OpenAPI 스키마 생성을 위한 체인 구성
    model = ChatVertexAI(
        model=settings.gemini_model,
        project=settings.gcp_project_id,
        location=settings.gcp_location,
        temperature=settings.gemini_temperature,
        max_output_tokens=settings.gemini_max_tokens,
    )
    
    # 입력 변환: dict -> str
    def extract_input(input_dict: dict) -> str:
        """입력 딕셔너리에서 문자열 추출"""
        if isinstance(input_dict, dict):
            return input_dict.get("input", "")
        return str(input_dict)
    
    # 출력 변환: str -> dict
    def format_output(output: str) -> dict:
        """출력을 딕셔너리 형식으로 변환"""
        return {"output": output}
    
    # 체인 구성: dict 입력 -> str 추출 -> 모델 호출 -> str 파싱 -> dict 출력
    # CustomUserType 사용 시 타입이 자동으로 추론되므로 with_types 불필요
    chain = (
        RunnableLambda(extract_input) 
        | model 
        | StrOutputParser() 
        | RunnableLambda(format_output)
    )  # type: ignore[var-annotated]
    
    return chain


def setup_gemini_routes(app: FastAPI, settings: Settings | None = None) -> None:
    """
    LangServe로 Gemini Runnable을 `/gemini` 경로에 마운트함.
    """
    if settings is None:
        settings = get_settings()

    # Root redirect to docs
    @app.get("/", summary="API 문서 리다이렉트")
    async def redirect_root_to_docs():
        """루트 경로 문서로 리다이렉트"""
        return RedirectResponse("/docs")

    # Runnable 생성
    runnable = _build_gemini_runnable(settings)

    # dependencies 설정 - 인증이 필요한 경우에만 추가
    dependencies = []
    if settings.require_api_key:
        dependencies.append(Depends(require_api_key))

    # LangServe 라우터 추가 - batch 엔드포인트 임시 비활성화 (Pydantic 2.11 호환성 문제)
    add_routes(
        app,
        runnable,
        path="/gemini",
        dependencies=dependencies,
        enabled_endpoints=[
            "invoke",
            # "batch",  # Pydantic 2.11 호환성 문제로 임시 비활성화
            "stream",
            "stream_log",
            "input_schema",
            "output_schema",
            "config_schema",
        ],
    )

    # 별도 헬스체크 엔드포인트 유지
    @app.get("/gemini/health", response_model=GeminiHealthResponse, summary="Gemini API 상태 확인")
    async def gemini_health():
        # GCP 프로젝트 미설정 시 바로 비정상 상태 반환
        if not settings.gcp_project_id:
            return GeminiHealthResponse(
                status="unhealthy", service="gemini", error="missing_gcp_project"
            )
        try:
            # 가벼운 모델 호출로 확인
            await ChatVertexAI(
                model=settings.gemini_model,
                project=settings.gcp_project_id,
                location=settings.gcp_location,
                temperature=0.0,
                max_output_tokens=8,
            ).ainvoke("ping")
            return GeminiHealthResponse(status="healthy", service="gemini")
        except Exception as e:
            logger.error("Gemini health check failed", error=str(e))
            return GeminiHealthResponse(
                status="unhealthy", service="gemini", error=str(e)
            )

    logger.info(
        "Gemini routes added via LangServe",
        endpoints=["/gemini/*", "/gemini/health"],
        authentication_required=settings.require_api_key,
    )
