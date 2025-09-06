"""
Gemini API Routes

LangServe 기반 Gemini Runnable 공개.
"""

from fastapi import FastAPI, Depends
from fastapi.responses import RedirectResponse
import structlog
from pydantic import BaseModel

from langserve import add_routes
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, Runnable

from app.config.settings import Settings, get_settings
from app.middleware.auth import require_api_key


logger = structlog.get_logger("gemini_routes")


# 제거됨: GeminiRequest, GeminiResponse - LangServe는 간단한 str 체인 선호


class GeminiHealthResponse(BaseModel):
    """Gemini 헬스체크 응답 모델"""

    status: str
    service: str
    error: str | None = None


def _build_gemini_runnable(settings: Settings) -> Runnable:
    """Gemini Runnable 생성 함수"""
    # API 키 미설정 시 요청마다 명확한 오류 발생 처리
    if not settings.gemini_api_key:

        def _raise_on_call(input_text: str) -> str:
            raise RuntimeError("Gemini API key not configured")

        return RunnableLambda(_raise_on_call)

    # LangServe는 더 간단한 str -> str 체인 선호
    model = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=settings.gemini_temperature,
        max_output_tokens=settings.gemini_max_tokens,
    )
    
    # 간단한 체인 구성: str 입력 -> 모델 호출 -> str 출력
    chain = model | StrOutputParser()
    
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

    # LangServe 라우터 추가 - 모든 엔드포인트 활성화
    add_routes(
        app,
        runnable,
        path="/gemini",
        dependencies=dependencies,
        enabled_endpoints=[
            "invoke",
            "batch",  # batch 엔드포인트 재활성화
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
        # API 키 미설정 시 바로 비정상 상태 반환
        if not settings.gemini_api_key:
            return GeminiHealthResponse(
                status="unhealthy", service="gemini", error="missing_api_key"
            )
        try:
            # 가벼운 모델 호출로 확인
            await ChatGoogleGenerativeAI(
                model=settings.gemini_model,
                google_api_key=settings.gemini_api_key,
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
