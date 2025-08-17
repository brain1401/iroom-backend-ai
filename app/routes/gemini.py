"""
Gemini API Routes

LangServe 기반 Gemini Runnable 공개.
"""

from fastapi import FastAPI, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Any
import structlog

from langserve import add_routes
from langserve.schema import CustomUserType
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, Runnable

from app.config.settings import Settings, get_settings
from app.middleware.auth import require_api_key


logger = structlog.get_logger("gemini_routes")


class GeminiRequest(CustomUserType):
    """요청 모델 명세"""

    input: str


class GeminiResponse(CustomUserType):
    """응답 모델 명세"""

    output: str


def _build_gemini_runnable(settings: Settings) -> Runnable:
    """Gemini Runnable 생성 함수"""
    # API 키 미설정 시 요청마다 명확한 오류 발생 처리
    if not settings.gemini_api_key:

        def _raise_on_call(request: GeminiRequest) -> GeminiResponse:
            raise RuntimeError("Gemini API key not configured")

        return RunnableLambda(_raise_on_call)

    def _process_request(request: GeminiRequest) -> GeminiResponse:
        """Gemini 요청 처리 함수"""
        model = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=settings.gemini_temperature,
            max_output_tokens=settings.gemini_max_tokens,
        )
        # 모델 호출 및 응답 처리
        response = model.invoke(request.input)
        output = StrOutputParser().invoke(response)
        return GeminiResponse(output=output)

    return RunnableLambda(_process_request)


def setup_gemini_routes(app: FastAPI, settings: Settings | None = None) -> None:
    """
    LangServe로 Gemini Runnable을 `/gemini` 경로에 마운트함.
    """
    if settings is None:
        settings = get_settings()

    # Root redirect to docs
    @app.get("/")
    async def redirect_root_to_docs():
        """루트 경로 문서로 리다이렉트"""
        return RedirectResponse("/docs")

    # Runnable 생성
    runnable = _build_gemini_runnable(settings)

    # dependencies 설정 - 인증이 필요한 경우에만 추가
    dependencies = []
    if settings.require_api_key:
        dependencies.append(Depends(require_api_key))

    # LangServe 라우터 추가 - batch 엔드포인트 제외로 TypeAdapter 오류 회피
    add_routes(
        app,
        runnable,
        path="/gemini",
        dependencies=dependencies,
        enabled_endpoints=[
            "invoke",
            "stream",
            "stream_log",
            "input_schema",
            "output_schema",
            "config_schema",
        ],
    )

    # 별도 헬스체크 엔드포인트 유지
    @app.get("/gemini/health")
    async def gemini_health():
        # API 키 미설정 시 바로 비정상 상태 반환
        if not settings.gemini_api_key:
            return {
                "status": "unhealthy",
                "service": "gemini",
                "error": "missing_api_key",
            }
        try:
            # 가벼운 모델 호출로 확인
            await ChatGoogleGenerativeAI(
                model=settings.gemini_model,
                google_api_key=settings.gemini_api_key,
                temperature=0.0,
                max_output_tokens=8,
            ).ainvoke("ping")
            return {"status": "healthy", "service": "gemini"}
        except Exception as e:
            logger.error("Gemini health check failed", error=str(e))
            return {"status": "unhealthy", "service": "gemini", "error": str(e)}

    logger.info(
        "Gemini routes added via LangServe",
        endpoints=["/gemini/*", "/gemini/health"],
        authentication_required=settings.require_api_key,
    )
