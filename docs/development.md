# 개발자 가이드

## 🛠️ 개발 환경 설정

### 시스템 요구사항
- Python 3.11 이상
- [uv](https://github.com/astral-sh/uv) 패키지 매니저
- Git
- Docker (선택적)

### 초기 설정

#### 1. 저장소 클론
```bash
git clone <repository-url>
cd iroom-backend-ai
```

#### 2. uv 설치
```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 설치 확인
uv --version
```

#### 3. 프로젝트 의존성 설치
```bash
# 개발 의존성 포함 전체 설치
uv sync

# 프로덕션 의존성만 설치
uv sync --no-dev
```

#### 4. 환경 변수 설정
```bash
# .env 파일 생성
cp .env.example .env

# .env 파일 편집
nano .env
```

#### .env 파일 예시
```bash
# Gemini API 설정
GEMINI_API_KEY=your_google_api_key_here
GEMINI_MODEL=gemini-2.5-pro
GEMINI_TEMPERATURE=0.7
GEMINI_MAX_TOKENS=32000

# 서버 설정
HOST=0.0.0.0
PORT=8000
DEBUG=true
LOG_LEVEL=DEBUG

# 인증 설정 (개발시 비활성화)
REQUIRE_API_KEY=false
VALID_API_KEYS=[]

# Rate Limiting (개발시 관대하게)
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS_PER_MINUTE=60

# CORS (개발시 모든 origin 허용)
CORS_ORIGINS=["*"]
```

## 🚀 개발 서버 실행

### 다양한 실행 방법

#### 1. 개발 서버 (권장)
```bash
# Hot reload 포함 개발 서버
uv run dev

# 또는 직접 실행
uv run uvicorn app.server:app --reload --host 0.0.0.0 --port 8000
```

#### 2. 프로덕션 서버
```bash
# 프로덕션 설정으로 실행
uv run serve

# 또는
uv run python -m app.server
```

#### 3. 커스텀 설정
```bash
# 포트 변경
uv run uvicorn app.server:app --port 8080 --reload

# 로그 레벨 변경
LOG_LEVEL=INFO uv run dev
```

### 서버 확인
```bash
# 헬스체크
curl http://localhost:8000/health

# API 문서
open http://localhost:8000/docs
```

## 🧪 테스트

### 테스트 실행

#### 전체 테스트
```bash
# 모든 테스트 실행
uv run test

# 또는 직접 pytest 실행
uv run pytest

# 상세 출력
uv run pytest -v

# 커버리지 포함
uv run pytest --cov=app
```

#### 특정 테스트 실행
```bash
# 특정 파일
uv run pytest tests/test_gemini_langserve.py

# 특정 함수
uv run pytest tests/test_gemini_langserve.py::test_gemini_invoke_schema

# 패턴 매칭
uv run pytest -k "gemini"
```

### 테스트 작성 가이드

#### 테스트 파일 구조
```
tests/
├── __init__.py
├── conftest.py              # 공통 fixtures
├── test_server.py           # 서버 기본 기능
├── test_gemini_langserve.py # Gemini LangServe 통합
├── test_auth_and_rate_limit.py # 인증 및 Rate Limiting
└── test_app_endpoints.py    # 엔드포인트 테스트
```

#### 테스트 예시
```python
# tests/test_example.py
import pytest
from fastapi.testclient import TestClient

from app.server import create_app
from app.config.settings import Settings


class TestSettings(Settings):
    """테스트용 설정"""
    debug: bool = True
    require_api_key: bool = False
    rate_limit_enabled: bool = False
    gemini_api_key: str = "test-key"


@pytest.fixture
def client():
    """테스트 클라이언트 생성"""
    app = create_app(TestSettings())
    return TestClient(app)


def test_health_endpoint(client: TestClient):
    """헬스체크 엔드포인트 테스트"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_gemini_invoke_schema(client: TestClient):
    """Gemini invoke 스키마 테스트"""
    payload = {
        "input": {
            "input": "테스트 질문"
        }
    }
    response = client.post("/gemini/invoke", json=payload)
    # 실제 API 호출 없이 스키마만 검증
    assert response.status_code in {200, 500}
```

## 🎨 코드 스타일 및 품질

### 현재 코드 품질 상태

#### ✅ 강점
- **타입 체킹**: BasedPyright로 **0개 오류** (완벽한 타입 안전성)
- **모듈 구조**: 명확한 책임 분리와 높은 응집도
- **설계 패턴**: Factory, DI, Chain of Responsibility 우수 적용
- **SOLID 원칙**: 94% 준수도 (매우 우수)

#### ⚠️ 개선 필요 영역 (린팅 12개 이슈)

**1. 미사용 Import (3개 - 자동 수정 가능)**
```python
# app/routes/gemini.py
- from pydantic import BaseModel  # 사용하지 않음
- from typing import Any          # 사용하지 않음

# app/server.py 
- from fastapi.openapi.utils import get_openapi  # 사용하지 않음
```

**2. Import 순서 (8개 - 환경변수 로딩 vs 린터 규칙)**
```python
# app/server.py - 다음 패턴으로 해결 방안:
# 1. 환경변수 로딩을 별도 모듈로 분리
# 2. 또는 # ruff: noqa: E402 코멘트 추가
```

**3. Bare Exception (1개 - 보안 이슈)**
```python
# app/middleware/rate_limit.py:234
# 현재:
except:
    estimated_tokens = 100

# 개선:
except (json.JSONDecodeError, ValueError, KeyError):
    estimated_tokens = 100
```

### 코드 품질 수정 가이드

#### 1. 자동 수정 가능한 이슈 해결
```bash
# 미사용 import와 기본 린팅 이슈 수정
uv run ruff check --fix app/
```

#### 2. 예외 처리 개선
```python
# app/middleware/rate_limit.py 수정
# 전:
except:
    estimated_tokens = 100
    
# 후:
except (json.JSONDecodeError, ValueError, KeyError) as e:
    logger.warning("요청 파싱 실패", error=str(e))
    estimated_tokens = 100
```

#### 3. Import 순서 최적화
```python
# app/server.py 수정 가이드:
# 방법 1: 환경변수 로딩을 설정 모듈에서 처리
# 방법 2: ruff 예외 설정 사용

# 추천: 방법 1 - 설정 모듈에서 dotenv 처리
```

### 코드 품질 도구

#### 타입 체킹
```bash
# BasedPyright로 타입 체킹
uv run typecheck

# 현재 상태: 0개 오류! (우수)
```

#### 코드 포맷팅
```bash
# Black으로 포맷팅
uv run format

# 또는 직접 Black 실행
uv run black app/ tests/

# 체크만 (변경하지 않음)
uv run black --check app/
```

#### 린팅
```bash
# Ruff로 린팅
uv run lint

# 또는 직접 Ruff 실행
uv run ruff check app/ tests/

# 자동 수정 가능한 이슈 수정
uv run ruff check --fix app/

# 현재 이슈: 12개 (대부분 자동 수정 가능)
```

### 통합 품질 검사
```bash
# 전체 코드 품질 검사
uv run check

# 이는 다음을 순차 실행:
# 1. basedpyright (타입 체킹) - 현재 0 오류
# 2. ruff check (린팅) - 현재 12 이슈
# 3. black --check (포맷 검사)
# 4. pytest (테스트)
```

### 코드 품질 개선 체크리스트

#### ✅ 즉시 수정 가능 (5분 내)
- [ ] `uv run ruff check --fix app/` 실행으로 미사용 import 제거
- [ ] rate_limit.py:234 bare exception 수정
- [ ] 수정 후 `uv run check`로 전체 검사

#### ✅ 단기 개선 (1주 내)
- [ ] Import 순서 최적화 전략 결정
- [ ] Pre-commit 훅 설정
- [ ] 코드 커버리지 85% 이상 달성

#### ✅ 중기 개선 (1개월 내)
- [ ] SonarQube 코드 품질 게이트 구축
- [ ] 코드 복잡도 메트릭 모니터링
- [ ] CodeClimate 또는 Codecov 통합

## 📁 프로젝트 구조 이해

### 디렉터리별 역할

#### `app/` - 메인 애플리케이션
```
app/
├── __init__.py              # 패키지 초기화
├── server.py               # FastAPI 앱 팩토리
├── config/                 # 설정 관리
│   ├── __init__.py
│   └── settings.py         # Pydantic Settings
├── middleware/             # 미들웨어 계층
│   ├── __init__.py
│   ├── auth.py            # 인증
│   ├── cors.py            # CORS
│   ├── logging.py         # 로깅
│   └── rate_limit.py      # Rate Limiting
├── routes/                # API 라우팅
│   ├── __init__.py
│   ├── gemini.py          # Gemini API 라우트
│   └── health.py          # 헬스체크
├── utils/                 # 유틸리티
│   ├── __init__.py
│   └── errors.py          # 에러 핸들링
└── scripts.py             # 개발 스크립트
```

#### `tests/` - 테스트 코드
- 각 모듈별 테스트 파일
- 공통 fixtures와 설정
- 통합 테스트 및 단위 테스트

#### `docs/` - 문서
- 프로젝트 문서화
- API 가이드
- 아키텍처 설명

## 🔧 개발 도구 활용

### uv 명령어 가이드

#### 의존성 관리
```bash
# 새 패키지 설치
uv add package-name

# 개발 의존성 설치
uv add --dev package-name

# 패키지 제거
uv remove package-name

# 의존성 동기화
uv sync

# 의존성 트리 확인
uv tree
```

#### 스크립트 실행
```bash
# pyproject.toml에 정의된 스크립트들
uv run start     # 프로덕션 서버
uv run dev       # 개발 서버
uv run test      # 테스트 실행
uv run lint      # 린팅
uv run format    # 포맷팅
uv run check     # 전체 검사
```

### VSCode 설정

#### `.vscode/settings.json` (코드 품질 최적화)
```json
{
    "python.defaultInterpreterPath": "./.venv/bin/python",
    "python.formatting.provider": "black",
    "python.linting.enabled": true,
    "python.linting.ruffEnabled": true,
    "python.testing.pytestEnabled": true,
    "python.testing.pytestArgs": ["tests"],
    "python.analysis.typeCheckingMode": "standard",
    "python.analysis.autoImportCompletions": true,
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
        "source.organizeImports": true,
        "source.fixAll.ruff": true
    },
    "files.exclude": {
        "**/__pycache__": true,
        "**/.pytest_cache": true,
        "**/uv.lock": true,
        "**/.ruff_cache": true
    },
    "files.watcherExclude": {
        "**/.venv/**": true,
        "**/node_modules/**": true,
        "**/__pycache__/**": true
    }
}
```

#### 추천 확장 (코드 품질 중심)
- **Python** - 필수 기본 확장
- **Ruff** - 린팅 및 자동 수정
- **Black Formatter** - 코드 포매팅
- **Pylance** - 인텔리센스 및 타입 체킹
- **Thunder Client** - API 테스트
- **GitLens** - Git 통합 및 코드 역사
- **Todo Tree** - TODO 코멘트 시각화

## 🔄 Git 워크플로우

### 브랜치 전략
```bash
# 새 기능 개발
git checkout -b feature/new-feature
git commit -m "feat: add new feature"

# 버그 수정
git checkout -b fix/bug-description
git commit -m "fix: resolve bug description"

# 문서 업데이트
git checkout -b docs/update-readme
git commit -m "docs: update README"
```

### 커밋 메시지 컨벤션
```
type(scope): subject

types:
- feat: 새 기능
- fix: 버그 수정
- docs: 문서 변경
- style: 코드 스타일 변경
- refactor: 코드 리팩토링
- test: 테스트 추가/수정
- chore: 빌드/도구 변경

예시:
feat(gemini): add streaming support
fix(auth): resolve API key validation
docs(api): update usage examples
```

### Pre-commit 훅 설정
```bash
# pre-commit 설치
uv add --dev pre-commit

# 훅 설치
uv run pre-commit install

# 수동 실행
uv run pre-commit run --all-files
```

#### `.pre-commit-config.yaml` (코드 품질 자동화)
```yaml
repos:
  # Ruff 린터 및 포매터
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.2.1
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
      - id: ruff-format
  
  # 추가 품질 검사
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
      - id: check-merge-conflict
      - id: debug-statements
  
  # 타입 체킹 (선택적)
  - repo: https://github.com/DetachHead/basedpyright
    rev: v1.10.3  
    hooks:
      - id: basedpyright
```

**Pre-commit 설정 시 이점:**
- 커밋 전 자동 코드 품질 검사
- 린팅 오류 사전 차단
- 코드 일관성 유지

## 🐛 디버깅

### 로그 활용

#### 구조화된 로깅
```python
import structlog

logger = structlog.get_logger("module_name")

# 정보 로깅
logger.info("Processing request", user_id=123, action="create")

# 에러 로깅
logger.error("Database connection failed", 
            error=str(e), 
            retry_count=3)

# 디버그 로깅 (DEBUG 레벨에서만)
logger.debug("Variable state", variables={"x": 1, "y": 2})
```

#### 로그 레벨 조정
```bash
# 환경변수로 조정
LOG_LEVEL=DEBUG uv run dev

# 또는 .env 파일에서
LOG_LEVEL=DEBUG
```

### 디버거 사용

#### Python 디버거
```python
# 브레이크포인트 설정
import pdb; pdb.set_trace()

# 또는 Python 3.7+
breakpoint()
```

#### FastAPI 디버그 모드
```python
# 개발시 자동으로 활성화
DEBUG=true uv run dev
```

### API 테스트 도구

#### curl 예시
```bash
# 기본 요청
curl -X POST http://localhost:8000/gemini/invoke \
  -H "Content-Type: application/json" \
  -d '{"input": {"input": "test"}}'

# 상세 출력
curl -v -X POST http://localhost:8000/gemini/invoke \
  -H "Content-Type: application/json" \
  -d '{"input": {"input": "test"}}'
```

#### httpx 클라이언트
```python
import httpx

# 동기 클라이언트
with httpx.Client() as client:
    response = client.post(
        "http://localhost:8000/gemini/invoke",
        json={"input": {"input": "test"}}
    )
    print(response.json())

# 비동기 클라이언트
import asyncio

async def test_api():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/gemini/invoke",
            json={"input": {"input": "test"}}
        )
        return response.json()

result = asyncio.run(test_api())
```

## 🚀 배포 준비

### Docker 로컬 테스트
```bash
# 이미지 빌드
docker build -t iroom-backend-ai .

# 컨테이너 실행
docker run -p 8080:8080 \
  -e GEMINI_API_KEY=your_key \
  iroom-backend-ai

# 테스트
curl http://localhost:8080/health
```

### 환경별 설정

#### 개발 환경
```bash
DEBUG=true
LOG_LEVEL=DEBUG
REQUIRE_API_KEY=false
RATE_LIMIT_ENABLED=false
```

#### 스테이징 환경
```bash
DEBUG=false
LOG_LEVEL=INFO
REQUIRE_API_KEY=true
RATE_LIMIT_ENABLED=true
```

#### 프로덕션 환경
```bash
DEBUG=false
LOG_LEVEL=WARNING
REQUIRE_API_KEY=true
RATE_LIMIT_ENABLED=true
CORS_ORIGINS=["https://yourdomain.com"]
```

## 📚 추가 리소스

### 관련 문서
- [LangServe 공식 문서](https://python.langchain.com/docs/langserve)
- [FastAPI 문서](https://fastapi.tiangolo.com/)
- [Pydantic 문서](https://docs.pydantic.dev/)
- [uv 문서](https://github.com/astral-sh/uv)

### 커뮤니티
- [LangChain GitHub](https://github.com/langchain-ai/langchain)
- [FastAPI GitHub](https://github.com/tiangolo/fastapi)

---

**해피 코딩! 🎉 문제가 있으면 이슈를 생성해주세요.**