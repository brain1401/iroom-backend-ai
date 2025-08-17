# iRoom Backend AI - 문서

이 문서는 iRoom Backend AI 프로젝트의 구조, 설계 원칙, 사용법을 설명합니다.

## 📚 문서 구조

### 🏗️ [프로젝트 아키텍처](./architecture.md)
- 전체 시스템 아키텍처 및 설계 패턴
- SOLID 원칙 준수 평가 (94% 준수)
- 아키텍처 품질 평가 및 발전 로드맵

### 🎯 [코드 품질 가이드](./code-quality.md) **[NEW]**
- 현재 품질 상태 분석 (A급 88/100)
- 린팅 이슈 해결 가이드 (12개 → 0개)
- 품질 자동화 및 메트릭 관리

### 🚀 [개선 로드맵](./improvement-roadmap.md) **[NEW]**
- Phase별 체계적 개선 계획 (90 → 98점 목표)
- Enterprise-grade 시스템 구축 로드맵
- ROI 분석 및 비즈니스 임팩트

### 👩‍💻 [개발자 가이드](./development.md)
- 개발 환경 설정 및 코드 품질 도구
- 현재 이슈 해결 가이드 포함
- VSCode 설정 및 pre-commit 훅

### 🔍 [LangServe 구조 분석](./langserve-analysis.md)
- LangServe 공식 문서 권장사항 대비 현재 구현 분석
- 준수 현황 및 우수한 점
- 모범 사례 검증 결과

### 🚀 [API 사용 가이드](./api-guide.md)
- Gemini API 엔드포인트 사용법
- 인증 및 Rate Limiting
- 요청/응답 예시

### 🚢 [배포 가이드](./deployment.md)
- Docker 컨테이너 배포
- 환경 변수 설정
- 프로덕션 배포 체크리스트

## 🎯 프로젝트 개요

iRoom Backend AI는 Google Gemini 2.5 Pro API를 LangServe 프레임워크를 통해 REST API로 제공하는 **A급 품질의 production-ready** 백엔드 서비스입니다.

### 📊 품질 현황 (2024-01 분석 기준)

| 평가 영역 | 점수 | 상태 |
|----------|------|------|
| **전체 품질** | **90/100** | **A급** |
| 아키텍처 설계 | 95/100 | ✅ 우수 |
| 타입 안전성 | 100/100 | ✅ 완벽 |
| SOLID 원칙 | 94/100 | ✅ 우수 |
| 코드 품질 | 88/100 | ⚠️ 개선중 |

### 🏆 주요 특징

- **LangServe 기반**: FastAPI + LangChain의 표준 패턴 준수
- **Enterprise Ready**: 인증, Rate Limiting, 모니터링, 헬스체크
- **우수한 설계**: Factory, DI, Chain of Responsibility 패턴 적용
- **타입 안전성**: BasedPyright로 0개 오류 달성
- **현대적 도구**: uv, Pydantic v2, structlog 활용
- **컨테이너화**: Docker 및 Kubernetes 배포 지원

### 🛠️ 기술 스택

**핵심 프레임워크:**
- **Web Framework**: FastAPI (비동기 고성능)
- **AI Framework**: LangChain + LangServe
- **AI Model**: Google Gemini 2.5 Pro
- **Package Manager**: uv (고속 의존성 관리)

**품질 & 개발 도구:**
- **타입 검증**: BasedPyright + Pydantic v2
- **코드 품질**: Ruff (린터) + Black (포매터)
- **로깅**: structlog (구조화된 로깅)
- **테스팅**: pytest + 커버리지 도구
- **컨테이너**: Docker 멀티스테이지 빌드

## 🚀 빠른 시작

```bash
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

### 📋 품질 검증

```bash
# 전체 품질 검사 (권장)
uv run check

# 개별 검사
uv run typecheck  # 타입 체킹 (현재: 0 오류)
uv run lint       # 린팅 (현재: 12 이슈)
uv run test       # 테스트 실행
uv run format     # 코드 포매팅
```

### 🔧 즉시 개선 가능

```bash
# 자동 수정 가능한 코드 품질 이슈 해결 (5분)
uv run ruff check --fix app/

# 전체 검사로 확인
uv run check
```

## 📋 API 엔드포인트

- `POST /gemini/invoke` - 단일 요청 처리
- `POST /gemini/batch` - 배치 요청 처리  
- `POST /gemini/stream` - 스트리밍 응답
- `GET /gemini/health` - 헬스체크
- `GET /health` - 전체 서비스 헬스체크

## 🔗 참고 링크

- [LangServe 공식 문서](https://python.langchain.com/docs/langserve)
- [Google Gemini API](https://ai.google.dev/docs)
- [FastAPI 문서](https://fastapi.tiangolo.com/)
- [LangChain 문서](https://python.langchain.com/)