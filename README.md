# iRoom Backend AI

> **Enterprise-ready AI 백엔드 서비스** - Google Gemini 2.5 Pro API를 LangServe로 제공하는 고품질 production-ready 서비스

[![Quality Score](https://img.shields.io/badge/Quality-90%2F100-brightgreen)](./docs/code-quality.md)
[![SOLID Principles](https://img.shields.io/badge/SOLID-94%25-green)](./docs/architecture.md)
[![Type Safety](https://img.shields.io/badge/Type%20Safety-100%25-brightgreen)](./docs/development.md)
[![Architecture](https://img.shields.io/badge/Architecture-95%2F100-brightgreen)](./docs/architecture.md)

## 🎯 프로젝트 개요

iRoom Backend AI는 **Google Gemini 2.5 Pro API**를 **LangServe 프레임워크**를 통해 REST API로 제공하는 백엔드 서비스입니다.


### 🏆 주요 특징

- **🚀 LangServe 기반**: FastAPI + LangChain의 표준 패턴 준수
- **🏢 Enterprise Ready**: 인증, Rate Limiting, 모니터링, 헬스체크
- **🎨 우수한 설계**: Factory, DI, Chain of Responsibility 패턴 적용  
- **🔒 타입 안전성**: BasedPyright로 0개 오류 달성
- **⚡ 현대적 도구**: uv, Pydantic v2, structlog 활용
- **🐳 컨테이너화**: Docker 및 Kubernetes 배포 지원

## 🛠️ 기술 스택

### 핵심 프레임워크
- **Web Framework**: FastAPI (비동기 고성능)
- **AI Framework**: LangChain + LangServe  
- **AI Model**: Google Gemini 2.5 Pro
- **Package Manager**: uv (고속 의존성 관리)

### 품질 & 개발 도구
- **타입 검증**: BasedPyright + Pydantic v2
- **코드 품질**: Ruff (린터) + Black (포매터) 
- **로깅**: structlog (구조화된 로깅)
- **테스팅**: pytest + 커버리지 도구
- **컨테이너**: Docker 멀티스테이지 빌드

## 🚀 빠른 시작

### 사전 요구사항

- Python 3.13
- [uv](https://github.com/astral-sh/uv) 패키지 매니저
- Google Gemini API 키

### 설치 및 실행

```bash
# uv 설치 (Windows)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# uv 설치 (macOS/Linux)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 저장소 클론
git clone <repository-url>
cd iroom-backend-ai

# 의존성 설치
uv sync

# 환경 변수 설정
cp .env.example .env
# .env 파일에서 GEMINI_API_KEY 설정

# 개발 서버 실행
uv run dev

# API 문서 확인
# http://localhost:8000/docs
```

### npm 스타일 스크립트

```bash
# 서버 실행
uv run dev          # 개발 서버 (hot reload)
uv run serve        # 프로덕션 서버

# 코드 품질
uv run check        # 전체 품질 검사
uv run typecheck    # 타입 체킹 (현재: 0 오류)
uv run lint         # 린팅 (현재: 12 이슈)
uv run format       # 코드 포매팅
uv run test         # 테스트 실행
```

## 📋 API 엔드포인트

| 엔드포인트       | 메서드 | 설명                  | 인증   |
| ---------------- | ------ | --------------------- | ------ |
| `/gemini/invoke` | POST   | 단일 텍스트 생성 요청 | 선택적 |
| `/gemini/batch`  | POST   | 배치 텍스트 생성 요청 | 선택적 |
| `/gemini/stream` | POST   | 스트리밍 텍스트 생성  | 선택적 |
| `/gemini/health` | GET    | Gemini API 상태 확인  | 없음   |
| `/health`        | GET    | 전체 서비스 상태 확인 | 없음   |
| `/docs`          | GET    | API 문서 (Swagger)    | 없음   |

### API 사용 예시

```bash
# 단일 요청
curl -X POST "http://localhost:8000/gemini/invoke" \
  -H "Content-Type: application/json" \
  -d '{"input": {"input": "안녕하세요! AI 백엔드 서비스입니다."}}'

# 스트리밍 요청  
curl -X POST "http://localhost:8000/gemini/stream" \
  -H "Content-Type: application/json" \
  -d '{"input": {"input": "긴 텍스트를 스트리밍으로 받아보세요."}}'
```

## 🐳 Docker 배포

### 기본 배포

```bash
# 이미지 빌드
docker build -t iroom-backend-ai:latest .

# 컨테이너 실행
docker run -d \
  --name iroom-backend-ai \
  -p 8080:8080 \
  -e GEMINI_API_KEY=your_google_api_key \
  iroom-backend-ai:latest
```

### Docker Compose

```yaml
version: '3.8'
services:
  iroom-backend-ai:
    build: .
    ports:
      - "8080:8080"
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - LOG_LEVEL=INFO
    restart: unless-stopped
```

## 📁 프로젝트 구조

```
iroom-backend-ai/
├── app/                        # 메인 애플리케이션
│   ├── server.py              # FastAPI 앱 팩토리
│   ├── config/                # 설정 관리
│   │   └── settings.py        # Pydantic Settings
│   ├── middleware/            # 미들웨어 계층
│   │   ├── auth.py           # 인증 미들웨어
│   │   ├── cors.py           # CORS 설정
│   │   ├── logging.py        # 로깅 미들웨어
│   │   └── rate_limit.py     # Rate Limiting
│   ├── routes/               # API 라우터
│   │   ├── gemini.py         # Gemini API 엔드포인트
│   │   └── health.py         # 헬스체크
│   └── utils/                # 유틸리티
│       └── errors.py         # 예외 처리
├── docs/                     # 상세 문서
├── tests/                    # 테스트 코드
├── Dockerfile               # Docker 설정
└── pyproject.toml          # 프로젝트 설정
```

## 📚 상세 문서

### 🏗️ 아키텍처 & 설계
- [**프로젝트 아키텍처**](./docs/architecture.md) - 전체 시스템 아키텍처 및 설계 패턴
- [**코드 품질 가이드**](./docs/code-quality.md) - 품질 상태 분석 및 개선 가이드
- [**LangServe 구조 분석**](./docs/langserve-analysis.md) - LangServe 표준 패턴 준수 현황

### 🚀 개발 & 배포
- [**개발자 가이드**](./docs/development.md) - 개발 환경 설정 및 도구 사용법
- [**API 사용 가이드**](./docs/api-guide.md) - API 엔드포인트 사용법 및 예시
- [**배포 가이드**](./docs/deployment.md) - Docker, Kubernetes 배포 방법

### 📈 로드맵 & 개선
- [**개선 로드맵**](./docs/improvement-roadmap.md) - Phase별 체계적 개선 계획
- [**스크립트 가이드**](./SCRIPTS.md) - npm 스타일 uv 명령어 사용법

## 🧪 개발 환경

### 코드 품질 도구

```bash
# 전체 품질 검사 (권장)
uv run check

# 자동 수정 가능한 이슈 해결
uv run ruff check --fix app/
uv run format

# 타입 체킹
uv run typecheck
```

### 테스트 실행

```bash
# 전체 테스트
uv run test

# 커버리지 포함
uv run test --cov=app --cov-report=html
```

## 🔧 환경 설정

### 필수 환경 변수

```bash
# Google Gemini API
GEMINI_API_KEY=your_google_api_key

# 서비스 설정 (선택적)
LOG_LEVEL=INFO
PORT=8080
HOST=0.0.0.0

# 인증 설정 (선택적)
REQUIRE_API_KEY=false
VALID_API_KEYS=["key1", "key2"]
API_KEY_HEADER=x-api-key
```

### LangSmith 연동 (선택적)

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=<your-api-key>
export LANGSMITH_PROJECT=<your-project>
```

## 🤝 기여하기

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### 코드 기여 가이드

- 한국어 주석 작성 (명사형 종결어미)
- `uv run check` 통과 필수
- 타입 힌트 필수 작성
- 테스트 커버리지 유지

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다. 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

## 🔗 참고 링크

- [LangServe 공식 문서](https://python.langchain.com/docs/langserve)
- [Google Gemini API](https://ai.google.dev/docs)
- [FastAPI 문서](https://fastapi.tiangolo.com/)
- [LangChain 문서](https://python.langchain.com/)
- [uv 공식 문서](https://docs.astral.sh/uv/)

---

<div align="center">
  <strong>🌟 Enterprise-ready AI Backend Service 🌟</strong>
  <br>
  <em>Built with ❤️ using LangServe + FastAPI + Google Gemini</em>
</div>